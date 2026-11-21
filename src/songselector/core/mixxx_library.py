"""Read-only access to Mixxx's library (mixxxdb.sqlite): every track's BPM, key, rating and colour, and the
playlists, crates and history.

Mixxx keeps its whole library in one plain SQLite database (no encryption, unlike Rekordbox), so Python's own
sqlite3 reads it. Nothing is written: the database is copied to a temporary folder first and the copy is read,
so Mixxx may be running. Values used (checked against Mixxx 2.5.6, schema 39, and Mixxx's src/proto/keys.proto):
- library.bpm: Mixxx's analysis, or the file's BPM tag until a track is analysed; 0 = none.
- library.key_id: ChromaticKey, 1-12 = C, Db, ..., B major, 13-24 = C, C#, ..., B minor; 0 = none. Used instead
  of the key text, which is in whatever notation the tag or Mixxx's setting used ('9d', 'Abm', 'G#').
- library.rating: 0-5 stars (0 = unrated). library.color: 0xRRGGBB, NULL = no colour.
- track_locations.location: the file's full path. Playlists.hidden: 0 = a playlist, 1 = Auto DJ, 2 = history.

`MixxxLibrary` has the shape of `TraktorCollection` (`path`, `error`, `by_path`, `by_filename`, `playlists`,
`keys()`, `find()`, `_load()`), so the same watcher, import, sync and Browser code serve both.
"""
import ntpath
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from songselector.core.key_formats import NOTES, parse_bpm, parse_key
from songselector.core.rekordbox_library import signature  # the same: size and time of the database and its WAL
from songselector.core.track_colors import hex_color
from songselector.core.traktor_collection import canonical_path, native_path
from songselector.env import getenv

DATABASE = 'mixxxdb.sqlite'
PLAYLIST, AUTO_DJ, HISTORY = 0, 1, 2  # Playlists.hidden


def discover_library():
    """Path of Mixxx's mixxxdb.sqlite in its standard places (the most recently written if there are several);
    '' if Mixxx has none."""
    override = getenv('MIXXX_LIBRARY')
    if override is not None:  # tests and unusual installs; 'none' or '' switches Mixxx off
        return '' if override.lower() in ('', 'none') else override
    home = Path.home()
    candidates = [home / '.mixxx',                                          # Linux
                  home / '.var' / 'app' / 'org.mixxx.Mixxx' / '.mixxx',    # Linux, Flatpak
                  home / 'Library' / 'Containers' / 'org.mixxx.mixxx' / 'Data' / 'Library' / 'Application Support'
                  / 'Mixxx',                                                # macOS (sandboxed)
                  home / 'Library' / 'Application Support' / 'Mixxx']      # macOS
    local = os.environ.get('LOCALAPPDATA')
    if local:
        candidates.append(Path(local) / 'Mixxx')                            # Windows
    existing = [folder / DATABASE for folder in candidates if (folder / DATABASE).is_file()]
    return str(max(existing, key=lambda path: path.stat().st_mtime)) if existing else ''


def chromatic_key(key_id, text=None):
    """('G#', 'major') for Mixxx's key_id 9 (A flat major); the key text if the id is missing; None."""
    try:
        number = int(key_id)
    except (TypeError, ValueError):
        number = 0
    if 1 <= number <= 24:
        return NOTES[(number - 1) % 12], 'major' if number <= 12 else 'minor'
    return parse_key(text) if text else None


def _rating(value):
    try:
        stars = int(value)
    except (TypeError, ValueError):
        return None
    return min(5, stars) if stars > 0 else None


def _local_path(location):
    """The track's path as this system writes it (Mixxx on Windows stores 'E:/DJ/a.mp3')."""
    text = (location or '').strip()
    return native_path(text) if text else ''


