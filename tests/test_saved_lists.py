"""Browser tab: collection entries, saved playlists and smartlists; the Playlist tab's order (#)."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from PyQt5.QtCore import QUrl

from songselector.config import FIELD_LABELS, HEADER_INDEX, POSITION_COLUMN
from songselector.core.library_store import PLAYLIST, SMARTLIST, LibraryStore
from songselector.core.traktor_collection import TraktorCollection, canonical_path

POSITION = HEADER_INDEX[POSITION_COLUMN]


def track(path, title, artist='Test', genre='House', bpm=120.0):
    return {'Artist': artist, 'Title': title, 'Genre': genre, 'BPM': bpm, 'File_Path': str(path),
            'Musical_Key_Base': 'C', 'BaseMinorOrMajor': 'major'}


class SavedListStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.store = LibraryStore(Path(self.temp.name) / 'library.sqlite')

    def tearDown(self):
        self.temp.cleanup()

    def test_playlists_keep_order_once_per_track_and_names_ignore_case(self):
        a, b, c = (track(rf'E:\{name}.mp3', name) for name in 'abc')
        self.store.save_playlist('Warm-up', [b, a, b])
        self.assertEqual([r['Title'] for r in self.store.load_playlist('warm-UP')], ['b', 'a'])
        self.assertEqual(self.store.add_to_playlist('Warm-up', [a, c]), 1)
        self.assertEqual(self.store.playlist_keys('Warm-up'), [canonical_path(p) for p in (r'E:\b.mp3', r'E:\a.mp3', r'E:\c.mp3')])
        self.store.save_smartlist('deep', [{'column': 'Genre', 'condition': 'contains', 'value': 'deep'}])
        self.assertEqual(self.store.saved_lists(), [('deep', SMARTLIST), ('Warm-up', PLAYLIST)])
        self.assertEqual(self.store.saved_list('DEEP')['rules'][0]['value'], 'deep')
        self.assertIsNone(self.store.saved_list('Warm-up')['rules'])

    def test_rename_and_delete(self):
        self.store.save_playlist('Set', [track(r'E:\a.mp3', 'a')])
        self.store.rename_saved_list('Set', 'Friday set')
        self.assertIsNone(self.store.saved_list('Set'))
        self.assertEqual(len(self.store.load_playlist('Friday set')), 1)
        self.store.delete_saved_list('Friday set')
        self.assertEqual(self.store.saved_lists(), [])
        self.assertEqual(self.store.playlist_keys('Friday set'), [])
        self.assertEqual(self.store.track_count(), 1)  # the track stays in the collection

    def test_tracks_by_key(self):
        self.store.upsert_tracks([track(r'E:\a.mp3', 'a'), track(r'E:\b.mp3', 'b')])
        found = self.store.tracks([canonical_path(r'E:\b.mp3'), 'e:\\missing.mp3'])
        self.assertEqual([record['Title'] for record in found.values()], ['b'])


class TraktorPlaylistParsingTests(unittest.TestCase):
    def test_playlists_folders_and_smartlists_are_read_in_traktor_order(self):
        nml = """<?xml version="1.0" encoding="UTF-8"?>
