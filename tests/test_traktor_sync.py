"""Changes made in Traktor (key, BPM, colour, rating) reach the library in the background."""
import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from traktor_key_calculator.core.traktor_collection import TraktorCollection, canonical_path
from traktor_key_calculator.core.traktor_sync import (apply_changes, collection_changes, seen_values, summary,
                                                      track_changes)
from test_imports import make_collection, tagged_file

ROW = {'File_Path': 'C:\\music\\a.mp3', 'Musical_Key_Base': 'A', 'BaseMinorOrMajor': 'minor', 'BPM': 128.0,
       'Color': 2, 'Rating': 4}
NOW = {'key': 'A minor', 'bpm': 128.0, 'color': 2, 'rating': 4}


class SyncRuleTests(unittest.TestCase):
    def test_first_sync_takes_traktors_colour_and_only_fills_empty_values(self):
        now = {'key': 'C major', 'bpm': 130.0, 'color': 5, 'rating': 2}
        self.assertEqual(track_changes(ROW, now), {'Color': 5, 'Color_Source': 'Traktor collection'})
        empty = {'File_Path': ROW['File_Path'], 'Color': None, 'Rating': None}
        changes = track_changes(empty, now)
        self.assertEqual((changes['Musical_Key_Base'], changes['BaseMinorOrMajor'], changes['BPM'], changes['Rating']),
                         ('C', 'major', 130.0, 2))

    def test_only_values_changed_in_traktor_since_the_last_sync_are_taken(self):
        self.assertEqual(track_changes(ROW, NOW, seen=NOW), {})
        tag_rating = dict(ROW, Rating=3)  # e.g. read from the file's tags; Traktor still says 4
        self.assertEqual(track_changes(tag_rating, NOW, seen=NOW), {})
        changed = dict(NOW, bpm=127.5, rating=5, color=0)  # tempo, rating and a cleared colour
        self.assertEqual(track_changes(tag_rating, changed, seen=NOW),
                         {'BPM': 127.5, 'BPM_Source': 'Traktor collection', 'Rating': 5,
                          'Color': 0, 'Color_Source': 'Traktor collection'})
        self.assertEqual(track_changes(ROW, dict(NOW, rating=None), seen=NOW), {'Rating': None})  # cleared
        self.assertEqual(track_changes(ROW, dict(NOW, key=None, bpm=None), seen=NOW), {})  # analysis gone: kept
        self.assertEqual(track_changes(ROW, dict(NOW, bpm=128.001), seen=NOW), {})  # rounding noise

    def test_table_changes_by_path_and_summary(self):
        table = pd.DataFrame([ROW, dict(ROW, File_Path='C:\\music\\b.mp3')])
        by_path = {canonical_path('C:/Music/A.mp3'): {'key': ('A', 'minor'), 'bpm': 126.0, 'color': '2', 'rating': 4}}
        changes = collection_changes(table, by_path, {canonical_path(ROW['File_Path']): NOW})
        self.assertEqual(list(changes), [0])
        result = apply_changes(table, changes)
        self.assertEqual(result['BPM'].tolist(), [126.0, 128.0])
        self.assertEqual(table['BPM'].tolist(), [128.0, 128.0])  # the input is not changed
        self.assertEqual(summary(changes), '1 track (BPM 1)')
        self.assertEqual(seen_values(by_path[canonical_path(ROW['File_Path'])]), dict(NOW, bpm=126.0))


class CollectionWatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)
        self.track = tagged_file(self.root / 'a.mp3')
        self.nml = self.root / 'collection.nml'
        make_collection(self.nml, [(self.track, 0, 120)])

    def tearDown(self):
        self.temp.cleanup()

    def wait_for(self, condition, seconds=10):
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.02)
        return condition()

    def test_reads_at_start_and_again_after_traktor_saves(self):
        from traktor_key_calculator.ui.traktor_watcher import CollectionWatcher
        with patch('traktor_key_calculator.ui.traktor_watcher.SETTLE_MS', 100):
            loaded = []
            watcher = CollectionWatcher(self.nml, first_check_ms=0)
            watcher.loaded.connect(loaded.append)
            self.assertTrue(self.wait_for(lambda: len(loaded) == 1))
            self.assertEqual(next(iter(loaded[0].by_path.values()))['bpm'], 120)
            make_collection(self.nml, [(self.track, 0, 124)])  # Traktor saves a new tempo
            watcher._changed()  # what the file watcher or the poll calls
            self.assertTrue(self.wait_for(lambda: len(loaded) == 2))
            self.assertEqual(next(iter(loaded[1].by_path.values()))['bpm'], 124)
            watcher._changed()  # unchanged file: not read again
            self.application.processEvents()
            time.sleep(0.3)
            self.application.processEvents()
            self.assertEqual(len(loaded), 2)
            watcher.stop()


class WindowSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        from traktor_key_calculator.config import SETTINGS_DEFAULT
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)
        self.track = tagged_file(self.root / 'a.mp3')
        self.nml = self.root / 'collection.nml'
        make_collection(self.nml, [(self.track, 0, 120)])
        settings = copy.deepcopy(SETTINGS_DEFAULT)
        settings.update({'Traktor collection': str(self.nml), 'Advanced search': {'enabled': False, 'filters': []}})
        (self.root / 'settings.json').write_text(json.dumps(settings))
        library = pd.DataFrame([{'Artist': 'A', 'Title': 'Track', 'BPM': 120, 'File_Path': str(self.track),
                                 'Musical_Key_Base': 'B', 'BaseMinorOrMajor': 'major', 'Color': 5, 'Rating': 5}])
        self.patches = [
            patch('traktor_key_calculator.ui.main_window.SETTINGS_FILE', str(self.root / 'settings.json')),
            patch('traktor_key_calculator.ui.main_window.DataManager.load_default_data', side_effect=lambda: library.copy()),
            patch('traktor_key_calculator.ui.traktor_watcher.FIRST_CHECK_MS', 600000),  # the test syncs itself
        ]
        for active in self.patches:
            active.start()
        from traktor_key_calculator.ui.main_window import TraktorKeyCalculator
        self.window = TraktorKeyCalculator()

    def tearDown(self):
        self.window.close()
        for active in self.patches:
            active.stop()
        self.temp.cleanup()

    def sync(self):
        collection = TraktorCollection(self.nml)
        collection._load()
        self.window._collection_changed(collection)

    def test_changes_made_in_traktor_update_list_playlist_and_database(self):
        from traktor_key_calculator.config import HEADER_INDEX
        from traktor_key_calculator.core.library_store import LIBRARY_LIST
        window = self.window
        window._add_to_playlist(window.table.iloc[0])
        self.sync()  # first sync: nothing differs (colour 5, rating 5, B major, 120 BPM)
        self.assertEqual(window.table.iloc[0]['BPM'], 120)
        make_collection(self.nml, [(self.track, 0, 126.5)])  # tempo changed in Traktor
        self.sync()
        self.assertEqual(window.table.iloc[0]['BPM'], 126.5)
        for tree in (window.candidate_tree, window.playlist_tree):
            self.assertEqual(tree.topLevelItem(0).text(HEADER_INDEX['Original BPM']), '126.5')
        self.assertEqual(window.library_store.load_list(LIBRARY_LIST)[0]['BPM'], 126.5)
        self.assertIn('Updated from Traktor: 1 track (BPM 1)', window.status_label.text())
        self.assertEqual(window.library_store.traktor_seen()[canonical_path(self.track)]['bpm'], 126.5)
        window.table.loc[0, 'BPM'] = 125  # e.g. a later import from tags; Traktor unchanged
        self.sync()
        self.assertEqual(window.table.iloc[0]['BPM'], 125)


if __name__ == '__main__':
    unittest.main()
