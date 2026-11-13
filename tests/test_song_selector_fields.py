"""Song Selector rating/color columns and Artist/Title/Genre tag editing."""
import copy
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import soundfile
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.wave import WAVE
from test_imports import tagged_file

from songselector.config import HEADER_INDEX, SS_COLOR_COLUMN, SS_RATING_COLUMN
from songselector.core.audio_metadata import extract_audio_metadata
from songselector.core.color_search import SS_COLOR_TOKEN, parse_color_search
from songselector.core.library_store import LIBRARY_LIST, LibraryStore
from songselector.core.search_filters import matches_condition
from songselector.core.tag_writer import write_tags
from songselector.ui.main_window import IN_PLAYLIST_ROLE


def track(path, title='Track', **fields):
    record = {'Artist': 'Test', 'Title': title, 'BPM': 120.0, 'File_Path': str(path),
              'Musical_Key_Base': 'C', 'BaseMinorOrMajor': 'major', 'Genre': 'Breaks'}
    record.update(fields)
    return record


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()


class TagWriterTests(TempDirTest):
    def test_mp3_changes_only_the_edited_tags_and_keeps_id3_version(self):
        path = tagged_file(self.root / 'song.mp3', key='Bm', bpm='128')
        tags = ID3(str(path))
        tags.save(str(path), v2_version=3)
        write_tags(path, Artist='New Artist', Genre='Tribal')
        metadata = extract_audio_metadata(path)
        self.assertEqual((metadata.artist, metadata.title, metadata.genre), ('New Artist', 'Test title', 'Tribal'))
        self.assertEqual((metadata.key, metadata.bpm, metadata.album, metadata.comment), ('Bm', '128', 'Test album', 'Test comment'))
        self.assertEqual(metadata.rating, 4)
        self.assertEqual(ID3(str(path)).version[:2], (2, 3))

    def test_empty_value_removes_tag_and_untagged_mp3_gets_tags(self):
        path = tagged_file(self.root / 'song.mp3')
        write_tags(path, Genre='')
        self.assertIsNone(extract_audio_metadata(path).genre)
        bare = self.root / 'bare.mp3'
        bare.write_bytes(b'')
        write_tags(bare, Title='Fresh')
        self.assertEqual(extract_audio_metadata(bare).title, 'Fresh')

    def test_wav_and_flac(self):
        for name in ('tone.wav', 'tone.flac'):
            path = self.root / name
            soundfile.write(str(path), np.zeros((4410, 2)), 44100)
            write_tags(path, Artist='A', Title='T', Genre='G')
            metadata = extract_audio_metadata(path)
            self.assertEqual((metadata.artist, metadata.title, metadata.genre), ('A', 'T', 'G'), name)
        self.assertEqual(FLAC(str(self.root / 'tone.flac'))['genre'], ['G'])
        self.assertEqual(str(WAVE(str(self.root / 'tone.wav')).tags['TPE1']), 'A')

    def test_rejects_unknown_fields_missing_and_unsupported_files(self):
        path = tagged_file(self.root / 'song.mp3')
        with self.assertRaises(ValueError):
            write_tags(path, Rating='5')
        with self.assertRaises(ValueError):
            write_tags(self.root / 'missing.mp3', Artist='x')
        other = self.root / 'song.ogg'
        other.write_bytes(b'')
        with self.assertRaises(ValueError):
            write_tags(other, Artist='x')


