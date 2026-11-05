"""Saved collection and lists (library.sqlite) and duplicate removal."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from traktor_key_calculator.core.library_store import LibraryStore, LIBRARY_LIST, PLAYLIST_LIST
from traktor_key_calculator.core.track_import import drop_duplicate_paths
from traktor_key_calculator.core.traktor_collection import canonical_path
from traktor_key_calculator.ui.main_window import IN_PLAYLIST_ROLE


def track(path, title='Track', **fields):
    record = {'Artist': 'Test', 'Title': title, 'BPM': 100.0, 'File_Path': str(path),
              'Musical_Key_Base': 'C', 'BaseMinorOrMajor': 'major'}
    record.update(fields)
    return record


class LibraryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.store = LibraryStore(Path(self.temp.name) / 'library.sqlite')

    def tearDown(self):
        self.temp.cleanup()

    def test_list_round_trip_keeps_order_values_and_extra_fields(self):
        records = [track(r'E:\music\b.mp3', 'B', Rating=np.int64(4), Color=5, Key_Source='File tags', Imported=True),
                   track(r'E:\music\a.mp3', 'A', BPM=float('nan'), ID=7)]
        self.store.save_list(LIBRARY_LIST, records)
        loaded = self.store.load_list(LIBRARY_LIST)
        self.assertEqual([row['Title'] for row in loaded], ['B', 'A'])
        self.assertEqual(loaded[0]['Rating'], 4)
        self.assertEqual(loaded[0]['Color'], 5)
        self.assertEqual(loaded[0]['Key_Source'], 'File tags')
        self.assertIs(loaded[0]['Imported'], True)
        self.assertIsNone(loaded[1]['BPM'])
        self.assertEqual(loaded[1]['ID'], 7)

    def test_never_saved_list_is_none_and_empty_list_is_empty(self):
        self.assertIsNone(self.store.load_list(PLAYLIST_LIST))
        self.store.save_list(PLAYLIST_LIST, [])
        self.assertEqual(self.store.load_list(PLAYLIST_LIST), [])

    def test_same_file_in_other_case_updates_one_track(self):
        self.store.upsert_tracks([track(r'E:\Music\Song.mp3', 'Old')])
        self.store.upsert_tracks([track(r'e:/music/song.MP3', 'New')])
        self.assertEqual(self.store.track_count(), 1)
        self.store.save_list(LIBRARY_LIST, [track(r'E:\Music\Song.mp3', 'Newest')])
        self.assertEqual(self.store.load_list(LIBRARY_LIST)[0]['Title'], 'Newest')

    def test_collection_keeps_tracks_removed_from_a_list(self):
        self.store.save_list(LIBRARY_LIST, [track(r'E:\a.mp3'), track(r'E:\b.mp3')])
        self.store.save_list(LIBRARY_LIST, [track(r'E:\b.mp3')])
        self.assertEqual(len(self.store.load_list(LIBRARY_LIST)), 1)
        self.assertEqual(self.store.track_count(), 2)

    def test_imported_tracks_only_returns_imports(self):
        self.store.upsert_tracks([track(r'E:\csv.mp3'), track(r'E:\dropped.mp3', Imported=True)])
        self.assertEqual(list(self.store.imported_tracks()), [canonical_path(r'E:\dropped.mp3')])


class DuplicatePathTests(unittest.TestCase):
    def test_same_path_in_other_case_or_slashes_is_a_duplicate_and_first_row_is_kept(self):
        table = pd.DataFrame([track(r'E:\DJ\a.mp3', 'first'), track(r'E:\DJ\b.mp3', 'other'),
                              track('e:/dj/A.MP3', 'second copy'), track(r'E:\DJ\sub\a.mp3', 'other folder')])
        result, removed = drop_duplicate_paths(table)
        self.assertEqual(removed, 1)
        self.assertEqual(list(result['Title']), ['first', 'other', 'other folder'])

    def test_rows_without_path_are_not_duplicates_and_empty_table_is_fine(self):
        table = pd.DataFrame([track('', 'no path 1'), track('', 'no path 2')])
        self.assertEqual(drop_duplicate_paths(table)[1], 0)
        self.assertEqual(drop_duplicate_paths(pd.DataFrame())[1], 0)


class LibraryPersistenceGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        from traktor_key_calculator.config import SETTINGS_DEFAULT
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)
        self.settings_path = self.root / 'settings.json'
        settings = copy.deepcopy(SETTINGS_DEFAULT)
        settings.update({'Traktor collection': '', 'Advanced search': {'enabled': False, 'filters': []}})
        self.settings_path.write_text(json.dumps(settings))
        self.files = []
        for name in ('one', 'two', 'three'):
            path = self.root / f'{name}.mp3'
            path.write_bytes(b'')
            self.files.append(path)
        # The "default CSV": three tracks, with the first one listed twice under another spelling.
        self.default_library = pd.DataFrame([track(path, path.stem) for path in self.files] +
                                            [track(str(self.files[0]).upper(), 'one again')])
        self.patches = [
            patch('traktor_key_calculator.ui.main_window.SETTINGS_FILE', str(self.settings_path)),
            patch('traktor_key_calculator.ui.main_window.DataManager.load_default_data',
                  side_effect=lambda: self.default_library.copy()),
        ]
        for active in self.patches:
            active.start()
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.close()
        self.application.processEvents()
        for active in self.patches:
            active.stop()
        self.temp.cleanup()

    def window(self):
        from traktor_key_calculator.ui.main_window import TraktorKeyCalculator
        window = TraktorKeyCalculator()
        self.windows.append(window)
        return window

    def restart(self, window):
        window.close()
        self.windows.remove(window)
        self.application.processEvents()
        return self.window()

    @staticmethod
    def titles(tree):
        from traktor_key_calculator.config import HEADER_INDEX
        return [tree.topLevelItem(i).text(HEADER_INDEX['Title']) for i in range(tree.topLevelItemCount())]

    def test_playlist_columns_can_be_resized_and_keep_their_width(self):
        from PyQt5.QtWidgets import QHeaderView
        from traktor_key_calculator.config import HEADER_INDEX
        window = self.window()
        header = window.playlist_tree.header()
        self.assertTrue(all(header.sectionResizeMode(i) == QHeaderView.Interactive for i in range(header.count())))
        window.playlist_tree.setColumnWidth(HEADER_INDEX['Title'], 333)
        window = self.restart(window)
        self.assertEqual(window.playlist_tree.columnWidth(HEADER_INDEX['Title']), 333)

    def test_hidden_playlist_columns_leave_no_empty_gap(self):
        from traktor_key_calculator.config import HEADER_INDEX
        settings = json.loads(self.settings_path.read_text())
        settings['Visible column left'] = ['Artist', 'Title', 'Camelot Key New']
        self.settings_path.write_text(json.dumps(settings))
        tree = self.window().playlist_tree
        header = tree.header()
        title, camelot = HEADER_INDEX['Title'], HEADER_INDEX['Camelot Key New']
        self.assertTrue(tree.isColumnHidden(HEADER_INDEX['Original BPM']))
        # Before 4.16.2 each hidden column in between kept its old width as an empty gap.
        self.assertEqual(header.sectionPosition(camelot), header.sectionPosition(title) + header.sectionSize(title))

    def test_track_counts_of_the_list_and_the_playlist(self):
        window = self.window()
        tree = window.candidate_tree
        window._count_timer.timeout.emit()
        self.assertEqual(window.list_count_label.text().strip(), '4 tracks')
        self.assertEqual(window.playlist_count_label.text(), '0 tracks')
        window.search_bar.setText('two')
        window._count_timer.timeout.emit()
        self.assertEqual(window.list_count_label.text().strip(), '1 of 4 tracks')
        window.search_bar.clear()
        tree.topLevelItem(0).setSelected(True)
        tree.topLevelItem(1).setSelected(True)
        window._count_timer.timeout.emit()
        self.assertEqual(window.list_count_label.text().strip(), '4 tracks, 2 selected')
        window.add_selected_to_playlist()
        window.playlist_tree.topLevelItem(0).setSelected(True)
        window._count_timer.timeout.emit()
        self.assertEqual(window.playlist_count_label.text(), '2 tracks, 1 selected')

    def test_refresh_rebuilds_the_list_from_every_track_of_the_collection_without_any_csv(self):
        window = self.window()
        window.table = window.table[window.table['Title'] != 'two'].reset_index(drop=True)  # 'two' left the list
        window._save_library()
        window.populate_tree()
        self.assertNotIn('two', list(window.table['Title']))
        with patch.object(window.data_manager, 'load_default_data', side_effect=AssertionError('no CSV any more')):
            window.refresh_data()
        # one record per path: the starting tracks were never "imported", yet they all come back
        self.assertEqual(sorted(window.table['Title']), ['one', 'three', 'two'])
        self.assertEqual(sorted(self.titles(window.candidate_tree)), ['one', 'three', 'two'])
        self.assertEqual(len(self.restart(window).table), 3)

    def test_a_fresh_install_starts_with_an_empty_library(self):
        self.default_library = pd.DataFrame()  # what DataManager.load_default_data returns now
        self.assertEqual(len(self.window().table), 0)

    def test_library_and_playlist_are_restored_after_restart(self):
        from traktor_key_calculator.config import HEADER_INDEX
        window = self.window()
        self.assertEqual(len(window.table), 4)
        window.table = window.table[window.table['Title'] != 'two'].reset_index(drop=True)
        window._save_library()
        window.populate_tree()
        for title in ('three', 'one'):
            item = next(window.candidate_tree.topLevelItem(i) for i in range(window.candidate_tree.topLevelItemCount())
                        if window.candidate_tree.topLevelItem(i).text(HEADER_INDEX['Title']) == title)
            window.candidate_tree.setCurrentItem(item)
            window.add_selected_to_playlist()

        restored = self.restart(window)
        # A path has one record in the collection, so both 'one' rows now share the first row's data.
        self.assertEqual(sorted(restored.table['Title']), ['one', 'one', 'three'])
        self.assertEqual(self.titles(restored.playlist_tree), ['three', 'one'])
        # Playlist members are dimmed in the library panel, as before the restart.
        tree = restored.candidate_tree
        dimmed = [tree.topLevelItem(i).data(0, IN_PLAYLIST_ROLE) for i in range(tree.topLevelItemCount())]
        self.assertTrue(all(dimmed))

        restored.clear_playlist()
        self.assertEqual(self.titles(self.restart(restored).playlist_tree), [])

    def test_first_start_migrates_imported_tracks_json_and_keeps_it(self):
        legacy = self.root / 'imported_tracks.json'
        dropped = self.root / 'dropped.mp3'
        dropped.write_bytes(b'')
        legacy.write_text(json.dumps([track(dropped, 'dropped earlier', Imported=True)]), encoding='utf-8')
        window = self.window()
        self.assertIn('dropped earlier', list(window.table['Title']))
        self.assertIn(canonical_path(dropped), window.saved_imports)
        self.assertTrue(legacy.exists())

    def test_delete_duplicates_menu_removes_rows_persists_and_keeps_files(self):
        window = self.window()
        action = next(action for action in window.library_context_menu().actions()
                      if action.text() == 'Delete duplicates from the list')
        action.trigger()
        self.assertEqual(sorted(window.table['Title']), ['one', 'three', 'two'])
        self.assertEqual(window.candidate_tree.topLevelItemCount(), 3)
        self.assertIn('Removed 1 duplicate', window.status_label.text())
        self.assertTrue(all(path.exists() for path in self.files))

        restored = self.restart(window)
        self.assertEqual(sorted(restored.table['Title']), ['one', 'three', 'two'])
        self.assertEqual(restored.delete_duplicate_tracks(), 0)
        self.assertEqual(restored.status_label.text(), 'No duplicate paths in the list')
