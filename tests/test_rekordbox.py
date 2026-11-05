"""Rekordbox's playlists, read straight from its encrypted library (core/rekordbox_library.py)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from traktor_key_calculator.core.rekordbox_library import RekordboxLibrary, database_key, discover_library, signature


def write_library(path, playlists, contents, songs):
    """A small database with the tables and columns Rekordbox's master.db has that the reader uses,
    encrypted with Rekordbox's key."""
    from sqlcipher3 import dbapi2 as sqlcipher
    connection = sqlcipher.connect(str(path))
    connection.execute(f"PRAGMA key='{database_key()}'")
    connection.execute('CREATE TABLE djmdPlaylist (ID, Seq, Name, Attribute, ParentID, SmartList, rb_local_deleted)')
    connection.execute('CREATE TABLE djmdSongPlaylist (PlaylistID, ContentID, TrackNo, rb_local_deleted)')
    connection.execute('CREATE TABLE djmdContent (ID, FolderPath, rb_local_deleted)')
    connection.executemany('INSERT INTO djmdPlaylist VALUES (?, ?, ?, ?, ?, ?, ?)', playlists)
    connection.executemany('INSERT INTO djmdContent VALUES (?, ?, ?)', contents)
    connection.executemany('INSERT INTO djmdSongPlaylist VALUES (?, ?, ?, ?)', songs)
    connection.commit()
    connection.close()


# ID, Seq, Name, Attribute (0 playlist, 1 folder, 4 smart playlist), ParentID, SmartList, deleted
PLAYLISTS = [
    ('p2', 2, 'Warm-up', 0, 'f1', None, 0),
    ('f1', 2, 'Sets', 1, 'root', None, 0),
    ('p1', 1, 'Peak', 0, 'root', None, 0),
    ('p3', 3, 'Old', 0, 'root', None, 1),                       # deleted in Rekordbox
    ('s1', 3, 'Fast', 4, 'root', '<NODE Id="1"/>', 0),
    ('p4', 1, 'Inner', 0, 'f1', None, 0),
]
CONTENTS = [('10', 'E:/DJ/a.mp3', 0), ('11', 'E:/DJ/Break/b.mp3', 0), ('12', 'beatport:12345', 0),
            ('13', 'E:/DJ/gone.mp3', 1), ('14', '//server/share/c.mp3', 0)]
SONGS = [('p1', '11', 1, 0), ('p1', '12', 2, 0), ('p1', '10', 3, 0), ('p1', '13', 4, 0),   # 12 streams, 13 is deleted
         ('p2', '10', 2, 0), ('p2', '14', 1, 0), ('p2', '11', 3, 1)]                        # last entry removed


class RekordboxLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TRAKTOR_APP_DATA_DIR'])
        self.path = str(Path(self.temp.name) / 'master.db')
        write_library(self.path, PLAYLISTS, CONTENTS, SONGS)

    def tearDown(self):
        self.temp.cleanup()

    def test_folders_playlists_smartlists_and_track_order_are_read(self):
        library = RekordboxLibrary(self.path)
        library._load()
        self.assertEqual(library.error, '')
        self.assertEqual(library.track_count, 4)  # the deleted track is not counted
        self.assertEqual(library.playlists, [
            {'type': 'PLAYLIST', 'name': 'Peak', 'tracks': ['E:\\DJ\\Break\\b.mp3', 'E:\\DJ\\a.mp3']},  # TrackNo order; streaming and deleted skipped
            {'type': 'FOLDER', 'name': 'Sets', 'children': [
                {'type': 'PLAYLIST', 'name': 'Inner', 'tracks': []},
                {'type': 'PLAYLIST', 'name': 'Warm-up', 'tracks': ['\\\\server\\share\\c.mp3', 'E:\\DJ\\a.mp3']}]},
            {'type': 'SMARTLIST', 'name': 'Fast', 'query': '<NODE Id="1"/>'}])

    def test_only_a_changed_library_is_read_again_and_a_bad_read_keeps_the_last_playlists(self):
        library = RekordboxLibrary(self.path)
        library._load()
        before = library.playlists
        with patch.object(RekordboxLibrary, '_read', side_effect=AssertionError('read twice')):
            library._load()  # unchanged: not read again
        self.assertEqual(library.error, '')
        Path(self.path).write_bytes(b'not a database' * 100)  # e.g. Rekordbox rewriting it
        library._load()
        self.assertIn('Cannot read the Rekordbox library', library.error)
        self.assertEqual(library.playlists, before)

    def test_missing_library_and_signature(self):
        self.assertIsNone(signature(str(Path(self.temp.name) / 'none.db')))
        library = RekordboxLibrary(str(Path(self.temp.name) / 'none.db'))
        library._load()
        self.assertIn('Cannot read', library.error)
        self.assertEqual(library.playlists, [])
        self.assertIsInstance(signature(self.path), tuple)

    def test_the_library_is_read_from_a_copy_and_not_changed(self):
        before = Path(self.path).read_bytes()
        RekordboxLibrary(self.path)._load()
        self.assertEqual(Path(self.path).read_bytes(), before)
        self.assertEqual(sorted(os.listdir(self.temp.name)), ['master.db'])

    def test_discovery_uses_the_override_the_settings_file_and_the_standard_place(self):
        with patch.dict(os.environ, {'TRAKTOR_REKORDBOX_LIBRARY': 'none'}):
            self.assertEqual(discover_library(), '')
        with patch.dict(os.environ, {'TRAKTOR_REKORDBOX_LIBRARY': r'D:\x\master.db'}):
            self.assertEqual(discover_library(), r'D:\x\master.db')
        appdata = Path(self.temp.name) / 'Roaming'
        (appdata / 'Pioneer' / 'rekordbox6').mkdir(parents=True)
        library_folder = Path(self.temp.name) / 'Library'
        library_folder.mkdir()
        (library_folder / 'master.db').write_bytes(b'x')
        (appdata / 'Pioneer' / 'rekordbox6' / 'rekordbox3.settings').write_text(
            f'<ROOT><VALUE name="masterDbDirectory" val="{library_folder}"/></ROOT>', encoding='utf-8')
        env = {key: value for key, value in os.environ.items() if key != 'TRAKTOR_REKORDBOX_LIBRARY'}
        env['APPDATA'] = str(appdata)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(discover_library(), str(library_folder / 'master.db'))
            (library_folder / 'master.db').unlink()
            self.assertEqual(discover_library(), '')  # settings point to nothing, standard place is empty


if __name__ == '__main__':
    unittest.main(verbosity=2)