class UserFieldStoreTests(TempDirTest):
    def test_user_fields_are_kept_when_metadata_is_upserted(self):
        store = LibraryStore(self.root / 'library.sqlite')
        song = track(r'E:\a.mp3')
        store.set_user_fields([song], SS_Rating=5, SS_Color=4)
        store.save_list(LIBRARY_LIST, [track(r'E:\a.mp3', 'Renamed')])  # e.g. Refresh from the CSV
        row = store.load_list(LIBRARY_LIST)[0]
        self.assertEqual((row['Title'], row['SS_Rating'], row['SS_Color']), ('Renamed', 5, 4))
        store.set_user_fields([song], SS_Color=None)
        self.assertEqual(store.user_fields(), {r'e:\a.mp3': {'SS_Rating': 5, 'SS_Color': None}})
        with self.assertRaises(ValueError):
            store.set_user_fields([song], Rating=3)

    def test_schema_1_database_is_upgraded_in_place(self):
        path = self.root / 'library.sqlite'
        connection = sqlite3.connect(path)
        connection.executescript("""
            CREATE TABLE tracks (path_key TEXT PRIMARY KEY, file_path TEXT NOT NULL, artist TEXT, title TEXT,
                album TEXT, genre TEXT, comment TEXT, bpm REAL, key_base TEXT, key_scale TEXT, rating REAL,
                color INTEGER, imported INTEGER, extra TEXT NOT NULL DEFAULT '{}', added_at TEXT NOT NULL,
                updated_at TEXT NOT NULL);
            INSERT INTO tracks VALUES ('e:\\old.mp3', 'E:\\old.mp3', 'Old', 'Song', NULL, NULL, NULL, 125, 'C',
                'major', NULL, 5, 1, '{}', 'x', 'x');
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta VALUES ('schema_version', '1');""")
        connection.commit()
        connection.close()
        store = LibraryStore(path)
        self.assertEqual(store.imported_tracks()[r'e:\old.mp3']['Artist'], 'Old')
        store.set_user_fields([track(r'E:\old.mp3')], SS_Rating=3)
        self.assertEqual(store.user_fields()[r'e:\old.mp3']['SS_Rating'], 3)
        with closing(sqlite3.connect(path)) as check:  # sqlite3's own context manager does not close
            self.assertEqual(check.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '3')
        store.save_playlist('Set', [track(r'E:\old.mp3')])  # schema 3 tables exist
        self.assertEqual(store.playlist_keys('Set'), [r'e:\old.mp3'])


class FilterTests(unittest.TestCase):
    def test_complex_search_numbers_and_color_names_on_song_selector_columns(self):
        self.assertTrue(matches_condition('4', 'at least (>=)', '4', SS_RATING_COLUMN))
        self.assertFalse(matches_condition('', 'at least (>=)', '1', SS_RATING_COLUMN))
        self.assertTrue(matches_condition('5', 'is', 'blue', SS_COLOR_COLUMN))
        self.assertTrue(matches_condition('', 'is', 'none', SS_COLOR_COLUMN))
        self.assertFalse(matches_condition('5', 'is not', 'blue', SS_COLOR_COLUMN))

    def test_search_bar_sscolor_is_separate_from_traktor_color(self):
        traktor = parse_color_search('tribal color:red sscolor:blue,green -sscolor:none')
        self.assertEqual(traktor.included, {1})
        mine = parse_color_search(traktor.text, SS_COLOR_TOKEN)
        self.assertEqual((mine.text, mine.included, mine.excluded), ('tribal', {5, 4}, {0}))
        self.assertTrue(mine.matches('5'))
        self.assertFalse(mine.matches(''))
        self.assertTrue(parse_color_search('sscolor:purpl', SS_COLOR_TOKEN).error)


class GuiTestBase(TempDirTest):
    """Window with a patched settings file and a small default library (no tests here)."""

    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        from songselector.config import SETTINGS_DEFAULT
        super().setUp()
        self.settings_path = self.root / 'settings.json'
        settings = copy.deepcopy(SETTINGS_DEFAULT)
        settings.update({'Traktor collection': '', 'Advanced search': {'enabled': False, 'filters': []}})
        self.settings_path.write_text(json.dumps(settings))
        self.song = tagged_file(self.root / 'song.mp3')
        self.other = tagged_file(self.root / 'other.mp3')
        self.library = pd.DataFrame([track(self.song, 'Song', Artist='CSV artist'), track(self.other, 'Other')])
        self.patches = [patch('songselector.ui.main_window.SETTINGS_FILE', str(self.settings_path)),
                        patch('songselector.ui.main_window.DataManager.load_default_data',
                              side_effect=lambda: self.library.copy())]
        for active in self.patches:
            active.start()
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.close()
        self.application.processEvents()
        for active in self.patches:
            active.stop()
        super().tearDown()

    def window(self):
        from songselector.ui.main_window import MainWindow
        window = MainWindow()
        self.windows.append(window)
        return window

    def restart(self, window):
        window.close()
        self.windows.remove(window)
        self.application.processEvents()
        return self.window()

    @staticmethod
    def item(tree, title):
        return next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                    if tree.topLevelItem(i).text(HEADER_INDEX['Title']) == title)

    @staticmethod
    def menu_action(menu, *path):
        for name in path[:-1]:
            menu = next(action.menu() for action in menu.actions() if action.text() == name)
        return next(action for action in menu.actions() if action.text().endswith(path[-1]))

