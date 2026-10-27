import json
import ntpath
import os
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET

from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, TKEY, TBPM, COMM, POPM, TXXX
from traktor_key_calculator.core.key_formats import parse_key, parse_bpm, nml_key, CAMELOT_MAJOR, CAMELOT_MINOR, OPEN_MAJOR, OPEN_MINOR
from traktor_key_calculator.core.audio_metadata import extract_audio_metadata
from traktor_key_calculator.core.track_import import TrackImporter, ImportedTrackStore, merge_tracks
from traktor_key_calculator.core.traktor_collection import TraktorCollection, canonical_path
from traktor_key_calculator.core.library_store import LibraryStore
from traktor_key_calculator.ui.theme import row_tint_alpha


def tagged_file(path, key='C', bpm='100'):
    tags = ID3()
    tags.add(TIT2(encoding=3, text=['Test title']))
    tags.add(TPE1(encoding=3, text=['Test artist']))
    tags.add(TALB(encoding=3, text=['Test album']))
    tags.add(TCON(encoding=3, text=['Breakbeat']))
    tags.add(COMM(encoding=3, lang='hun', desc='', text=['Test comment']))
    tags.add(POPM(email='traktor@native-instruments.de', rating=204, count=0))
    if key is not None:
        tags.add(TKEY(encoding=3, text=[key]))
    if bpm is not None:
        tags.add(TBPM(encoding=3, text=[bpm]))
    tags.save(path)
    return path