<NML VERSION="19"><COLLECTION ENTRIES="1">
<ENTRY TITLE="A" ARTIST="X"><LOCATION DIR="/:DJ/:Break/:" FILE="a.mp3" VOLUME="E:"></LOCATION><INFO GENRE="break"></INFO></ENTRY>
</COLLECTION>
<PLAYLISTS><NODE TYPE="FOLDER" NAME="$ROOT"><SUBNODES COUNT="3">
<NODE TYPE="FOLDER" NAME="BPM120"><SUBNODES COUNT="1">
<NODE TYPE="PLAYLIST" NAME="Inner"><PLAYLIST ENTRIES="1" TYPE="LIST" UUID="1">
<ENTRY><PRIMARYKEY TYPE="TRACK" KEY="E:/:DJ/:Break/:a.mp3"></PRIMARYKEY></ENTRY></PLAYLIST></NODE>
</SUBNODES></NODE>
<NODE TYPE="SMARTLIST" NAME="&lt;165"><SMARTLIST UUID="2"><SEARCH_EXPRESSION VERSION="1" QUERY="$BPM &gt; 165.000000"></SEARCH_EXPRESSION></SMARTLIST></NODE>
<NODE TYPE="PLAYLIST" NAME="Set"><PLAYLIST ENTRIES="2" TYPE="LIST" UUID="3">
<ENTRY><PRIMARYKEY TYPE="TRACK" KEY="E:/:DJ/:Other/:b.mp3"></PRIMARYKEY></ENTRY>
<ENTRY><PRIMARYKEY TYPE="TRACK" KEY="E:/:DJ/:Break/:a.mp3"></PRIMARYKEY></ENTRY></PLAYLIST></NODE>
</SUBNODES></NODE></PLAYLISTS></NML>"""
        with tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR']) as folder:
            path = Path(folder) / 'collection.nml'
            path.write_text(nml, encoding='utf-8')
            collection = TraktorCollection(path)
            collection._load()
        self.assertEqual(collection.error, '')
        self.assertEqual(list(collection.by_path), [canonical_path(r'E:\DJ\Break\a.mp3')])  # tracks still read
        self.assertEqual([(entry['type'], entry['name']) for entry in collection.playlists],
                         [('FOLDER', 'BPM120'), ('SMARTLIST', '<165'), ('PLAYLIST', 'Set')])
        self.assertEqual(collection.playlists[0]['children'][0]['tracks'], [r'E:\DJ\Break\a.mp3'])
        self.assertEqual(collection.playlists[1]['query'], '$BPM > 165.000000')
        self.assertEqual(collection.playlists[2]['tracks'], [r'E:\DJ\Other\b.mp3', r'E:\DJ\Break\a.mp3'])


class BrowserGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        from songselector.config import SETTINGS_DEFAULT
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)
        self.settings_path = self.root / 'settings.json'
        settings = copy.deepcopy(SETTINGS_DEFAULT)
        settings.update({'Traktor collection': '', 'Advanced search': {'enabled': False, 'filters': []}})
        self.settings_path.write_text(json.dumps(settings))
        self.paths = {}
        rows = []
        for title, artist, genre, bpm in (('one', 'Cat Power', 'Breakbeat', 128), ('two', 'Forme', 'House', 122),
                                          ('three', 'Cat Power', 'House', 125), ('four', 'Yeadon', 'Deep House', 118)):
            self.paths[title] = self.root / f'{title}.mp3'
            self.paths[title].write_bytes(b'')
            rows.append(track(self.paths[title], title, artist, genre, bpm))
        self.default_library = pd.DataFrame(rows)
        self.patches = [
            patch('songselector.ui.main_window.SETTINGS_FILE', str(self.settings_path)),
            patch('songselector.ui.main_window.DataManager.load_default_data',
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
    def shown(window):
        """Titles the List shows, top to bottom."""
        tree = window.candidate_tree
        return [tree.topLevelItem(i).text(HEADER_INDEX['Title']) for i in range(tree.topLevelItemCount())
                if not tree.topLevelItem(i).isHidden()]

    @staticmethod
    def playlist(window, column='Title'):
        tree = window.playlist_tree
        return [tree.topLevelItem(i).text(HEADER_INDEX[column]) for i in range(tree.topLevelItemCount())]

    def add(self, window, *titles):
        window.add_paths_to_playlist([str(self.paths[title]) for title in titles])

    @staticmethod
    def drop(widget, mime, pos=None):
        from PyQt5.QtCore import QCoreApplication, QPoint, QPointF, Qt
        from PyQt5.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
        pos = pos or QPoint(8, 8)
        for event in (QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier),
                      QDragMoveEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)):
            QCoreApplication.sendEvent(widget.viewport(), event)
        event = QDropEvent(QPointF(pos), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QCoreApplication.sendEvent(widget.viewport(), event)
        return event.isAccepted()

    @staticmethod
    def node_mime(node):
        from PyQt5.QtCore import QMimeData

        from songselector.ui.tree_widgets import NODE_MIME
        mime = QMimeData()
        mime.setData(NODE_MIME, json.dumps(node).encode('utf-8'))
        return mime

    def test_left_pane_has_playlist_and_browser_tabs_and_position_column(self):
        window = self.window()
        self.assertEqual([window.left_tabs.tabText(i) for i in range(window.left_tabs.count())], ['Playlist', 'Browser'])
        for tree in (window.playlist_tree, window.candidate_tree):
            self.assertEqual(tree.header().logicalIndex(0), POSITION)  # shown first
            self.assertFalse(tree.isColumnHidden(POSITION))
        self.add(window, 'three', 'one')
        self.assertEqual(self.playlist(window, POSITION_COLUMN), ['1', '2'])
        window.resize(1200, 700)
        window.show()
        self.application.processEvents()
        for tree in (window.playlist_tree, window.candidate_tree):
            # Artist's cell starts where its column starts: no unshaded branch indent before it
            artist = tree.indexFromItem(tree.topLevelItem(0), HEADER_INDEX['Artist'])
            self.assertEqual(tree.visualRect(artist).left(), tree.header().sectionViewportPosition(HEADER_INDEX['Artist']))
        # Not a track field: not searchable, not in Complex Search
        self.assertNotIn(POSITION_COLUMN, window.search_column_actions)
        self.assertNotIn('Group', window.search_column_actions)
        self.assertNotIn(POSITION_COLUMN, FIELD_LABELS)
        window.search_columns = [POSITION_COLUMN]  # even if chosen, # is not searched
        window.search_bar.setText('1')
        self.assertEqual(self.shown(window), [])

    def test_collection_entries_show_their_tracks_in_the_list(self):
        window = self.window()
        browser = window.list_browser
        self.assertEqual(browser.groups['artist'].text(0), 'Artists (3)')
        self.assertEqual(browser.groups['genre'].text(0), 'Genres (3)')
        browser.groups['artist'].setExpanded(True)
        self.assertEqual([browser.groups['artist'].child(i).text(0) for i in range(3)], ['Cat Power', 'Forme', 'Yeadon'])
        browser.setCurrentItem(browser.groups['artist'].child(0))  # a click
        self.assertEqual(sorted(self.shown(window)), ['one', 'three'])
        self.assertTrue(window.source_bar.isVisibleTo(window))
        self.assertIn('Artist: Cat Power', window.source_label.text())
        window.search_bar.setText('three')  # the search applies on top
        self.assertEqual(self.shown(window), ['three'])
        window.search_bar.clear()
        window.source_clear_button.click()
        self.assertEqual(len(self.shown(window)), 4)
        self.assertFalse(window.source_bar.isVisibleTo(window))
        self.assertEqual(browser.current_node()['kind'], 'all')

    def test_saved_playlist_keeps_its_order_and_is_shown_in_list_order_by_position(self):
        window = self.window()
        self.add(window, 'two', 'four', 'one')
        with patch('songselector.ui.saved_lists.QInputDialog.getText', return_value=('Friday set', True)):
            window.save_playlist_as()
        window.list_browser.setCurrentItem(window.list_browser.playlists_root.child(0))
        self.assertEqual(self.shown(window), ['two', 'four', 'one'])
        tree = window.candidate_tree
        self.assertEqual(tree.sortColumn(), POSITION)
        self.assertEqual([tree.topLevelItem(i).text(POSITION) for i in range(tree.topLevelItemCount())
                          if not tree.topLevelItem(i).isHidden()], ['1', '2', '3'])
        window.show_list_source(None)
        self.assertNotEqual(tree.sortColumn(), POSITION)  # the earlier sort is back
        self.assertTrue(all(tree.topLevelItem(i).text(POSITION) == '' for i in range(tree.topLevelItemCount())))

        # Loading it back into the Playlist tab, after changing the tab
        window.clear_playlist()
        self.add(window, 'three')
        node = {'kind': PLAYLIST, 'name': 'Friday set'}
        with patch.object(window, '_ask_replace_or_add', return_value='add'):
            window.load_into_playlist(node)
        self.assertEqual(self.playlist(window), ['three', 'two', 'four', 'one'])
        with patch.object(window, '_ask_replace_or_add', return_value='replace'):
            window.list_browser.node_activated.emit(node)  # a double-click
        self.assertEqual(self.playlist(window), ['two', 'four', 'one'])
        self.assertEqual(self.playlist(window, POSITION_COLUMN), ['1', '2', '3'])
        with patch.object(window, '_ask_replace_or_add', return_value=None):
            window.load_into_playlist({'kind': 'artist', 'name': 'Forme'})
        self.assertEqual(self.playlist(window), ['two', 'four', 'one'])

        restored = self.restart(window)
        self.assertEqual(restored.list_browser.playlists_root.child(0).text(0), 'Friday set')
        self.assertEqual(self.playlist(restored), ['two', 'four', 'one'])

    def test_saved_playlist_shows_tracks_hidden_as_playlist_tab_tracks(self):
        window = self.window()
        window.set_hide_playlist_tracks(True)
        self.add(window, 'two', 'one')
        self.assertEqual(sorted(self.shown(window)), ['four', 'three'])
        window.library_store.save_playlist('Set', window._playlist_records())
        window.refresh_saved_lists()
        window.show_list_source({'kind': PLAYLIST, 'name': 'Set'})
        self.assertEqual(self.shown(window), ['two', 'one'])
        window.show_list_source({'kind': 'genre', 'name': 'House'})  # other entries still hide them
        self.assertEqual(self.shown(window), ['three'])

    def test_playlist_rows_move_and_insert_where_dropped(self):
        window = self.window()
        self.add(window, 'one', 'two', 'three')
        tree = window.playlist_tree
        tree.topLevelItem(2).setSelected(True)
        tree.move_selected(0)
        self.assertEqual(self.playlist(window), ['three', 'one', 'two'])
        tree.clearSelection()
        tree.topLevelItem(0).setSelected(True)
        tree.topLevelItem(1).setSelected(True)
        tree.move_selected(3)  # to the end, keeping their order
        self.assertEqual(self.playlist(window), ['two', 'three', 'one'])
        window.add_paths_to_playlist([str(self.paths['four']), str(self.paths['one'])], 1)
        self.assertEqual(self.playlist(window), ['two', 'four', 'three', 'one'])  # 'one' stays where it was
        self.assertEqual(self.playlist(window, POSITION_COLUMN), ['1', '2', '3', '4'])
        self.assertEqual(self.playlist(self.restart(window)), ['two', 'four', 'three', 'one'])

    def test_dragging_entries_to_the_list_and_the_playlist_tab(self):
        window = self.window()
        self.assertTrue(self.drop(window.candidate_tree, self.node_mime({'kind': 'genre', 'name': 'House'})))
        self.assertEqual(sorted(self.shown(window)), ['three', 'two'])
        window.library_store.save_smartlist('fast', [{'column': 'Original BPM', 'condition': 'greater than', 'value': '124'}])
        window.refresh_saved_lists()
        self.assertTrue(self.drop(window.playlist_tree, self.node_mime({'kind': SMARTLIST, 'name': 'fast'})))
        self.assertEqual(sorted(self.playlist(window)), ['one', 'three'])

    def test_tracks_dropped_on_a_playlist_in_the_browser_are_added(self):
        from PyQt5.QtCore import QMimeData

        from songselector.ui.tree_widgets import TRACKS_MIME
        window = self.window()
        window.library_store.save_playlist('Set', [])
        window.library_store.save_smartlist('Rules', [])
        window.refresh_saved_lists()
        browser = window.list_browser
        browser.setCurrentItem(browser.playlists_root.child(1))  # 'Set' is shown
        self.assertEqual(self.shown(window), [])
        mime = QMimeData()
        mime.setData(TRACKS_MIME, '\n'.join(str(self.paths[t]) for t in ('four', 'two')).encode('utf-8'))
        target = browser.visualItemRect(browser.playlists_root.child(1)).center()
        self.assertTrue(self.drop(browser, mime, target))
        self.assertEqual(self.shown(window), ['four', 'two'])  # the List follows
        smartlist = browser.visualItemRect(browser.playlists_root.child(0)).center()
        self.assertFalse(self.drop(browser, mime, smartlist))  # not onto a smartlist

    def test_smartlist_lists_current_matches_and_can_be_renamed_and_deleted(self):
        window = self.window()
        rules = [{'column': 'Genre', 'condition': 'contains', 'value': 'house'},
                 {'column': 'None', 'condition': 'is', 'value': 'ignored'}]
        node = window.save_smartlist('House', rules)
        window.show_list_source(node)
        self.assertEqual(sorted(self.shown(window)), ['four', 'three', 'two'])
        self.assertIn('Genre contains house', window.source_label.text())
        window.set_song_selector_fields([str(self.paths['four'])], SS_Rating=5)
        window.save_smartlist('House', rules + [{'column': 'Rating - Song Selector', 'condition': 'at least (>=)', 'value': '4'}])
        self.assertEqual(self.shown(window), ['four'])  # edited rules apply at once
        with patch('songselector.ui.saved_lists.QInputDialog.getText', return_value=('Best house', True)):
            window.rename_saved_list(node)
        self.assertEqual(window.list_source, {'kind': SMARTLIST, 'name': 'Best house'})
        self.assertEqual(self.shown(window), ['four'])
        window.delete_saved_list(window.list_source, confirm=False)
        self.assertIsNone(window.list_source)
        self.assertEqual(len(self.shown(window)), 4)
        self.assertEqual(window.library_store.saved_lists(), [])

    def test_names_in_use_are_refused_and_complex_search_saves_a_smartlist(self):
        window = self.window()
        window.save_smartlist('Rules', [])
        with patch('songselector.ui.saved_lists.QInputDialog.getText', return_value=('rules', True)), \
                patch('songselector.ui.saved_lists.QMessageBox.warning') as warning:
            self.assertIsNone(window.save_playlist_as())
        warning.assert_called_once()
        self.assertEqual(window.library_store.saved_list('Rules')['kind'], SMARTLIST)

        from PyQt5.QtCore import QTimer
        def configure():
            dialog = window.advanced_search_dialog
            row = dialog.filter_rows[0]
            row.column_combo.setCurrentText('Artist')
            row.value_edit.setText('cat')
            with patch('songselector.ui.saved_lists.QInputDialog.getText', return_value=('Cats', True)):
                dialog.button_save_smartlist.click()
            dialog.button_cancel.click()
        QTimer.singleShot(0, configure)
        window.open_advanced_search()
        self.assertEqual(window.library_store.saved_list('Cats')['rules'],
                         [{'column': 'Artist', 'condition': 'contains', 'value': 'cat'}])
        window.show_list_source({'kind': SMARTLIST, 'name': 'Cats'})
        self.assertEqual(sorted(self.shown(window)), ['one', 'three'])

    # -- drops keep the view; Traktor's playlists ------------------------------------------

    def external_files(self, *names):
        from PyQt5.QtCore import QMimeData
        paths = []
        for name in names:
            path = self.root / f'{name}.wav'
            path.write_bytes(b'')
            paths.append(path)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        return mime

    def test_files_dropped_on_the_list_showing_a_playlist_are_added_to_it(self):
        # Bug in 4.22.0: 136 tracks dropped from Traktor onto the List while it showed a playlist
        # were only imported into the library, and the List jumped to all tracks.
        window = self.window()
        window.library_store.save_playlist('Set', [track(self.paths['four'], 'four')])
        window.refresh_saved_lists()
        window.show_list_source({'kind': PLAYLIST, 'name': 'Set'})
        mime = self.external_files('new b', 'new a')
        mime.setUrls(mime.urls() + [QUrl.fromLocalFile(str(self.paths['two']))])
        self.assertTrue(self.drop(window.candidate_tree, mime))
        self.assertEqual(window.list_source, {'kind': PLAYLIST, 'name': 'Set'})  # still shown
        self.assertEqual(self.shown(window), ['four', 'new b', 'new a', 'two'])  # dropped order, by #
        self.assertEqual(len(window.library_store.playlist_keys('Set')), 4)
        self.assertIn(canonical_path(self.root / 'new a.wav'), window._rows_by_path())  # in the library too

    def test_files_dropped_on_a_browser_playlist_keep_the_list_as_it_is(self):
        window = self.window()
        window.library_store.save_playlist('Set', [])
        window.refresh_saved_lists()
        browser = window.list_browser
        browser.setCurrentItem(browser.playlists_root.child(0))
        target = browser.visualItemRect(browser.playlists_root.child(0)).center()
        self.assertTrue(self.drop(browser, self.external_files('x', 'y'), target))
        self.assertEqual(window.list_source, {'kind': PLAYLIST, 'name': 'Set'})
        self.assertEqual(self.shown(window), ['x', 'y'])

    def traktor_playlists(self, window):
        """Traktor's tree as TraktorCollection.playlists has it: a folder with a playlist, a smartlist."""
        (self.root / 'not imported.mp3').write_bytes(b'')
        window.importer.collection.playlists = [
            {'type': 'FOLDER', 'name': 'Sets', 'children': [
                {'type': 'PLAYLIST', 'name': 'Breakbeat', 'tracks': [
                    str(self.paths['three']), str(self.root / 'gone.mp3'), str(self.paths['one']),
                    str(self.root / 'not imported.mp3')]}]},
            {'type': 'SMARTLIST', 'name': 'Fast', 'query': '$BPM > 165.000000'}]
        window.refresh_traktor_playlists()
        return {'kind': 'traktor', 'name': 'Breakbeat', 'path': ['Sets', 'Breakbeat']}

    def test_traktor_playlists_are_listed_shown_loaded_and_copied(self):
        window = self.window()
        node = self.traktor_playlists(window)
        browser = window.list_browser
        self.assertEqual(browser.traktor_root.text(0), 'Traktor Playlists (1)')
        folder = browser.traktor_root.child(0)
        self.assertEqual((folder.text(0), folder.child(0).text(0)), ('Sets', 'Breakbeat'))
        self.assertIn('not supported yet', browser.traktor_root.child(1).toolTip(0))
        browser.setCurrentItem(folder.child(0))
        self.assertEqual(window.list_source, node)
        self.assertEqual(self.shown(window), ['three', 'one'])  # Traktor's order, by #
        self.assertIn('2 of its tracks are not in the library list', window.source_label.text())
        browser.setCurrentItem(browser.traktor_root.child(1))  # a Traktor smartlist: nothing happens
        self.assertEqual(window.list_source, node)

        browser.node_activated.emit(node)  # double-click: into the Playlist tab
        self.assertEqual(self.playlist(window), ['three', 'one'])

        window.import_foreign_missing(node)  # the file that exists comes in; the view stays
        self.assertEqual(window.list_source, node)
        self.assertEqual(self.shown(window), ['three', 'one', 'not imported'])
        with patch('songselector.ui.saved_lists.QInputDialog.getText', return_value=('My breaks', True)):
            copy = window.copy_foreign_playlist(node)
        self.assertEqual([r['Title'] for r in window.library_store.load_playlist('My breaks')],
                         ['three', 'one', 'not imported'])
        window.show_list_source(copy)
        self.assertEqual(self.shown(window), ['three', 'one', 'not imported'])

        # Traktor saved again without that playlist: showing it falls back to all tracks
        window.importer.collection.playlists = []
        window.refresh_traktor_playlists()
        self.assertEqual(window.list_source, copy)
        window.show_list_source(node)
        self.assertIsNone(window.list_source)

    def test_rekordbox_playlists_are_listed_shown_loaded_and_copied_like_traktors(self):
        from songselector.core.rekordbox_library import RekordboxLibrary
        window = self.window()
        browser = window.list_browser
        self.assertTrue(browser.rekordbox_root.isHidden())  # no Rekordbox library: no entry
        (self.root / 'not imported.mp3').write_bytes(b'')
        library = RekordboxLibrary(str(self.root / 'master.db'))
        library.playlists = [
            {'type': 'FOLDER', 'name': 'Sets', 'children': [
                {'type': 'PLAYLIST', 'name': 'Peak', 'tracks': [
                    str(self.paths['four']), str(self.root / 'gone.mp3'), str(self.paths['two']),
                    str(self.root / 'not imported.mp3')]}]},
            {'type': 'SMARTLIST', 'name': 'Fast', 'query': '<NODE/>'}]
        window._rekordbox_changed(library)  # what the watcher does after reading master.db
        node = {'kind': 'rekordbox', 'name': 'Peak', 'path': ['Sets', 'Peak']}
        self.assertFalse(browser.rekordbox_root.isHidden())
        self.assertEqual(browser.rekordbox_root.text(0), 'Rekordbox Playlists (1)')
        self.assertEqual(browser.traktor_root.childCount(), 0)
        self.assertIn('Rekordbox smartlist (not supported yet)', browser.rekordbox_root.child(1).toolTip(0))
        browser.setCurrentItem(browser.rekordbox_root.child(0).child(0))
        self.assertEqual(window.list_source, node)
        self.assertEqual(self.shown(window), ['four', 'two'])  # Rekordbox's order, by #
        self.assertIn('Showing Rekordbox playlist: Peak', window.source_label.text())
        self.assertIn('2 of its tracks are not in the library list', window.source_label.text())

        browser.node_activated.emit(node)
        self.assertEqual(self.playlist(window), ['four', 'two'])
        window.import_foreign_missing(node)
        self.assertEqual(self.shown(window), ['four', 'two', 'not imported'])
        with patch('songselector.ui.saved_lists.QInputDialog.getText', return_value=('From Rekordbox', True)):
            copy = window.copy_foreign_playlist(node)
        self.assertEqual([r['Title'] for r in window.library_store.load_playlist('From Rekordbox')],
                         ['four', 'two', 'not imported'])
        window.show_list_source(copy)
        self.assertEqual(self.shown(window), ['four', 'two', 'not imported'])

        library = RekordboxLibrary(str(self.root / 'master.db'))  # Rekordbox saved again, without that playlist
        window._rekordbox_changed(library)
        self.assertEqual(window.list_source, copy)
        window.show_list_source(node)
        self.assertIsNone(window.list_source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
