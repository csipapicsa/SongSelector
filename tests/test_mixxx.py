"""Mixxx's library, read straight from mixxxdb.sqlite (core/mixxx_library.py), and how its values meet
Traktor's: the primary DJ program decides, the others fill gaps (core/dj_programs.py, core/traktor_sync.py)."""
import copy
import json
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from test_imports import make_collection, tagged_file

from songselector.core.dj_programs import MIXXX, TRAKTOR, priority, resolve_primary
from songselector.core.mixxx_library import MixxxLibrary, chromatic_key, discover_library, signature
from songselector.core.track_import import TrackImporter, enrich_ratings
from songselector.core.traktor_collection import TraktorCollection, canonical_path
from songselector.core.traktor_sync import MIXXX_SOURCE, collection_changes, track_changes

P = os.path.normpath  # Mixxx's paths as this system writes them (backslashes on Windows)


def write_library(path, tracks, playlists=(), crates=()):
    """A database with the tables and columns of Mixxx 2.5's mixxxdb.sqlite that the reader uses.
    tracks: dicts with id, location and any of artist, title, bpm, key, key_id, rating, color, mixxx_deleted,
    filesize; playlists: (id, name, position, hidden, [track ids]); crates: (id, name, [track ids])."""
    with closing(sqlite3.connect(str(path))) as connection, connection:
        connection.executescript("""
            CREATE TABLE track_locations (id INTEGER PRIMARY KEY, location varchar(512), filename varchar(512),
                directory varchar(512), filesize INTEGER, fs_deleted INTEGER, needs_verification INTEGER);
            CREATE TABLE library (id INTEGER PRIMARY KEY, artist varchar(64), title varchar(64), album varchar(64),
                genre varchar(64), comment varchar(256), location INTEGER, bpm FLOAT, key varchar(8), key_id INTEGER,
                rating INTEGER, color INTEGER, mixxx_deleted INTEGER);
            CREATE TABLE Playlists (id INTEGER PRIMARY KEY, name varchar(48), position INTEGER, hidden INTEGER,
                date_created datetime, date_modified datetime, locked INTEGER);
            CREATE TABLE PlaylistTracks (id INTEGER PRIMARY KEY, playlist_id INTEGER, track_id INTEGER,
                position INTEGER, pl_datetime_added);
            CREATE TABLE crates (id INTEGER PRIMARY KEY, name varchar(48), count INTEGER, show INTEGER,
                locked INTEGER, autodj_source INTEGER);
            CREATE TABLE crate_tracks (crate_id INTEGER, track_id INTEGER);""")
        for track in tracks:
            location = str(track['location'])
            connection.execute('INSERT INTO track_locations (id, location, filename, filesize, fs_deleted) '
                               'VALUES (?, ?, ?, ?, 0)', (track['id'], location, location.replace('\\', '/').split('/')[-1],
                                                          track.get('filesize', 0)))
            connection.execute('INSERT INTO library (id, artist, title, location, bpm, key, key_id, rating, color, '
                               'mixxx_deleted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                               (track['id'], track.get('artist'), track.get('title'), track['id'], track.get('bpm', 0),
                                track.get('key', ''), track.get('key_id', 0), track.get('rating', 0),
                                track.get('color'), track.get('mixxx_deleted', 0)))
        for list_id, name, position, hidden, track_ids in playlists:
            connection.execute('INSERT INTO Playlists (id, name, position, hidden) VALUES (?, ?, ?, ?)',
                               (list_id, name, position, hidden))
            connection.executemany('INSERT INTO PlaylistTracks (playlist_id, track_id, position) VALUES (?, ?, ?)',
                                   [(list_id, track, index + 1) for index, track in enumerate(track_ids)])
        for crate_id, name, track_ids in crates:
            connection.execute('INSERT INTO crates (id, name) VALUES (?, ?)', (crate_id, name))
            connection.executemany('INSERT INTO crate_tracks VALUES (?, ?)', [(crate_id, track) for track in track_ids])