def make_collection(path, records):
    root = ET.Element('NML', VERSION='19')
    collection = ET.SubElement(root, 'COLLECTION', ENTRIES=str(len(records)))
    for filepath, key, bpm in records:
        entry = ET.SubElement(collection, 'ENTRY', ARTIST='Collection artist', TITLE='Collection title')
        drive, tail = ntpath.splitdrive(str(filepath.parent))
        ET.SubElement(entry, 'LOCATION', VOLUME=drive, DIR=tail.replace('\\', '/:') + '/:', FILE=filepath.name)
        ET.SubElement(entry, 'INFO', GENRE='Collection genre', COMMENT='Collection comment', COLOR='5',
                      RANKING='255', FILESIZE=str(round(filepath.stat().st_size / 1024)))
        ET.SubElement(entry, 'TEMPO', BPM=str(bpm))
        ET.SubElement(entry, 'MUSICAL_KEY', VALUE=str(key))
        ET.SubElement(entry, 'ALBUM', TITLE='Collection album')
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()

    def test_all_key_notations(self):
        for index in range(12):
            self.assertEqual(parse_key(f'{index+1}A'), (CAMELOT_MINOR[index], 'minor'))
            self.assertEqual(parse_key(f'{index+1}B'), (CAMELOT_MAJOR[index], 'major'))
            self.assertEqual(parse_key(f'{index+1}d'), (OPEN_MAJOR[index], 'major'))
            self.assertEqual(parse_key(f'{index+1}m'), (OPEN_MINOR[index], 'minor'))
        self.assertEqual(parse_key('3m'), ('B', 'minor'))
        self.assertEqual(parse_key('Bbm'), ('A#', 'minor'))
        self.assertEqual(parse_key('F# minor'), ('F#', 'minor'))
        self.assertEqual(parse_key('Db major'), ('C#', 'major'))
        self.assertEqual(nml_key('23'), ('B', 'minor'))
        self.assertIsNone(parse_key('unknown'))
        for value in ('nan', 'inf', '-1', '0', None):
            self.assertIsNone(parse_bpm(value))
        self.assertEqual(parse_bpm('128,5'), 128.5)

    def test_file_details_comments_and_ratings(self):
        path = tagged_file(self.root/'full.MP3', key='8A', bpm='128.5')
        metadata = extract_audio_metadata(path)
        self.assertEqual(metadata.artist, 'Test artist')
        self.assertEqual(metadata.album, 'Test album')
        self.assertEqual(metadata.comment, 'Test comment')
        self.assertEqual(metadata.rating, 4)
        row = TrackImporter().read(path)
        self.assertEqual((row['Musical_Key_Base'], row['BaseMinorOrMajor']), ('A', 'minor'))
        self.assertEqual(row['BPM'], 128.5)
        self.assertEqual(row['Key_Source'], 'File tags')

    def test_user_text_key_tag(self):
        path = tagged_file(self.root/'txxx.mp3', key=None)
        tags = ID3(path)
        tags.add(TXXX(encoding=3, desc='INITIALKEY', text=['11B']))
        tags.save(path)
        row = TrackImporter().read(path)
        self.assertEqual((row['Musical_Key_Base'], row['BaseMinorOrMajor']), ('A', 'major'))

    def test_collection_fallback_precision_and_tag_priority(self):
        fallback = tagged_file(self.root/'fallback.mp3', key=None, bpm=None)
        tagged = tagged_file(self.root/'tagged.mp3', key='8A', bpm='100')
        collection = self.root/'collection.nml'
        make_collection(collection, [(fallback, 23, 125.23), (tagged, 0, 100.25)])
        importer = TrackImporter(collection)
        row = importer.read(fallback)
        self.assertEqual((row['Musical_Key_Base'], row['BaseMinorOrMajor']), ('B', 'minor'))
        self.assertEqual(row['BPM'], 125.23)
        self.assertEqual(row['Color'], 5)
        self.assertEqual(row['Key_Source'], 'Traktor collection')
        row = importer.read(tagged)
        self.assertEqual(row['Musical_Key_Base'], 'A')
        self.assertEqual(row['BaseMinorOrMajor'], 'minor')
        self.assertEqual(row['BPM'], 100.25)
        tags = ID3(tagged)
        tags.add(TBPM(encoding=3, text=['140']))
        tags.save(tagged)
        self.assertEqual(importer.read(tagged)['BPM'], 140)

    def test_ambiguous_collection_filenames_not_guessed(self):
        locations = []
        for folder in ('one', 'two', 'three'):
            (self.root/folder).mkdir()
            locations.append(tagged_file(self.root/folder/'same.mp3', key=None, bpm=None))
        collection = self.root/'collection.nml'
        make_collection(collection, [(locations[0], 0, 100), (locations[1], 12, 100)])
        index = TraktorCollection(collection)
        self.assertIsNone(index.find(locations[2]))
        self.assertEqual(index.find(locations[0])['key'], ('C', 'major'))

    def test_unique_relocated_file_and_collection_reload(self):
        path = tagged_file(self.root/'song.mp3', key=None, bpm=None)
        collection = self.root/'collection.nml'
        make_collection(collection, [(path, 0, 100)])
        index = TraktorCollection(collection)
        (self.root/'moved').mkdir()
        copy = self.root/'moved'/'song.mp3'
        copy.write_bytes(path.read_bytes())
        self.assertEqual(index.find(copy)['key'], ('C', 'major'))
        make_collection(collection, [(path, 12, 150.33)])
        self.assertEqual(index.find(path)['key'], ('C', 'minor'))
        self.assertEqual(index.find(path)['bpm'], 150.33)

    def test_missing_metadata_is_explicit_and_persistence_deduplicates(self):
        path = self.root/'unknown.mp3'
        path.write_bytes(b'')
        row = TrackImporter().read(path)
        self.assertIsNone(row['Musical_Key_Base'])
        self.assertIsNone(row['BPM'])
        duplicate = dict(row, File_Path=row['File_Path'].upper())
        table = merge_tracks(None, [row, duplicate])
        self.assertEqual(len(table), 1)
        store = ImportedTrackStore(self.root/'imports.json')
        store.save({canonical_path(row['File_Path']): row})
        self.assertEqual(store.load()[canonical_path(row['File_Path'])], row)

    def test_bad_collection_does_not_stop_tag_import(self):
        collection = self.root/'bad.nml'
        collection.write_text('<broken>', encoding='utf-8')
        path = tagged_file(self.root/'song.mp3')
        importer = TrackImporter(collection)
        self.assertEqual(importer.read(path)['Musical_Key_Base'], 'C')
        self.assertTrue(importer.collection.error)


    def test_previous_details_survive_missing_tags_and_collection(self):
        file = self.root/'untagged.mp3'
        file.write_bytes(b'')
        previous = {'Artist': 'Known artist', 'Title': 'Known title', 'Album': 'Known album',
                    'Genre': 'Known genre', 'Comment': 'Known comment', 'Rating': 4,
                    'Musical_Key_Base': 'F#', 'BaseMinorOrMajor': 'minor', 'BPM': 123.4, 'Color': 2}
        row = TrackImporter().read(file, existing=previous)
        for field in previous:
            self.assertEqual(row[field], previous[field])
        self.assertEqual(row['Color_Source'], 'Loaded CSV')

    def test_collection_zero_color_overrides_previous_color(self):
        file = tagged_file(self.root/'cleared.mp3')
        collection = self.root/'collection.nml'
        make_collection(collection, [(file, 0, 100)])
        tree = ET.parse(collection)
        tree.find('./COLLECTION/ENTRY/INFO').set('COLOR', '0')
        tree.write(collection, encoding='utf-8')
        row = TrackImporter(collection).read(file, existing={'Color': 5})
        self.assertEqual(row['Color'], 0)
        self.assertEqual(row['Color_Source'], 'Traktor collection')


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def test_multi_file_drop_playlist_duplicates_unknowns_and_restart(self):
        from PyQt5.QtCore import QCoreApplication, QMimeData, QUrl, QPoint, QPointF, Qt
        from PyQt5.QtGui import QDragEnterEvent, QDropEvent
        from traktor_key_calculator.config import init_settings, HEADER_INDEX
        from traktor_key_calculator.ui.main_window import TraktorKeyCalculator
        import pandas as pd
        data = Path(os.environ['TRAKTOR_APP_DATA_DIR'])
        fixture = data/'gui-fixtures'
        fixture.mkdir(exist_ok=True)
        tagged = tagged_file(fixture/'tagged.mp3')
        fallback = tagged_file(fixture/'fallback.mp3', key=None, bpm=None)
        unknown = fixture/'unknown.mp3'
        unknown.write_bytes(b'')
        nml = fixture/'collection.nml'
        make_collection(nml, [(fallback, 23, 125.23)])
        init_settings()
        window = TraktorKeyCalculator()
        self.assertEqual(len(window.table), 2920)
        window.importer = TrackImporter(nml)
        window.table = pd.DataFrame()
        window.bpm_slider.setValue(100)
        window.populate_tree()
        window.search_bar.setText('a filter that excludes everything')
        window.current_advanced_search = {'enabled': True, 'filters': [{'column': 'Genre', 'condition': 'is', 'value': 'not matching'}]}
        window.advanced_filters = window.current_advanced_search['filters']

        def drop(tree, paths):
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
            enter = QDragEnterEvent(QPoint(8,8), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            QCoreApplication.sendEvent(tree.viewport(), enter)
            self.assertTrue(enter.isAccepted())
            event = QDropEvent(QPointF(8,8), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            QCoreApplication.sendEvent(tree.viewport(), event)
            self.assertTrue(event.isAccepted())
            self.application.processEvents()

        def item_for(tree, path):
            return next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                        if canonical_path(tree.topLevelItem(i).text(HEADER_INDEX['Path'])) == canonical_path(path))

        drop(window.candidate_tree, [tagged, fallback, unknown, tagged])
        self.assertEqual(len(window.table), 3)
        self.assertEqual(window.candidate_tree.topLevelItemCount(), 3)
        self.assertFalse(window.current_advanced_search['enabled'])
        self.assertTrue(all(not window.candidate_tree.topLevelItem(i).isHidden() for i in range(3)))
        item = item_for(window.candidate_tree, tagged)
        self.assertEqual(item.text(HEADER_INDEX['Artist']), 'Test artist')
        self.assertEqual(item.text(HEADER_INDEX['Album']), 'Test album')
        self.assertEqual(item.text(HEADER_INDEX['Rating']), '4')
        self.assertEqual(item.text(HEADER_INDEX['Original Key']), 'C major')
        self.assertEqual(item.text(HEADER_INDEX['New Key']), 'C major')
        self.assertEqual(item_for(window.candidate_tree, fallback).text(HEADER_INDEX['Original Key']), 'B minor')
        self.assertEqual(item_for(window.candidate_tree, unknown).text(HEADER_INDEX['Original Key']), 'Unknown')
        window.sort_by_column(HEADER_INDEX['Original BPM'])
        drop(window.playlist_tree, [tagged, tagged])
        self.assertEqual(window.playlist_tree.topLevelItemCount(), 1)
        self.assertTrue(item_for(window.candidate_tree, tagged).isHidden())
        window.bpm_slider.setValue(150)
        window.update_tree_after_slider()
        self.assertEqual(item_for(window.playlist_tree, tagged).text(HEADER_INDEX['New Key']), 'G major')
        self.assertEqual(item_for(window.playlist_tree, tagged).text(HEADER_INDEX['Original Key']), 'C major')
        drop(window.playlist_tree, [unknown])
        self.assertEqual(item_for(window.playlist_tree, unknown).text(HEADER_INDEX['New Key']), 'Unknown')
        window.clear_playlist()
        self.assertFalse(item_for(window.candidate_tree, tagged).isHidden())
        window.close()
        self.application.processEvents()
        restored = TraktorKeyCalculator()
        self.assertEqual(len(restored.saved_imports), 3)
        self.assertEqual(item_for(restored.candidate_tree, tagged).text(HEADER_INDEX['Original Key']), 'C major')
        restored.close()

    def test_real_mp3_tags_and_traktor_collection(self):
        path = Path(r'E:\DJ\BREAKBEAT\Afghan Headspin - The Calling.mp3')
        if not path.exists():
            self.skipTest('Local sample unavailable')
        importer = TrackImporter(r'E:\DJ\TRAKTOR\collection.nml')
        row = importer.read(path)
        self.assertEqual((row['Musical_Key_Base'], row['BaseMinorOrMajor']), ('B', 'minor'))
        self.assertGreater(row['BPM'], 134)
        self.assertLess(row['BPM'], 136)
        self.assertTrue(row['Artist'])
        self.assertTrue(row['Title'])
        self.assertEqual(len(importer.collection.by_path), 13353)



class ColorGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application=QApplication.instance() or QApplication([])

    def setUp(self):
        from traktor_key_calculator.config import init_settings
        from traktor_key_calculator.ui.main_window import TraktorKeyCalculator
        import pandas as pd
        self.temp=tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.root=Path(self.temp.name)
        self.file=self.root/'color.mp3'
        self.file.write_bytes(b'')
        self.collection=self.root/'collection.nml'
        make_collection(self.collection, [(self.file, 0, 100)])
        init_settings()
        self.window=TraktorKeyCalculator()
        self.window.coloring_mode='song'
        self.window.importer=TrackImporter(self.collection)
        self.window.library_store=LibraryStore(self.root/'library.sqlite')
        self.window.saved_imports={}
        self.window.table=pd.DataFrame()
        self.window.bpm_slider.setValue(100)
        self.window.populate_tree()

    def tearDown(self):
        self.window.close()
        self.application.processEvents()
        self.temp.cleanup()

    def drop(self, tree, path):
        from PyQt5.QtCore import QCoreApplication,QMimeData,QUrl,QPoint,QPointF,Qt
        from PyQt5.QtGui import QDragEnterEvent,QDropEvent
        mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(path))])
        enter=QDragEnterEvent(QPoint(8,8),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        QCoreApplication.sendEvent(tree.viewport(),enter)
        self.assertTrue(enter.isAccepted())
        event=QDropEvent(QPointF(8,8),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        QCoreApplication.sendEvent(tree.viewport(),event)
        self.assertTrue(event.isAccepted())
        self.application.processEvents()

    def test_category_color_and_all_collection_details_in_both_panels(self):
        from traktor_key_calculator.config import HEADER_INDEX,COLOR_MAPPING_CATEGORY
        self.drop(self.window.candidate_tree,self.file)
        self.drop(self.window.playlist_tree,self.file)
        for tree in (self.window.candidate_tree,self.window.playlist_tree):
            item=tree.topLevelItem(0)
            self.assertFalse(tree.isColumnHidden(HEADER_INDEX['Color']))
            expected={'Artist':'Collection artist','Title':'Collection title','Album':'Collection album',
                      'Genre':'Collection genre','Comment':'Collection comment','Rating':'5',
                      'Original Key':'C major','Color':'5'}
            for field,value in expected.items():
                self.assertEqual(item.text(HEADER_INDEX[field]),value)
            for column in range(tree.columnCount()):
                color=item.background(column).color()
                self.assertEqual(color.rgb(),COLOR_MAPPING_CATEGORY[5].rgb())
                self.assertEqual(color.alpha(),row_tint_alpha())  # depends on the theme
            self.assertIn('Color: Traktor collection',item.toolTip(HEADER_INDEX['Color']))

    def test_key_colors_change_with_tempo_in_both_panels(self):
        from traktor_key_calculator.config import HEADER_INDEX,OPEN_KEY_COLOR_MAPPING,COLOR_MAPPING_CATEGORY
        self.drop(self.window.candidate_tree,self.file)
        self.drop(self.window.playlist_tree,self.file)
        self.window.coloring_mode='key'
        self.window.populate_tree()
        for tree in (self.window.candidate_tree,self.window.playlist_tree):
            self.assertEqual(tree.topLevelItem(0).background(0).color().rgb(),OPEN_KEY_COLOR_MAPPING['1d'].rgb())
        self.window.bpm_slider.setValue(150)
        self.window.update_tree_after_slider()
        for tree in (self.window.candidate_tree,self.window.playlist_tree):
            item=tree.topLevelItem(0)
            self.assertEqual(item.text(HEADER_INDEX['New Key']),'G major')
            self.assertEqual(item.background(0).color().rgb(),OPEN_KEY_COLOR_MAPPING['2d'].rgb())
            self.assertEqual(item.text(HEADER_INDEX['Color']),'5')
        self.window.coloring_mode='song'
        self.window.populate_tree()
        for tree in (self.window.candidate_tree,self.window.playlist_tree):
            self.assertEqual(tree.topLevelItem(0).background(0).color().rgb(),COLOR_MAPPING_CATEGORY[5].rgb())

    def test_clearing_traktor_color_clears_old_background(self):
        from traktor_key_calculator.config import HEADER_INDEX
        from PyQt5.QtCore import Qt
        self.drop(self.window.candidate_tree,self.file)
        self.drop(self.window.playlist_tree,self.file)
        tree=ET.parse(self.collection)
        tree.find('./COLLECTION/ENTRY/INFO').set('COLOR','0')
        tree.write(self.collection,encoding='utf-8')
        self.drop(self.window.candidate_tree,self.file)
        for view in (self.window.candidate_tree,self.window.playlist_tree):
            item=view.topLevelItem(0)
            self.assertEqual(item.text(HEADER_INDEX['Color']),'0')
            self.assertEqual(item.background(0).style(),Qt.NoBrush)

    def test_real_mp3_drop_uses_actual_traktor_color(self):
        from traktor_key_calculator.config import HEADER_INDEX,COLOR_MAPPING_CATEGORY
        file=Path(r'E:\DJ\BREAKBEAT\8-Bit Krush - robosapiens remix.mp3')
        if not file.exists():
            self.skipTest('Local real MP3 unavailable')
        self.window.importer=TrackImporter(r'E:\DJ\TRAKTOR\collection.nml')
        expected=self.window.importer.collection.find(file)
        self.assertIsNotNone(expected)
        color=int(expected['color'])
        self.assertIn(color,COLOR_MAPPING_CATEGORY)
        self.drop(self.window.candidate_tree,file)
        self.drop(self.window.playlist_tree,file)
        for view in (self.window.candidate_tree,self.window.playlist_tree):
            item=view.topLevelItem(0)
            self.assertEqual(item.text(HEADER_INDEX['Color']),str(color))
            self.assertEqual(item.background(0).color().rgb(),COLOR_MAPPING_CATEGORY[color].rgb())
            self.assertTrue(item.text(HEADER_INDEX['Artist']))
            self.assertTrue(item.text(HEADER_INDEX['Title']))

    def test_color_delegate_renders_real_dot_pixels_with_selection(self):
        from PyQt5.QtWidgets import QStyleOptionViewItem,QStyle
        from PyQt5.QtGui import QImage,QPainter,QStandardItemModel,QStandardItem
        from PyQt5.QtCore import QRect
        from traktor_key_calculator.config import COLOR_MAPPING_CATEGORY
        from traktor_key_calculator.ui.delegates import ColorDotDelegate
        model=QStandardItemModel();model.appendRow(QStandardItem('5.0'))
        delegate=ColorDotDelegate()
        for selected in (False,True):
            image=QImage(40,30,QImage.Format_ARGB32);image.fill(0xffffffff)
            option=QStyleOptionViewItem();option.rect=QRect(0,0,40,30)
            option.state=QStyle.State_Enabled|QStyle.State_Active
            if selected:option.state|=QStyle.State_Selected
            painter=QPainter(image)
            delegate.paint(painter,option,model.index(0,0))
            painter.end()
            self.assertEqual(image.pixelColor(option.rect.center()).rgb(),COLOR_MAPPING_CATEGORY[5].rgb())


if __name__ == '__main__':
    unittest.main(verbosity=2)