class MixxxLibrary:
    def __init__(self, path=''):
        self.path = str(path or '')
        self.error = ''
        self.by_path = {}
        self.by_filename = {}
        # Same shape as TraktorCollection.playlists: the playlists, then folders 'Crates' and 'History'.
        self.playlists = []
        self.track_count = 0
        self._signature = None

    def _load(self):
        if not self.path:
            return
        signature_now = signature(self.path)
        if signature_now is None:
            self.error = f'Cannot read the Mixxx library: {self.path} does not exist'
            return
        if signature_now == self._signature:
            return
        try:
            self.by_path, self.by_filename, self.playlists = self._read()
            self.track_count = len(self.by_path)
            self._signature = signature_now
            self.error = ''
        except (OSError, sqlite3.Error) as error:
            # The last valid library stays: Mixxx may be writing the file right now.
            self.error = f'Cannot read the Mixxx library: {error}'

    def _read(self):
        copy = tempfile.mkdtemp(prefix='songselector-mixxx-')
        try:
            target = os.path.join(copy, DATABASE)
            shutil.copyfile(self.path, target)
            for suffix in ('-wal', '-journal'):  # a write in progress: SQLite completes or rolls it back on open
                if os.path.isfile(self.path + suffix):
                    shutil.copyfile(self.path + suffix, target + suffix)
            with closing(sqlite3.connect(target)) as connection:
                return self._query(connection)
        finally:
            shutil.rmtree(copy, ignore_errors=True)

    @staticmethod
    def _query(connection):
        columns = {row[1] for row in connection.execute('PRAGMA table_info(library)')}
        colour = 'l.color' if 'color' in columns else 'NULL'  # Mixxx before 2.3 had no track colours
        rows = connection.execute(
            f'SELECT l.id, l.artist, l.title, l.album, l.genre, l.comment, l.bpm, l.key_id, l.key, l.rating, {colour}, '
            'l.mixxx_deleted, tl.location, tl.filename, tl.filesize '
            'FROM library l JOIN track_locations tl ON tl.id = l.location').fetchall()
        paths, by_path, by_filename = {}, {}, {}
        for (track_id, artist, title, album, genre, comment, bpm, key_id, key_text, rating, color, deleted,
             location, filename, size) in rows:
            path = _local_path(location)
            if not path:
                continue
            paths[track_id] = path
            if deleted:  # removed from Mixxx's library (it may still be on a playlist)
                continue
            record = {'path': path, 'artist': artist, 'title': title, 'album': album, 'genre': genre,
                      'comment': comment, 'bpm': parse_bpm(bpm), 'key': chromatic_key(key_id, key_text),
                      'color': hex_color(color) if color is not None else None, 'rating': _rating(rating),
                      'size_kb': size / 1024 if size else None}
            by_path[canonical_path(path)] = record
            by_filename.setdefault((filename or ntpath.basename(path)).casefold(), []).append(record)

        def tracks(sql, list_id):
            return [paths[track] for (track,) in connection.execute(sql, (list_id,)) if track in paths]

        in_playlist = 'SELECT track_id FROM PlaylistTracks WHERE playlist_id = ? ORDER BY position'
        playlists, history = [], []
        for list_id, name, hidden in connection.execute('SELECT id, name, hidden FROM Playlists ORDER BY position, id'):
            entry = {'type': 'PLAYLIST', 'name': name or '', 'tracks': tracks(in_playlist, list_id)}
            if hidden == PLAYLIST:
                playlists.append(entry)
            elif hidden == HISTORY:
                history.append(entry)
            elif hidden == AUTO_DJ and entry['tracks']:  # the Auto DJ queue, when something is queued
                playlists.insert(0, entry)
        crates = [{'type': 'PLAYLIST', 'name': name or '', 'tracks': tracks(
                      'SELECT ct.track_id FROM crate_tracks ct JOIN library l ON l.id = ct.track_id WHERE ct.crate_id = ? '
                      'ORDER BY l.artist COLLATE NOCASE, l.title COLLATE NOCASE', crate_id)}
                  for crate_id, name in connection.execute('SELECT id, name FROM crates ORDER BY name COLLATE NOCASE')]
        tree = playlists
        if crates:
            tree = tree + [{'type': 'FOLDER', 'name': 'Crates', 'children': crates}]
        if history:  # newest set first
            tree = tree + [{'type': 'FOLDER', 'name': 'History', 'children': history[::-1]}]
        return by_path, by_filename, tree

    def keys(self):
        """path_keys of every track in the library (loads it first if needed)."""
        self._load()
        return set(self.by_path)

    def find(self, filepath):
        """The record of a file: by its path, else by a unique file name of the same size."""
        self._load()
        exact = self.by_path.get(canonical_path(filepath))
        if exact is not None:
            return exact
        candidates = self.by_filename.get(ntpath.basename(os.path.basename(str(filepath))).casefold(), [])
        if len(candidates) != 1:
            return None
        record = candidates[0]
        try:
            if record['size_kb'] and abs(record['size_kb'] - os.path.getsize(filepath) / 1024) > 2:
                return None
        except OSError:
            return None
        return record