TRACKS = [
    # From the user's Mixxx 2.5.6 library: BPM and key from the tags ('9d' = A flat major = key_id 9).
    {'id': 1, 'location': '/mnt/e/DJ/Break/Test the Bass.mp3', 'artist': 'Badboe', 'title': 'Test the Bass',
     'bpm': 135.0, 'key': '9d', 'key_id': 9, 'rating': 3, 'color': 0x880000},
    # Analysed by Mixxx: decimal BPM, key text in Mixxx's notation, minor key (21 = G# minor).
    {'id': 2, 'location': '/mnt/e/DJ/Break/Bring 4th.mp3', 'bpm': 130.98052579338102, 'key': 'Abm', 'key_id': 21,
     'color': 0x00FFFF},
    {'id': 3, 'location': 'E:/DJ/Windows path.mp3', 'key': 'Cm', 'key_id': 0},  # no key id: the text is read
    {'id': 4, 'location': '/mnt/e/DJ/Hidden.mp3', 'mixxx_deleted': 1},           # removed from the library
]
PLAYLISTS = [(1, 'Auto DJ', 1, 1, []), (3, '2026-11-20', 3, 2, [2, 1]), (5, '2026-11-21', 5, 2, [1]),
             (6, 'test_playlists', 6, 0, [2, 1, 4]), (7, 'test_playlist_2', 7, 0, [3])]
CRATES = [(1, 'Warm-up', [1, 2]), (2, 'Acid', [])]


class MixxxLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.path = Path(self.temp.name) / 'mixxxdb.sqlite'
        write_library(self.path, TRACKS, PLAYLISTS, CRATES)

    def tearDown(self):
        self.temp.cleanup()

    def load(self):
        library = MixxxLibrary(self.path)
        library._load()
        self.assertEqual(library.error, '')
        return library

    def test_tracks_with_bpm_key_rating_and_exact_colour(self):
        library = self.load()
        self.assertEqual(library.track_count, 3)  # the removed track is not in the library
        first = library.find('/mnt/e/DJ/Break/Test the Bass.mp3')
        self.assertEqual((first['bpm'], first['key'], first['rating'], first['color'], first['artist']),
                         (135.0, ('G#', 'major'), 3, '#880000', 'Badboe'))
        second = library.find('/mnt/e/DJ/Break/Bring 4th.mp3')
        self.assertEqual((second['bpm'], second['key'], second['rating'], second['color']),
                         (130.98052579338102, ('G#', 'minor'), None, '#00FFFF'))  # rating 0: unrated
        windows = library.by_path[canonical_path('E:\\DJ\\Windows path.mp3')]
        self.assertEqual((windows['key'], windows['bpm'], windows['color']), (('C', 'minor'), None, None))
        self.assertIsNone(library.find('/mnt/e/DJ/Hidden.mp3'))

    def test_every_key_id_is_mixxx_chromatic_key(self):
        # src/proto/keys.proto: 1 C major ... 12 B major, 13 C minor ... 24 B minor
        self.assertEqual(chromatic_key(1), ('C', 'major'))
        self.assertEqual(chromatic_key(12), ('B', 'major'))
        self.assertEqual(chromatic_key(13), ('C', 'minor'))
        self.assertEqual(chromatic_key(22), ('A', 'minor'))
        self.assertEqual(chromatic_key(24), ('B', 'minor'))
        self.assertEqual(chromatic_key(0, '3m'), ('B', 'minor'))  # Open Key text, as Traktor writes it
        self.assertIsNone(chromatic_key(None))

    def test_playlists_then_crates_then_history_newest_first(self):
        bass, bring, hidden = (P('/mnt/e/DJ/Break/Test the Bass.mp3'), P('/mnt/e/DJ/Break/Bring 4th.mp3'),
                               P('/mnt/e/DJ/Hidden.mp3'))
        self.assertEqual(self.load().playlists, [
            {'type': 'PLAYLIST', 'name': 'test_playlists', 'tracks': [bring, bass, hidden]},  # Mixxx's order
            {'type': 'PLAYLIST', 'name': 'test_playlist_2', 'tracks': ['E:\\DJ\\Windows path.mp3']},
            {'type': 'FOLDER', 'name': 'Crates', 'children': [
                {'type': 'PLAYLIST', 'name': 'Acid', 'tracks': []},
                {'type': 'PLAYLIST', 'name': 'Warm-up', 'tracks': [bring, bass]}]},  # by artist: none first
            {'type': 'FOLDER', 'name': 'History', 'children': [
                {'type': 'PLAYLIST', 'name': '2026-11-21', 'tracks': [bass]},
                {'type': 'PLAYLIST', 'name': '2026-11-20', 'tracks': [bring, bass]}]}])

    def test_a_file_is_found_by_its_name_and_size_when_its_path_differs(self):
        track = tagged_file(Path(self.temp.name) / 'moved.mp3')
        write_library(self.path.with_name('other.sqlite'), [
            {'id': 1, 'location': '/old/place/moved.mp3', 'bpm': 128, 'filesize': track.stat().st_size}])
        library = MixxxLibrary(self.path.with_name('other.sqlite'))
        self.assertEqual(library.find(track)['bpm'], 128)

    def test_only_a_changed_library_is_read_again_and_a_bad_read_keeps_the_last_one(self):
        library = self.load()
        before = library.by_path
        with patch.object(MixxxLibrary, '_read', side_effect=AssertionError('read twice')):
            library._load()  # unchanged: not read again
        time.sleep(0.01)
        self.path.write_bytes(b'not a database' * 100)  # e.g. Mixxx writing it right now
        library._load()
        self.assertIn('Cannot read the Mixxx library', library.error)
        self.assertEqual(library.by_path, before)

    def test_missing_library(self):
        self.assertIsNone(signature(str(self.path.with_name('none.sqlite'))))
        library = MixxxLibrary(self.path.with_name('none.sqlite'))
        library._load()
        self.assertIn('does not exist', library.error)
        self.assertEqual((library.playlists, library.by_path), ([], {}))

    def test_discovered_in_the_home_folder_or_switched_off(self):
        home = Path(self.temp.name) / 'home'
        (home / '.mixxx').mkdir(parents=True)
        write_library(home / '.mixxx' / 'mixxxdb.sqlite', TRACKS)
        with patch.dict(os.environ), patch('pathlib.Path.home', return_value=home):
            os.environ.pop('SONGSELECTOR_MIXXX_LIBRARY', None)
            os.environ.pop('LOCALAPPDATA', None)
            self.assertEqual(discover_library(), str(home / '.mixxx' / 'mixxxdb.sqlite'))
        with patch.dict(os.environ, {'SONGSELECTOR_MIXXX_LIBRARY': 'none'}):
            self.assertEqual(discover_library(), '')


