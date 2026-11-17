"""Duplicate rows three ways and the keep rule (core.duplicates), the preview dialog."""
import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from songselector.core.duplicates import (
    ARTIST_TITLE,
    PATH,
    SAME_FILE,
    artist_title_key,
    filled,
    find_duplicates,
    richness,
)


def row(path, artist='Artist', title='Title', **fields):
    return {'File_Path': str(path), 'Artist': artist, 'Title': title, **fields}


class KeepRuleTests(unittest.TestCase):
    def test_filled_ignores_empty_nan_and_zero_colours_and_ratings(self):
        self.assertFalse(filled(None))
        self.assertFalse(filled(float('nan')))
        self.assertFalse(filled('  '))
        self.assertFalse(filled(0, 'Color'))
        self.assertFalse(filled('0', 'SS_Rating'))
        self.assertTrue(filled(0, 'BPM'))
        self.assertTrue(filled(3, 'Rating'))
        self.assertEqual(richness(row('a', Comment='peak', Color=0, Rating=4, Genre='')), 4)  # artist, title, comment, rating

    def test_artist_title_ignores_case_and_spaces_and_needs_both(self):
        self.assertEqual(artist_title_key(row('a', ' Daft  Punk', 'One More Time ')),
                         artist_title_key(row('b', 'daft punk', 'one more time')))
        self.assertEqual(artist_title_key(row('a', '', 'Intro')), '')
        self.assertEqual(artist_title_key(row('a', 'Artist', None)), '')

    def test_existing_file_wins_then_richest_then_collection_then_first(self):
        exists = {'/gone.mp3': False}.get
        table = pd.DataFrame([
            row('/gone.mp3', Comment='rich', Rating=5, Color=3, Genre='Breaks'),  # richest, but the file is gone
            row('/plain.mp3'),
            row('/rich.mp3', Comment='rich'),
        ])
        [group] = find_duplicates(table, ARTIST_TITLE, exists=lambda path: exists(path, True))
        self.assertEqual((group.keep, group.remove), (2, [1, 0]))
        self.assertIn('file missing', group.reasons[0])
        self.assertIn('3 fields filled in', group.reasons[2])
        # a tie in information: the one in the Traktor / Rekordbox collection, else the first
        table = pd.DataFrame([row('/a.mp3'), row('/b.mp3'), row('/c.mp3')])
        [group] = find_duplicates(table, ARTIST_TITLE, in_collection=lambda path: path == '/b.mp3', exists=lambda p: True)
        self.assertEqual(group.keep, 1)
        self.assertIn('collection', group.reasons[1])
        [group] = find_duplicates(table, ARTIST_TITLE, exists=lambda p: True)
        self.assertEqual((group.keep, group.remove), (0, [1, 2]))


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_same_path_ignores_case_and_slashes(self):
        table = pd.DataFrame([row(r'E:\Music\a.mp3', title='One'), row('e:/music/A.MP3', title='Two'),
                              row(r'E:\Music\b.mp3', title='One')])
        [group] = find_duplicates(table, PATH, exists=lambda p: True)
        self.assertEqual((group.keep, group.remove), (0, [1]))

    def test_unknown_mode_and_empty_tables(self):
        self.assertEqual(find_duplicates(pd.DataFrame(), PATH), [])
        self.assertEqual(find_duplicates(None, PATH), [])
        with self.assertRaises(ValueError):
            find_duplicates(pd.DataFrame([row('a')]), 'nonsense')

    def test_same_file_finds_copies_and_hashes_only_files_of_equal_size(self):
        original = self.root / 'a' / 'song.mp3'
        copy = self.root / 'b' / 'song (copy).mp3'
        same_size = self.root / 'c.mp3'
        other = self.root / 'd.mp3'
        for path, content in ((original, b'x' * 1000), (copy, b'x' * 1000), (same_size, b'y' * 1000), (other, b'z' * 10)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        hashed = []

        def digest(path):
            from songselector.core.duplicates import file_digest
            hashed.append(Path(path).name)
            return file_digest(path)

        table = pd.DataFrame([row(original, 'A', 'One'), row(copy, 'B', 'Other name'), row(same_size, 'C', 'X'),
                              row(other, 'D', 'Y'), row(self.root / 'missing.mp3', 'E', 'Z')])
        [group] = find_duplicates(table, SAME_FILE, digest=digest)
        self.assertEqual((group.keep, group.remove), (0, [1]))
        self.assertEqual(sorted(hashed), ['c.mp3', 'song (copy).mp3', 'song.mp3'])  # d.mp3: its size is unique


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def test_unticked_rows_are_kept(self):
        from PyQt5.QtCore import Qt

        from songselector.ui.duplicates_dialog import DuplicatesDialog
        table = pd.DataFrame([row('/a.mp3'), row('/b.mp3'), row('/c.mp3')])
        groups = find_duplicates(table, ARTIST_TITLE, exists=lambda p: True)
        dialog = DuplicatesDialog(ARTIST_TITLE, groups, table.to_dict('index'))
        self.assertEqual(dialog.removed_indexes(), [1, 2])
        self.assertEqual(dialog.ok_button.text(), 'Remove 2 row(s)')
        dialog.tree.topLevelItem(0).child(0).setCheckState(0, Qt.Unchecked)
        self.assertEqual(dialog.removed_indexes(), [2])
        self.assertEqual(dialog.ok_button.text(), 'Remove 1 row(s)')
        dialog.tree.topLevelItem(0).child(1).setCheckState(0, Qt.Unchecked)
        self.assertFalse(dialog.ok_button.isEnabled())
        self.assertIn('Keep: Artist - Title', dialog.tree.topLevelItem(0).text(0))


if __name__ == '__main__':
    unittest.main()
