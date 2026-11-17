"""Cover art: reading it (core.cover_art), the thumbnail cache and loader, the Cover column."""
import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
import soundfile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3
from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication
from test_imports import tagged_file
from test_song_selector_fields import GuiTestBase

from songselector.core.cover_art import cache_keys, embedded_cover, find_cover, folder_cover
from songselector.ui.covers import CoverProvider


def image_bytes(colour, size=200, fmt='PNG'):
    image = QImage(size, size, QImage.Format_RGB32)
    image.fill(QColor(colour))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, fmt)
    return bytes(data)


def add_pictures(path, *pictures):
    """pictures: (picture type, bytes); 3 = front cover."""
    tags = ID3(str(path))
    for kind, data in pictures:
        tags.add(APIC(encoding=3, mime='image/png', type=kind, desc=str(kind), data=data))
    tags.save(str(path))


class CoverReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_mp3_front_cover_is_preferred(self):
        song = tagged_file(self.root / 'song.mp3')
        blue, red = image_bytes('blue'), image_bytes('red')
        add_pictures(song, (4, blue), (3, red))  # back cover first, then the front
        self.assertEqual(embedded_cover(song), red)
        other = tagged_file(self.root / 'other.mp3')
        add_pictures(other, (0, blue))           # only "other": still a cover
        self.assertEqual(embedded_cover(other), blue)

    def test_flac_picture(self):
        path = self.root / 'song.flac'
        soundfile.write(path, np.zeros(4410, dtype=np.float32), 44100)
        audio = FLAC(str(path))
        picture = Picture()
        picture.type, picture.mime, picture.data = 3, 'image/png', image_bytes('green')
        audio.add_picture(picture)
        audio.save()
        self.assertEqual(embedded_cover(path), image_bytes('green'))

    def test_cover_file_next_to_the_track_when_nothing_is_embedded(self):
        song = tagged_file(self.root / 'song.mp3')
        self.assertIsNone(find_cover(song))
        (self.root / 'Folder.JPG').write_bytes(image_bytes('yellow', fmt='JPG'))  # any case
        self.assertEqual(folder_cover(song), (self.root / 'Folder.JPG').read_bytes())
        (self.root / 'cover.png').write_bytes(image_bytes('red'))                # cover.* comes before folder.*
        self.assertEqual(find_cover(song), image_bytes('red'))
        add_pictures(song, (3, image_bytes('blue')))                             # embedded comes first
        self.assertEqual(find_cover(song), image_bytes('blue'))

    def test_missing_or_unreadable_files_have_no_cover(self):
        self.assertIsNone(embedded_cover(self.root / 'gone.mp3'))
        self.assertIsNone(find_cover(self.root / 'gone.mp3'))
        (self.root / 'text.mp3').write_text('not audio')
        self.assertIsNone(embedded_cover(self.root / 'text.mp3'))
        self.assertEqual(cache_keys(self.root / 'gone.mp3'), (None, None))

    def test_cache_keys_change_with_the_file_and_the_no_cover_key_also_with_its_folder(self):
        song = tagged_file(self.root / 'song.mp3')
        cover, none = cache_keys(song)
        self.assertEqual(cache_keys(song), (cover, none))
        time.sleep(0.02)
        (self.root / 'cover.jpg').write_bytes(b'x')  # a cover added to the folder
        self.assertEqual(cache_keys(song)[0], cover)   # a found cover stays valid
        self.assertNotEqual(cache_keys(song)[1], none)  # "no cover" is checked again
        time.sleep(0.02)
        add_pictures(song, (3, image_bytes('red')))  # the file itself changed
        self.assertNotEqual(cache_keys(song)[0], cover)


class CoverProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.addCleanup(self.temp.cleanup)  # cleanups run last-in first-out: after the providers stopped
        self.root = Path(self.temp.name)
        self.cache = self.root / 'covers'

    def wait(self, provider, path):
        provider.pixmap(path)  # request it
        deadline = time.monotonic() + 10
        while not provider.known(path) and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        return provider.pixmap(path)

    def test_loads_in_the_background_and_caches_a_thumbnail_on_disk(self):
        song = tagged_file(self.root / 'song.mp3')
        add_pictures(song, (3, image_bytes('red', size=600)))
        bare = tagged_file(self.root / 'bare.mp3')
        provider = CoverProvider(self.cache)
        self.addCleanup(provider.stop)
        ready = []
        provider.ready.connect(ready.append)
        self.assertIsNone(provider.pixmap(song))  # not known yet: requested
        pixmap = self.wait(provider, song)
        self.assertEqual(max(pixmap.width(), pixmap.height()), 128)  # a thumbnail, not the 600 px original
        self.assertEqual(QColor(pixmap.toImage().pixel(64, 64)).name(), '#ff0000')
        self.assertTrue(provider.cached_file(song).is_file())
        self.assertIsNone(self.wait(provider, bare))
        self.assertTrue(any(name.suffix == '.none' for name in self.cache.iterdir()))  # "no cover" remembered
        self.assertEqual(len(ready), 2)

        def must_not_read(_path):
            raise AssertionError('the file was read again')
        again = CoverProvider(self.cache, finder=must_not_read)  # a new start: everything from the disk cache
        self.addCleanup(again.stop)
        self.assertIsNotNone(self.wait(again, song))
        self.assertIsNone(self.wait(again, bare))
        self.assertTrue(again.known(bare))

    def test_broken_picture_data_counts_as_no_cover(self):
        song = tagged_file(self.root / 'song.mp3')
        add_pictures(song, (3, b'not an image'))
        provider = CoverProvider(self.cache)
        self.addCleanup(provider.stop)
        provider.pixmap(song)
        self.assertIsNone(self.wait(provider, song))
        self.assertTrue(provider.known(song))


class CoverColumnTests(GuiTestBase):
    def wait_for_covers(self, window):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            window.candidate_tree.viewport().repaint()  # painting requests the covers
            self.application.processEvents()
            if all(window.covers.known(path) for path in (self.song, self.other)):
                break
            time.sleep(0.01)
        window._repaint_covers()
        self.application.processEvents()

    def test_off_by_default_then_square_and_cropped_rows(self):
        from songselector.config import HEADER_INDEX
        add_pictures(self.song, (3, image_bytes('red')))
        window = self.window()
        window.resize(1200, 600)
        window.show()
        tree, column = window.candidate_tree, HEADER_INDEX['Cover']
        self.assertTrue(tree.isColumnHidden(column))        # nothing changes until a style is chosen
        normal = tree.visualItemRect(tree.topLevelItem(0)).height()
        window.cover_style_actions['square'].trigger()
        window.cover_size_actions[72].trigger()
        self.application.processEvents()
        self.assertFalse(tree.isColumnHidden(column))
        self.assertEqual(tree.header().visualIndex(column), 1)  # right after #
        self.assertEqual(tree.visualItemRect(tree.topLevelItem(0)).height(), 72)  # square rows, also without a cover
        self.wait_for_covers(window)
        item = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                    if tree.topLevelItem(i).text(HEADER_INDEX['Path']) == str(self.song))
        cell = tree.visualRect(tree.indexFromItem(item, column))
        shot = tree.viewport().grab().toImage()
        self.assertEqual(QColor(shot.pixel(cell.center())).name(), '#ff0000')  # the cover is painted
        window.cover_style_actions['cropped'].trigger()
        self.application.processEvents()
        self.assertEqual(tree.visualItemRect(tree.topLevelItem(0)).height(), normal)  # normal rows again
        self.assertEqual(tree.columnWidth(column), 76)
        self.assertEqual(window.settings['Cover art'], 'cropped')
        self.assertEqual(window.settings['Cover size'], 72)
        self.assertFalse(window.playlist_tree.isColumnHidden(column))  # the Playlist shows covers too
        window.cover_style_actions['off'].trigger()
        self.assertTrue(tree.isColumnHidden(column))
        self.assertTrue(window.playlist_tree.isColumnHidden(column))


if __name__ == '__main__':
    unittest.main()