class PriorityTests(unittest.TestCase):
    def test_primary_first_and_automatic_choice(self):
        self.assertEqual(priority(MIXXX), [MIXXX, TRAKTOR])
        self.assertEqual(priority(TRAKTOR), [TRAKTOR, MIXXX])
        self.assertEqual(resolve_primary('auto', {MIXXX}), MIXXX)          # only Mixxx found: it is the primary
        self.assertEqual(resolve_primary('auto', {TRAKTOR, MIXXX}), TRAKTOR)
        self.assertEqual(resolve_primary('auto', set()), TRAKTOR)
        self.assertEqual(resolve_primary(MIXXX, {TRAKTOR}), MIXXX)        # an explicit choice stays

    def test_a_program_that_does_not_decide_only_fills_empty_values(self):
        row = {'File_Path': '/a.mp3', 'Musical_Key_Base': 'A', 'BaseMinorOrMajor': 'minor', 'BPM': None,
               'Color': 5, 'Rating': None}
        now = {'key': 'C major', 'bpm': 131.0, 'color': '#00FFFF', 'rating': 4}
        self.assertEqual(track_changes(row, now, source=MIXXX_SOURCE, fill_only=True),
                         {'BPM': 131.0, 'BPM_Source': MIXXX_SOURCE, 'Rating': 4})
        uncoloured = dict(row, Color=0)
        self.assertEqual(track_changes(uncoloured, now, source=MIXXX_SOURCE, fill_only=True)['Color'], '#00FFFF')

    def test_exact_colours_are_synced_and_no_colour_does_not_clear_on_first_sight(self):
        row = {'File_Path': '/a.mp3', 'Color': 3, 'Rating': 2}
        seen = {'key': None, 'bpm': None, 'color': '#FF8800', 'rating': 2}
        self.assertEqual(track_changes(row, dict(seen, color='#00FF00'), seen, MIXXX_SOURCE),
                         {'Color': '#00FF00', 'Color_Source': MIXXX_SOURCE})
        self.assertEqual(track_changes(row, dict(seen, color=0), seen=None, source=MIXXX_SOURCE), {})
        self.assertEqual(track_changes(row, dict(seen, color='#ff8800'), seen=seen, source=MIXXX_SOURCE), {})

    def test_the_deciding_program_per_track(self):
        table = pd.DataFrame([{'File_Path': '/both.mp3', 'Color': 4}, {'File_Path': '/mixxx-only.mp3', 'Color': 4}])
        by_path = {canonical_path('/both.mp3'): {'color': '#FF8800'},
                   canonical_path('/mixxx-only.mp3'): {'color': '#FF8800'}}
        seen = {key: {'key': None, 'bpm': None, 'color': 4, 'rating': None} for key in by_path}
        traktor_has = {canonical_path('/both.mp3')}
        changes = collection_changes(table, by_path, seen, MIXXX_SOURCE, lambda key: key not in traktor_has)
        self.assertEqual(list(changes), [1])  # Traktor decides the first track: Mixxx's colour change is not taken
        self.assertEqual(changes[1]['Color'], '#FF8800')


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_an_untagged_file_gets_mixxx_analysis_colour_and_rating(self):
        track = tagged_file(self.root / 'a.mp3', key=None, bpm=None)
        write_library(self.root / 'mixxxdb.sqlite', [{'id': 1, 'location': track, 'bpm': 131.78, 'key_id': 16,
                                                      'rating': 5, 'color': 0xFF00FF}])
        record = TrackImporter('', self.root / 'mixxxdb.sqlite', primary=MIXXX).read(track)
        self.assertEqual((record['BPM'], record['Musical_Key_Base'], record['BaseMinorOrMajor'], record['Color']),
                         (131.78, 'D#', 'minor', '#FF00FF'))
        self.assertEqual((record['Key_Source'], record['BPM_Source'], record['Color_Source']),
                         ('Mixxx library', 'Mixxx library', 'Mixxx library'))
        self.assertEqual(record['Rating'], 4)  # the file's own POPM rating (204) comes first, as for Traktor

    def test_the_primary_programs_values_come_first(self):
        track = tagged_file(self.root / 'a.mp3', key=None, bpm=None)
        nml = self.root / 'collection.nml'
        make_collection(nml, [(track, 0, 128)])  # Traktor: C major, 128 BPM, colour 5 (blue)
        write_library(self.root / 'mixxxdb.sqlite', [{'id': 1, 'location': track, 'bpm': 64.0, 'key_id': 16,
                                                      'color': 0x00FF00}])
        traktor_first = TrackImporter(nml, self.root / 'mixxxdb.sqlite', primary=TRAKTOR).read(track)
        self.assertEqual((traktor_first['BPM'], traktor_first['Musical_Key_Base'], traktor_first['Color']),
                         (128.0, 'C', 5))
        mixxx_first = TrackImporter(nml, self.root / 'mixxxdb.sqlite', primary=MIXXX).read(track)
        self.assertEqual((mixxx_first['BPM'], mixxx_first['Musical_Key_Base'], mixxx_first['Color'],
                          mixxx_first['Color_Source']), (64.0, 'D#', '#00FF00', 'Mixxx library'))

    def test_ratings_of_a_loaded_list_come_from_the_first_program_that_has_one(self):
        write_library(self.root / 'mixxxdb.sqlite', [{'id': 1, 'location': '/x/a.mp3', 'rating': 2},
                                                     {'id': 2, 'location': '/x/b.mp3', 'rating': 0}])
        table = pd.DataFrame([{'File_Path': '/x/a.mp3', 'Rating': None}, {'File_Path': '/x/b.mp3', 'Rating': None}])
        result = enrich_ratings(table, TraktorCollection(''), MixxxLibrary(self.root / 'mixxxdb.sqlite'))
        self.assertEqual(result['Rating'].tolist()[0], 2)
        self.assertTrue(pd.isna(result['Rating'].tolist()[1]))


