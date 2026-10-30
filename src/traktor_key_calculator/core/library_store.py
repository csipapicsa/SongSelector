"""SQLite store for the app's own track collection and saved track lists.

- collection: every track the app has ever loaded (library CSV rows and imported
  audio files), one row per canonical path. Tracks are never deleted from it.
- lists: ordered track paths per named list, i.e. what each panel showed when it
  was last saved. LIBRARY_LIST is the right-hand library, PLAYLIST_LIST the
  left-hand playlist.
- saved lists: the user's playlists (ordered tracks) and smartlists (Complex
  Search rules, matched live), shown under Playlists in the Browser tab. Names
  are unique ignoring case.

SQLite was chosen over JSON because single-track updates do not rewrite the
whole file, reads and searches are faster, and writes are transactional (a crash
cannot leave a half-written file). It is part of the Python standard library.
"""
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from traktor_key_calculator.core.traktor_collection import canonical_path

SCHEMA_VERSION = 3
LIBRARY_LIST = 'Library'
PLAYLIST_LIST = 'Playlist'
# Kinds of saved list
PLAYLIST = 'playlist'
SMARTLIST = 'smartlist'

# The app's own per-track values (record key -> column). They are written only by
# set_user_fields; upserting track metadata never overwrites them.
USER_COLUMNS = {
    'SS_Rating': 'ss_rating',
    'SS_Color': 'ss_color',
}

# Track fields stored in their own (searchable) columns: record key -> column.
# Any other record field (sources, CSV extras) is kept in the JSON `extra` column.
TRACK_COLUMNS = {
    'File_Path': 'file_path',
    'Artist': 'artist',
    'Title': 'title',
    'Album': 'album',
    'Genre': 'genre',
    'Comment': 'comment',
    'BPM': 'bpm',
    'Musical_Key_Base': 'key_base',
    'BaseMinorOrMajor': 'key_scale',
    'Rating': 'rating',
    'Color': 'color',
    'Imported': 'imported',
    **USER_COLUMNS,
}
_RECORD_COLUMNS = (*TRACK_COLUMNS.values(), 'extra')
_SELECT_TRACKS = 'SELECT ' + ', '.join(_RECORD_COLUMNS) + ' FROM tracks'
_SELECT_LIST = ('SELECT ' + ', '.join('t.' + column for column in _RECORD_COLUMNS) +
                ' FROM list_tracks l JOIN tracks t ON t.path_key = l.path_key'
                ' WHERE l.list_name = ? ORDER BY l.position')