class SongSelectorGuiTests(GuiTestBase):
    def test_columns_visible_and_searchable_after_settings_upgrade(self):
        window = self.window()
        for column in (SS_RATING_COLUMN, SS_COLOR_COLUMN):
            self.assertFalse(window.candidate_tree.isColumnHidden(HEADER_INDEX[column]))
            self.assertTrue(window.search_column_actions[column].isChecked())

    def test_rating_and_color_from_context_menu_persist_and_filter(self):
        window = self.window()
        window.candidate_tree.setCurrentItem(self.item(window.candidate_tree, 'Song'))
        menu = window.library_context_menu()
        self.menu_action(menu, 'Rating - Song Selector', '(4)').trigger()
        self.menu_action(menu, 'Color - Song Selector', 'Blue').trigger()
        song = self.item(window.candidate_tree, 'Song')
        self.assertEqual((song.text(HEADER_INDEX[SS_RATING_COLUMN]), song.text(HEADER_INDEX[SS_COLOR_COLUMN])), ('4', '5'))

        window.search_bar.setText('sscolor:blue')
        visible = [window.candidate_tree.topLevelItem(i).text(HEADER_INDEX['Title'])
                   for i in range(window.candidate_tree.topLevelItemCount())
                   if not window.candidate_tree.topLevelItem(i).isHidden()]
        self.assertEqual(visible, ['Song'])
        window.search_bar.clear()

        restored = self.restart(window)
        self.assertEqual(self.item(restored.candidate_tree, 'Song').text(HEADER_INDEX[SS_RATING_COLUMN]), '4')
        restored.refresh_data()  # rebuilding from the CSV keeps the app's own values
        self.assertEqual(self.item(restored.candidate_tree, 'Song').text(HEADER_INDEX[SS_COLOR_COLUMN]), '5')
        restored.current_advanced_search = {'enabled': True, 'filters': [
            {'column': SS_RATING_COLUMN, 'condition': 'at least (>=)', 'value': '4'}]}
        restored.advanced_filters = restored.current_advanced_search['filters']
        restored.filter_items()
        self.assertFalse(self.item(restored.candidate_tree, 'Song').isHidden())
        self.assertTrue(self.item(restored.candidate_tree, 'Other').isHidden())

        restored.set_song_selector_fields([str(self.song)], SS_Rating=None)
        self.assertEqual(self.item(restored.candidate_tree, 'Song').text(HEADER_INDEX[SS_RATING_COLUMN]), '')

    def test_playlist_rows_have_the_same_menu(self):
        window = self.window()
        window.candidate_tree.setCurrentItem(self.item(window.candidate_tree, 'Other'))
        window.add_selected_to_playlist()
        window.playlist_tree.setCurrentItem(window.playlist_tree.topLevelItem(0))
        menu = window.track_context_menu(window.playlist_tree)
        self.assertNotIn('Delete duplicates from the list', [action.text() for action in menu.actions()])
        self.menu_action(menu, 'Rating - Song Selector', '(2)').trigger()
        self.assertEqual(window.playlist_tree.topLevelItem(0).text(HEADER_INDEX[SS_RATING_COLUMN]), '2')

    def test_edit_tags_writes_file_updates_library_and_survives_refresh(self):
        window = self.window()
        self.assertTrue(window.edit_track_tags(str(self.song), Artist='Edited', Genre='Tribal'))
        metadata = extract_audio_metadata(self.song)
        self.assertEqual((metadata.artist, metadata.genre, metadata.title), ('Edited', 'Tribal', 'Test title'))
        self.assertEqual(self.item(window.candidate_tree, 'Test title').text(HEADER_INDEX['Artist']), 'Edited')
        restored = self.restart(window)
        restored.refresh_data()
        song = self.item(restored.candidate_tree, 'Test title')
        self.assertEqual((song.text(HEADER_INDEX['Artist']), song.text(HEADER_INDEX['Genre'])), ('Edited', 'Tribal'))

    def test_failed_tag_write_changes_nothing(self):
        window = self.window()
        missing = self.root / 'gone.mp3'
        window.table = pd.concat([window.table, pd.DataFrame([track(missing, 'Gone')])], ignore_index=True)
        with patch('songselector.ui.main_window.QMessageBox.warning') as warning:
            self.assertFalse(window.edit_track_tags(str(missing), Artist='x'))
        warning.assert_called_once()
        self.assertEqual(window.table.loc[window.table['Title'] == 'Gone', 'Artist'].iloc[0], 'Test')

    def test_tag_edit_keeps_existing_embedding_current(self):
        from songselector.core.embeddings import file_fingerprint
        from songselector.core.traktor_collection import canonical_path
        window = self.window()
        key = canonical_path(self.song)
        window.embedding_store.save(key, file_fingerprint(self.song), np.ones((1, 2048)))
        window.edit_track_tags(str(self.song), Title='Renamed')
        self.assertEqual(window.embedding_store.fingerprints()[key], file_fingerprint(self.song))


