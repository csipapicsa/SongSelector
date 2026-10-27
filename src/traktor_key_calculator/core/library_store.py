"""SQLite store for the app's own track collection and saved track lists.

- collection: every track the app has ever loaded (library CSV rows and imported
  audio files), one row per canonical path. Tracks are never deleted from it.
- lists: ordered track paths per named list, i.e. what each panel showed when it
  was last saved. LIBRARY_LIST is the right-hand library, PLAYLIST_LIST the
  left-hand playlist.

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

SCHEMA_VERSION = 2
LIBRARY_LIST = 'Library'
PLAYLIST_LIST = 'Playlist'

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
        existing = {row[1] for row in connection.execute('PRAGMA table_info(tracks)')}
        with connection:
            for column, kind in (('ss_rating', 'REAL'), ('ss_color', 'INTEGER')):  # 1 -> 2
                if column not in existing:
                    connection.execute(f'ALTER TABLE tracks ADD COLUMN {column} {kind}')
            connection.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

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

    @staticmethod
    def _record(row):
        record = dict(zip(TRACK_COLUMNS, row[:-1]))
        record.update(json.loads(row[-1]))
        if record.get('Imported') is not None:
            record['Imported'] = bool(record['Imported'])
        return record