_SELECT_SAVED_LIST = ('SELECT ' + ', '.join('t.' + column for column in _RECORD_COLUMNS) +
                      ' FROM saved_list_tracks l JOIN tracks t ON t.path_key = l.path_key'
                      ' WHERE l.list_name = ? ORDER BY l.position')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tracks (
    path_key   TEXT PRIMARY KEY,   -- canonical_path(file_path): case/separator-insensitive
    file_path  TEXT NOT NULL,
    artist     TEXT,
    title      TEXT,
    album      TEXT,
    genre      TEXT,
    comment    TEXT,
    bpm        REAL,
    key_base   TEXT,
    key_scale  TEXT,
    rating     REAL,
    color      INTEGER,
    imported   INTEGER,
    ss_rating  REAL,               -- schema 2: Song Selector rating 1-5
    ss_color   INTEGER,            -- schema 2: Song Selector color 1-9 (see COLOR_NAMES)
    extra      TEXT NOT NULL DEFAULT '{}',
    added_at   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS list_tracks (
    list_name TEXT NOT NULL,
    position  INTEGER NOT NULL,
    path_key  TEXT NOT NULL REFERENCES tracks(path_key),
    PRIMARY KEY (list_name, position)
);
CREATE TABLE IF NOT EXISTS lists (
    name     TEXT PRIMARY KEY,
    saved_at TEXT NOT NULL
);
-- schema 3: the user's playlists and smartlists
CREATE TABLE IF NOT EXISTS saved_lists (
    name     TEXT PRIMARY KEY COLLATE NOCASE,
    kind     TEXT NOT NULL,             -- 'playlist' or 'smartlist'
    rules    TEXT,                      -- smartlist: Complex Search rows as JSON
    saved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_list_tracks (
    list_name TEXT NOT NULL COLLATE NOCASE,
    position  INTEGER NOT NULL,
    path_key  TEXT NOT NULL REFERENCES tracks(path_key),
    PRIMARY KEY (list_name, position)
);
-- Values of each track as Traktor's collection had them at the last sync (core/traktor_sync.py).
CREATE TABLE IF NOT EXISTS traktor_seen (
    path_key TEXT PRIMARY KEY,
    key      TEXT,
    bpm      REAL,
    color    INTEGER,
    rating   REAL
);
"""


def _plain(value):
    """Convert pandas/numpy values to plain Python values SQLite and JSON accept."""
    if hasattr(value, 'item'):  # numpy scalar
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class LibraryStore:
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.executescript(_SCHEMA)
        self._migrate(connection)
        return connection

    @staticmethod
    def _migrate(connection):
        """Bring an older database up to SCHEMA_VERSION (new databases already are)."""
        row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is not None and row[0] == str(SCHEMA_VERSION):
            return  # up to date: no write (this runs on every connection)
        existing = {row[1] for row in connection.execute('PRAGMA table_info(tracks)')}
        with connection:  # 2 -> 3 only adds tables, which _SCHEMA creates
            for column, kind in (('ss_rating', 'REAL'), ('ss_color', 'INTEGER')):  # 1 -> 2
                if column not in existing:
                    connection.execute(f'ALTER TABLE tracks ADD COLUMN {column} {kind}')
            connection.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    # -- Traktor sync -----------------------------------------------------------

    def traktor_seen(self):
        """{path_key: {'key', 'bpm', 'color', 'rating'}} as Traktor had them at the last sync."""
        with closing(self._connect()) as connection:
            rows = connection.execute('SELECT path_key, key, bpm, color, rating FROM traktor_seen').fetchall()
        return {row[0]: dict(zip(('key', 'bpm', 'color', 'rating'), row[1:])) for row in rows}

    def save_traktor_seen(self, values):
        """Store {path_key: values} (the whole collection, in one transaction)."""
        with closing(self._connect()) as connection, connection:
            connection.executemany('INSERT OR REPLACE INTO traktor_seen VALUES (?, ?, ?, ?, ?)',
                                   [(key, value['key'], value['bpm'], value['color'], value['rating'])
                                    for key, value in values.items()])

    # -- collection -----------------------------------------------------------

    def upsert_tracks(self, records):
        """Insert or update tracks by path. Returns the number of tracks written.

        A path has exactly one record. If the same path occurs more than once in
        `records`, the first occurrence is stored (as in drop_duplicate_paths).
        """
        now = _now()
        rows = []
        seen = set()
        for record in records:
            record = {name: _plain(value) for name, value in record.items()}
            key = canonical_path(record.get('File_Path'))
            if not key or key in seen:
                continue
            seen.add(key)
            columns = [record.get(name) for name in TRACK_COLUMNS]
            extra = {name: value for name, value in record.items() if name not in TRACK_COLUMNS}
            rows.append((key, *columns, json.dumps(extra, ensure_ascii=False), now, now))
        names = ', '.join(TRACK_COLUMNS.values())
        placeholders = ', '.join('?' * (len(TRACK_COLUMNS) + 4))
        updates = ', '.join(f'{column}=excluded.{column}' for column in TRACK_COLUMNS.values()
                            if column not in USER_COLUMNS.values())
        sql = (f'INSERT INTO tracks (path_key, {names}, extra, added_at, updated_at) VALUES ({placeholders}) '
               f'ON CONFLICT(path_key) DO UPDATE SET {updates}, extra=excluded.extra, updated_at=excluded.updated_at')
        with closing(self._connect()) as connection, connection:
            connection.executemany(sql, rows)
        return len(rows)

    def set_user_fields(self, records, **fields):
        """Set Song Selector fields, e.g. SS_Rating=4 or SS_Color=None (clears), for tracks.

        The tracks are stored first if they are not in the collection yet.
        """
        unknown = set(fields) - set(USER_COLUMNS)
        if unknown:
            raise ValueError(f'Not a Song Selector field: {", ".join(sorted(unknown))}')
        records = list(records)
        self.upsert_tracks(records)
        assignments = ', '.join(f'{USER_COLUMNS[name]} = ?' for name in fields)
        keys = [canonical_path(record.get('File_Path')) for record in records]
        values = [_plain(value) for value in fields.values()]
        with closing(self._connect()) as connection, connection:
            connection.executemany(f'UPDATE tracks SET {assignments}, updated_at = ? WHERE path_key = ?',
                                   [(*values, _now(), key) for key in keys if key])

    def user_fields(self):
        """Song Selector fields of every track that has at least one, by canonical path."""
        columns = ', '.join(USER_COLUMNS.values())
        condition = ' OR '.join(f'{column} IS NOT NULL' for column in USER_COLUMNS.values())
        with closing(self._connect()) as connection:
            rows = connection.execute(f'SELECT path_key, {columns} FROM tracks WHERE {condition}').fetchall()
        return {row[0]: dict(zip(USER_COLUMNS, row[1:])) for row in rows}

    def track_count(self):
        with closing(self._connect()) as connection:
            return connection.execute('SELECT COUNT(*) FROM tracks').fetchone()[0]

    def tracks(self, keys):
        """Records of these canonical paths that are in the collection, by path."""
        keys = list(keys)
        records = {}
        with closing(self._connect()) as connection:
            for start in range(0, len(keys), 500):  # SQLite limits the number of parameters
                chunk = keys[start:start + 500]
                rows = connection.execute(_SELECT_TRACKS + f' WHERE path_key IN ({", ".join("?" * len(chunk))})',
                                          chunk).fetchall()
                records.update((canonical_path(record['File_Path']), record) for record in map(self._record, rows))
        return records

    def imported_tracks(self):
        """Tracks added by drag and drop or file picker, keyed by canonical path."""
        with closing(self._connect()) as connection:
            rows = connection.execute(_SELECT_TRACKS + ' WHERE imported = 1').fetchall()
        return {canonical_path(record['File_Path']): record for record in map(self._record, rows)}

    # -- lists ----------------------------------------------------------------

    def save_list(self, name, records):
        """Save the list's tracks in order; also stores the tracks themselves."""
        records = list(records)
        self.upsert_tracks(records)
        keys = [canonical_path(record.get('File_Path')) for record in records]
        with closing(self._connect()) as connection, connection:
            connection.execute('DELETE FROM list_tracks WHERE list_name = ?', (name,))
            connection.executemany('INSERT INTO list_tracks VALUES (?, ?, ?)',
                                   [(name, position, key) for position, key in enumerate(keys) if key])
            connection.execute('INSERT OR REPLACE INTO lists VALUES (?, ?)', (name, _now()))

    def load_list(self, name):
        """Records of a saved list in order, or None if the list was never saved."""
        with closing(self._connect()) as connection:
            if connection.execute('SELECT 1 FROM lists WHERE name = ?', (name,)).fetchone() is None:
                return None
            rows = connection.execute(_SELECT_LIST, (name,)).fetchall()
        return [self._record(row) for row in rows]

    # -- saved playlists and smartlists ----------------------------------------

    def saved_lists(self):
        """[(name, kind)] of the user's playlists and smartlists, by name."""
        with closing(self._connect()) as connection:
            return connection.execute('SELECT name, kind FROM saved_lists ORDER BY name COLLATE NOCASE').fetchall()

    def saved_list(self, name):
        """{'name', 'kind', 'rules'} (rules: smartlist rows, else None), or None if there is no such list."""
        with closing(self._connect()) as connection:
            row = connection.execute('SELECT name, kind, rules FROM saved_lists WHERE name = ?', (name,)).fetchone()
        if row is None:
            return None
        return {'name': row[0], 'kind': row[1], 'rules': json.loads(row[2]) if row[2] else None}

    def save_playlist(self, name, records):
        """Create or replace a playlist with these tracks, in order (a track at most once)."""
        records = list(records)
        self.upsert_tracks(records)
        keys = list(dict.fromkeys(key for key in (canonical_path(record.get('File_Path')) for record in records) if key))
        with closing(self._connect()) as connection, connection:
            self._replace_list(connection, name, PLAYLIST, None)
            connection.executemany('INSERT INTO saved_list_tracks VALUES (?, ?, ?)',
                                   [(name, position, key) for position, key in enumerate(keys)])

    def add_to_playlist(self, name, records):
        """Append tracks that are not on the playlist yet; returns how many were added."""
        records = list(records)
        self.upsert_tracks(records)
        present = set(self.playlist_keys(name))
        keys = [key for key in dict.fromkeys(canonical_path(record.get('File_Path')) for record in records)
                if key and key not in present]
        with closing(self._connect()) as connection, connection:
            start = connection.execute('SELECT COALESCE(MAX(position) + 1, 0) FROM saved_list_tracks '
                                       'WHERE list_name = ?', (name,)).fetchone()[0]
            connection.executemany('INSERT INTO saved_list_tracks VALUES (?, ?, ?)',
                                   [(name, start + offset, key) for offset, key in enumerate(keys)])
        return len(keys)

    def playlist_keys(self, name):
        """Canonical paths of a playlist's tracks, in order."""
        with closing(self._connect()) as connection:
            rows = connection.execute('SELECT path_key FROM saved_list_tracks WHERE list_name = ? '
                                      'ORDER BY position', (name,)).fetchall()
        return [row[0] for row in rows]

    def load_playlist(self, name):
        """Records of a playlist's tracks, in order."""
        with closing(self._connect()) as connection:
            rows = connection.execute(_SELECT_SAVED_LIST, (name,)).fetchall()
        return [self._record(row) for row in rows]

    def save_smartlist(self, name, rules):
        """Create or replace a smartlist: Complex Search rows ({'column', 'condition', 'value'})."""
        with closing(self._connect()) as connection, connection:
            self._replace_list(connection, name, SMARTLIST, json.dumps(list(rules), ensure_ascii=False))

    def rename_saved_list(self, old, new):
        with closing(self._connect()) as connection, connection:
            connection.execute('UPDATE saved_lists SET name = ?, saved_at = ? WHERE name = ?', (new, _now(), old))
            connection.execute('UPDATE saved_list_tracks SET list_name = ? WHERE list_name = ?', (new, old))

    def delete_saved_list(self, name):
        with closing(self._connect()) as connection, connection:
            connection.execute('DELETE FROM saved_list_tracks WHERE list_name = ?', (name,))
            connection.execute('DELETE FROM saved_lists WHERE name = ?', (name,))

    @staticmethod
    def _replace_list(connection, name, kind, rules):
        connection.execute('DELETE FROM saved_list_tracks WHERE list_name = ?', (name,))
        connection.execute('DELETE FROM saved_lists WHERE name = ?', (name,))
        connection.execute('INSERT INTO saved_lists VALUES (?, ?, ?, ?)', (name, kind, rules, _now()))

    @staticmethod
    def _record(row):
        record = dict(zip(TRACK_COLUMNS, row[:-1]))
        record.update(json.loads(row[-1]))
        if record.get('Imported') is not None:
            record['Imported'] = bool(record['Imported'])
        return record