class WindowTests(unittest.TestCase):
    """Traktor and Mixxx both linked, as for a DJ who uses both."""

    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        from songselector.config import SETTINGS_DEFAULT
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR'])
        self.root = Path(self.temp.name)
        self.both = tagged_file(self.root / 'both.mp3')           # in Traktor and in Mixxx
        self.only = tagged_file(self.root / 'mixxx-only.mp3')     # only in Mixxx
        self.nml = self.root / 'collection.nml'
        make_collection(self.nml, [(self.both, 0, 120)])         # Traktor: colour 5, rating 5
        self.mixxx = self.root / 'mixxxdb.sqlite'
        self.write_mixxx(both_colour=0xFF8800, only_colour=0x00FFFF)
        settings = copy.deepcopy(SETTINGS_DEFAULT)
        settings.update({'Traktor collection': str(self.nml), 'Mixxx library': str(self.mixxx),
                         'Advanced search': {'enabled': False, 'filters': []}})
        (self.root / 'settings.json').write_text(json.dumps(settings))
        library = pd.DataFrame([{'Artist': 'A', 'Title': 'Both', 'BPM': 120, 'File_Path': str(self.both),
                                 'Musical_Key_Base': 'B', 'BaseMinorOrMajor': 'major', 'Color': 0, 'Rating': None},
                                {'Artist': 'A', 'Title': 'Only', 'BPM': 133, 'File_Path': str(self.only),
                                 'Musical_Key_Base': 'B', 'BaseMinorOrMajor': 'major', 'Color': 0, 'Rating': None}])
        self.patches = [
            patch('songselector.ui.main_window.SETTINGS_FILE', str(self.root / 'settings.json')),
            patch('songselector.ui.main_window.DataManager.load_default_data', side_effect=lambda: library.copy()),
            patch('songselector.ui.traktor_watcher.FIRST_CHECK_MS', 600000),  # the test syncs itself
        ]
        for active in self.patches:
            active.start()
        from songselector.ui.main_window import MainWindow
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        for active in self.patches:
            active.stop()
        self.temp.cleanup()

    def write_mixxx(self, both_colour, only_colour, only_rating=3):
        self.mixxx.unlink(missing_ok=True)
        write_library(self.mixxx, [
            {'id': 1, 'location': self.both, 'bpm': 120.0, 'key_id': 12, 'rating': 1, 'color': both_colour},
            {'id': 2, 'location': self.only, 'bpm': 133.0, 'key_id': 12, 'rating': only_rating, 'color': only_colour}],
            playlists=[(6, 'test_playlists', 6, 0, [2, 1])])

    def read_mixxx(self):
        library = MixxxLibrary(self.mixxx)
        library._load()
        self.window._mixxx_changed(library)

    def read_traktor(self):
        collection = TraktorCollection(self.nml)
        collection._load()
        self.window._collection_changed(collection)

    def row(self, path):
        table = self.window.table
        return table[table['File_Path'].map(canonical_path) == canonical_path(path)].iloc[0]

    def test_mixxx_read_first_waits_for_traktor_the_primary(self):
        window = self.window
        self.assertEqual(window.importer.primary, TRAKTOR)  # automatic: Traktor is found first
        self.read_mixxx()
        self.assertEqual(self.row(self.both)['Color'], 0)  # waits: Traktor decides this track
        self.read_traktor()
        both, only = self.row(self.both), self.row(self.only)
        self.assertEqual((both['Color'], both['Rating']), (5, 5))           # Traktor's
        self.assertEqual((only['Color'], only['Rating']), ('#00FFFF', 3))   # only Mixxx has it: Mixxx's
        self.assertEqual(only['Color_Source'], 'Mixxx library')
        self.write_mixxx(both_colour=0x00FF00, only_colour=0xFF00FF, only_rating=5)  # colours changed in Mixxx
        self.read_mixxx()
        self.assertEqual(self.row(self.both)['Color'], 5)                   # Traktor still decides
        self.assertEqual((self.row(self.only)['Color'], self.row(self.only)['Rating']), ('#FF00FF', 5))
        self.assertIn('Updated from Mixxx: 1 track (colour 1, rating 1)', window.status_label.text())
        saved = {canonical_path(r['File_Path']): r for r in window.library_store.load_list('Library')}
        self.assertEqual(saved[canonical_path(self.only)]['Color'], '#FF00FF')  # stored as text in library.sqlite

    def test_making_mixxx_primary_brings_its_colours(self):
        self.read_traktor()
        self.read_mixxx()
        self.assertEqual(self.row(self.both)['Color'], 5)
        self.window.set_primary_program(MIXXX)
        self.assertEqual(self.window.importer.primary, MIXXX)
        self.assertEqual(self.row(self.both)['Color'], '#FF8800')
        self.assertTrue(self.window.primary_actions[MIXXX].isChecked())

    def test_mixxx_playlists_in_the_browser(self):
        from songselector.ui.list_browser import MIXXX as MIXXX_KIND
        self.read_mixxx()
        browser = self.window.list_browser
        self.assertFalse(browser.mixxx_root.isHidden())
        item = browser.mixxx_root.child(0)
        self.assertEqual(item.text(0), 'test_playlists')
        keys = self.window._foreign_keys({'kind': MIXXX_KIND, 'name': 'test_playlists', 'path': ['test_playlists']})
        self.assertEqual(keys, [canonical_path(self.only), canonical_path(self.both)])


if __name__ == '__main__':
    unittest.main()