class CommentTagTests(TempDirTest):
    def test_mp3_comment_replaces_main_comment_and_keeps_other_comm_frames(self):
        from mutagen.id3 import COMM
        path = tagged_file(self.root / 'song.mp3')  # main comment in language 'hun'
        tags = ID3(str(path))
        tags.add(COMM(encoding=3, lang='eng', desc='iTunNORM', text=['00000A']))
        tags.save(str(path))
        write_tags(path, Comment='Peak time tool')
        self.assertEqual(extract_audio_metadata(path).comment, 'Peak time tool')
        frames = {(frame.desc, frame.lang): str(frame) for frame in ID3(str(path)).getall('COMM')}
        self.assertEqual(frames, {('', 'eng'): 'Peak time tool', ('iTunNORM', 'eng'): '00000A'})
        write_tags(path, Comment='')
        self.assertIsNone(extract_audio_metadata(path).comment)

    def test_flac_comment(self):
        path = self.root / 'tone.flac'
        soundfile.write(str(path), np.zeros((4410, 2)), 44100)
        write_tags(path, Comment='Warm-up')
        self.assertEqual(extract_audio_metadata(path).comment, 'Warm-up')


class MultiSelectionGuiTests(GuiTestBase):
    """Shift/Ctrl multi-selection, Delete key and bulk actions."""

    def setUp(self):
        super().setUp()
        self.third = tagged_file(self.root / 'third.mp3')
        self.library = pd.DataFrame([track(self.song, 'Song'), track(self.other, 'Other'), track(self.third, 'Third')])

    def select(self, tree, *titles):
        tree.clearSelection()
        for title in titles:
            self.item(tree, title).setSelected(True)

    @staticmethod
    def titles(tree):
        return [tree.topLevelItem(i).text(HEADER_INDEX['Title']) for i in range(tree.topLevelItemCount())
                if not tree.topLevelItem(i).isHidden()]

    def test_trees_allow_shift_and_ctrl_selection(self):
        from PyQt5.QtWidgets import QAbstractItemView
        window = self.window()
        for tree in (window.candidate_tree, window.playlist_tree):
            self.assertEqual(tree.selectionMode(), QAbstractItemView.ExtendedSelection)

    def test_delete_key_removes_selected_library_rows_after_confirmation(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        from PyQt5.QtWidgets import QMessageBox
        window = self.window()
        self.select(window.candidate_tree, 'Song', 'Third')
        with patch('songselector.ui.main_window.QMessageBox.question', return_value=QMessageBox.No):
            QTest.keyClick(window.candidate_tree, Qt.Key_Delete)
        self.assertEqual(sorted(self.titles(window.candidate_tree)), ['Other', 'Song', 'Third'])
        with patch('songselector.ui.main_window.QMessageBox.question', return_value=QMessageBox.Yes):
            QTest.keyClick(window.candidate_tree, Qt.Key_Delete)
        self.assertEqual(self.titles(window.candidate_tree), ['Other'])
        self.assertTrue(self.song.exists() and self.third.exists())
        restored = self.restart(window)
        self.assertEqual(self.titles(restored.candidate_tree), ['Other'])
        self.assertEqual(restored.library_store.track_count(), 3)  # still in the collection

    def test_delete_key_in_playlist_returns_tracks_to_the_library(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        window = self.window()
        self.select(window.candidate_tree, 'Song', 'Other', 'Third')
        window.add_selected_to_playlist()
        self.assertEqual(window.playlist_tree.topLevelItemCount(), 3)
        self.select(window.playlist_tree, 'Song', 'Third')
        QTest.keyClick(window.playlist_tree, Qt.Key_Delete)
        self.assertEqual(self.titles(window.playlist_tree), ['Other'])
        dimmed = {title for title in ('Song', 'Other', 'Third')
                  if self.item(window.candidate_tree, title).data(0, IN_PLAYLIST_ROLE)}
        self.assertEqual(dimmed, {'Other'})  # removed from the playlist: no longer dimmed
        self.assertEqual(self.titles(self.restart(window).playlist_tree), ['Other'])

    def test_rating_and_color_apply_to_every_selected_row(self):
        window = self.window()
        self.select(window.candidate_tree, 'Song', 'Third')
        menu = window.library_context_menu()
        self.menu_action(menu, 'Rating - Song Selector (2 tracks)', '(5)').trigger()
        self.menu_action(menu, 'Color - Song Selector (2 tracks)', 'Green').trigger()
        values = {title: (self.item(window.candidate_tree, title).text(HEADER_INDEX[SS_RATING_COLUMN]),
                          self.item(window.candidate_tree, title).text(HEADER_INDEX[SS_COLOR_COLUMN]))
                  for title in ('Song', 'Other', 'Third')}
        self.assertEqual(values, {'Song': ('5', '4'), 'Other': ('', ''), 'Third': ('5', '4')})

    def test_remove_action_in_menu_and_edit_comment(self):
        from PyQt5.QtWidgets import QMessageBox
        window = self.window()
        self.select(window.candidate_tree, 'Other')
        window.candidate_tree.setCurrentItem(self.item(window.candidate_tree, 'Other'))
        menu = window.library_context_menu()
        self.assertTrue(any(action.text().startswith('Edit track info') for action in menu.actions()))
        self.assertTrue(window.edit_track_tags(str(self.other), Comment='Big room'))
        self.assertEqual(self.item(window.candidate_tree, 'Test title').text(HEADER_INDEX['Comment']), 'Big room')
        self.assertEqual(extract_audio_metadata(self.other).comment, 'Big room')
        with patch('songselector.ui.main_window.QMessageBox.question', return_value=QMessageBox.Yes):
            self.menu_action(window.library_context_menu(), 'Remove from library\tDel').trigger()
        self.assertEqual(sorted(self.titles(window.candidate_tree)), ['Song', 'Third'])


class DefaultModelTests(GuiTestBase):
    def test_default_model_is_used_when_none_is_chosen(self):
        model = self.root / 'default-cnn14.onnx'
        model.write_bytes(b'x')
        with patch('songselector.ui.main_window.DEFAULT_EMBEDDING_MODEL', str(model)), \
                patch('songselector.ui.main_window.EmbeddingAnalyzer'):  # no real process
            window = self.window()
            self.assertEqual(window.embedding_model_path(), model)
            window.settings['Embedding model'] = str(self.root / 'missing.onnx')
            self.assertEqual(window.embedding_model_path(), model)
            chosen = self.root / 'chosen.onnx'
            chosen.write_bytes(b'x')
            window.settings['Embedding model'] = str(chosen)
            self.assertEqual(window.embedding_model_path(), chosen)


class MissingFilesGuiTests(GuiTestBase):
    def setUp(self):
        super().setUp()
        self.gone = self.root / 'gone.mp3'  # never created: a moved or deleted file
        self.library = pd.DataFrame([track(self.song, 'Song'), track(self.gone, 'Gone'), track(self.other, 'Other')])

    @staticmethod
    def titles(tree):
        return sorted(tree.topLevelItem(i).text(HEADER_INDEX['Title']) for i in range(tree.topLevelItemCount()))

    def test_library_removes_only_missing_files_after_confirmation_even_if_filtered_out(self):
        from PyQt5.QtWidgets import QMessageBox
        window = self.window()
        window.search_bar.setText('Song')  # 'Gone' is hidden by the search but still removed
        with patch('songselector.ui.main_window.QMessageBox.question', return_value=QMessageBox.Yes) as ask:
            self.menu_action(window.library_context_menu(), 'Remove missing files from the list').trigger()
        self.assertIn('1 missing file(s)', ask.call_args[0][2])
        self.assertEqual(self.titles(window.candidate_tree), ['Other', 'Song'])
        self.assertEqual(self.titles(self.restart(window).candidate_tree), ['Other', 'Song'])

    def test_playlist_removes_missing_files_and_reports_when_there_are_none(self):
        window = self.window()
        for title in ('Song', 'Gone'):
            window.candidate_tree.setCurrentItem(self.item(window.candidate_tree, title))
            window.add_selected_to_playlist()
        self.assertEqual(window.remove_missing_tracks(window.playlist_tree), 1)
        self.assertEqual(self.titles(window.playlist_tree), ['Song'])
        self.assertEqual(window.remove_missing_tracks(window.playlist_tree), 0)
        self.assertEqual(window.status_label.text(), 'No missing files in the list')


class ThemeTests(GuiTestBase):
    def test_dark_theme_by_default_and_switchable_at_runtime(self):
        from PyQt5.QtGui import QPalette
        from PyQt5.QtWidgets import QApplication

        from songselector.ui.theme import status_style
        window = self.window()
        palette = QApplication.instance().palette()
        self.assertLess(palette.color(QPalette.Window).lightness(), 80)  # dark grey
        self.assertTrue(window.dark_theme_action.isChecked())
        self.assertIn('#ff7b72', status_style('error'))
        window.dark_theme_action.setChecked(False)
        self.assertGreater(QApplication.instance().palette().color(QPalette.Window).lightness(), 180)
        self.assertEqual(window.settings['Theme'], 'light')
        self.assertIn('#cf222e', status_style('error'))
        self.assertEqual(status_style('info'), 'font-weight: normal;')
        window.dark_theme_action.setChecked(True)  # leave the shared QApplication dark


class PlaylistInLibraryTests(GuiTestBase):
    """Playlist tracks stay findable in the library (dimmed); hiding them is a View option."""

    def test_search_finds_playlist_tracks_dimmed_and_the_toggle_hides_them(self):
        window = self.window()
        window.candidate_tree.setCurrentItem(self.item(window.candidate_tree, 'Song'))
        window.add_selected_to_playlist()
        window.search_bar.setText('Song')
        song = self.item(window.candidate_tree, 'Song')
        self.assertFalse(song.isHidden())
        self.assertTrue(song.font(0).italic())
        self.assertIn('1 in the playlist (dimmed)', window.status_label.text())
        window.hide_playlist_action.setChecked(True)
        self.assertTrue(song.isHidden())
        self.assertIn('1 more in the playlist (hidden, see View menu)', window.status_label.text())
        self.assertTrue(window.settings['Hide playlist tracks'])
        window.hide_playlist_action.setChecked(False)
        self.assertFalse(song.isHidden())

    def test_active_advanced_search_is_visible_on_the_button_and_in_the_status(self):
        window = self.window()
        self.assertEqual(window.btn_advanced_search.text(), 'Advanced Search')
        window.current_advanced_search = {'enabled': True, 'filters': [
            {'column': 'Original BPM', 'condition': 'greater than', 'value': '100'},
            {'column': 'Original BPM', 'condition': 'less than', 'value': '140'}]}
        window.advanced_filters = window.current_advanced_search['filters']
        window.filter_items()
        self.assertEqual(window.btn_advanced_search.text(), 'Advanced Search (2 active)')
        self.assertIn('Original BPM less than 140', window.btn_advanced_search.toolTip())
        self.assertIn('Advanced Search is on', window.status_label.text())
        window.current_advanced_search['enabled'] = False
        window.filter_items()
        self.assertEqual(window.btn_advanced_search.text(), 'Advanced Search')
