"""Read-only access to Rekordbox's playlists, read straight from its library (master.db).

Rekordbox 6 and 7 keep their library in an SQLCipher database. Its key is not secret: it is
the same on every machine and is published by the MIT-licensed pyrekordbox project
(https://github.com/dylanljones/pyrekordbox), from which the obfuscated key below is taken.
Only playlists are read: their folders, their order, and the file of every track. Nothing is
written, Rekordbox does not have to be started or touched, and it may be running: the
database is copied to a temporary folder first and the copy is read.

`RekordboxLibrary` has the shape of `TraktorCollection` (`path`, `error`, `playlists`, `_load()`),
so the same background watcher and the same Browser code serve both.
"""
import base64
import ntpath
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

_OBFUSCATED_KEY = b"PN_Pq^*N>(JYe*u^8;Yg76HuZ<mR13S?=>)b9;DpoTXV(6ItkU`}8*m6tx_I{Solh_N#dfe{v="
_XOR = b'657f48f84c437cc1'

# djmdPlaylist.Attribute
PLAYLIST, FOLDER, SMARTLIST = 0, 1, 4
_LOCAL_FILE = re.compile(r'^([A-Za-z]:[\\/]|\\\\|//)')  # not a streaming service's track id


def database_key():
    data = bytes(b ^ _XOR[i % len(_XOR)] for i, b in enumerate(base64.b85decode(_OBFUSCATED_KEY)))
    return zlib.decompress(data).decode('utf-8')


def discover_library():
    """Path of Rekordbox's master.db: the one named in its settings, else the standard place;
    the most recently written if there are several. '' if Rekordbox has none."""
    override = os.environ.get('TRAKTOR_REKORDBOX_LIBRARY')
    if override is not None:  # tests and unusual installs; 'none' or '' switches Rekordbox off
        return '' if override.lower() in ('', 'none') else override
    candidates = []
    appdata = os.environ.get('APPDATA')
    if not appdata:
        return ''
    pioneer = Path(appdata) / 'Pioneer'
    for folder in (pioneer / 'rekordbox6', pioneer / 'rekordbox'):
        try:
            for value in ET.parse(folder / 'rekordbox3.settings').getroot().findall('VALUE'):
                if value.get('name') == 'masterDbDirectory' and value.get('val'):
                    candidates.append(Path(value.get('val')) / 'master.db')
        except (OSError, ET.ParseError):
            pass
    candidates.append(pioneer / 'rekordbox' / 'master.db')
    existing = [path for path in candidates if path.is_file()]
    return str(max(existing, key=lambda path: path.stat().st_mtime)) if existing else ''


def signature(path):
    """What changed-or-not is decided by: size and modification time of the database and of its
    write-ahead log, if there is one. None if the database is not there."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    try:
        log = os.stat(path + '-wal')
        log = (log.st_mtime_ns, log.st_size)
    except OSError:
        log = None
    return stat.st_mtime_ns, stat.st_size, log


def _local_path(text):
    """Windows path of a track, '' for tracks that are not local files (streaming, cloud)."""
    text = (text or '').strip()
    return ntpath.normpath(text.replace('/', '\\')) if _LOCAL_FILE.match(text) else ''


def _tree(playlists, songs):
    """[{'type': 'FOLDER', 'name', 'children'}, {'type': 'PLAYLIST', 'name', 'tracks'},
    {'type': 'SMARTLIST', 'name', 'query'}] in Rekordbox's order; `playlists` are
    (id, seq, name, attribute, parent id, smart-list definition) rows."""
    children = {}
    for row in playlists:
        children.setdefault(row[4], []).append(row)

    def build(parent, seen):
        entries = []
        for identifier, _seq, name, attribute, _parent, smart in sorted(children.get(parent, []), key=lambda r: r[1] or 0):
            if identifier in seen:  # a corrupt cycle
                continue
            if attribute == FOLDER:
                entries.append({'type': 'FOLDER', 'name': name or '', 'children': build(identifier, seen | {identifier})})
            elif attribute == SMARTLIST:
                entries.append({'type': 'SMARTLIST', 'name': name or '', 'query': smart or ''})
            else:
                entries.append({'type': 'PLAYLIST', 'name': name or '', 'tracks': songs.get(identifier, [])})
        return entries

    return build('root', frozenset())


class RekordboxLibrary:
    def __init__(self, path=''):
        self.path = str(path or '')
        self.error = ''
        self.playlists = []   # same shape as TraktorCollection.playlists
        self.track_count = 0  # tracks in the Rekordbox library (not only those on playlists)
        self._signature = None

    def _load(self):
        if not self.path:
            return
        signature_now = signature(self.path)
        if signature_now is None:
            self.error = f'Cannot read the Rekordbox library: {self.path} does not exist'
            return
        if signature_now == self._signature:
            return
        try:
            self.playlists, self.track_count = self._read()
            self._signature = signature_now
            self.error = ''
        except Exception as error:  # files, a missing package, sqlcipher3's own errors: one message
            # The last valid playlists stay: Rekordbox may be rewriting the file right now.
            self.error = f'Cannot read the Rekordbox library: {error}'

    def _read(self):
        try:
            from sqlcipher3 import dbapi2 as sqlcipher
        except ImportError as error:
            raise ImportError('the sqlcipher3 package is missing') from error
        copy = tempfile.mkdtemp(prefix='songselector-rekordbox-')
        try:
            target = os.path.join(copy, 'master.db')
            shutil.copyfile(self.path, target)
            if os.path.isfile(self.path + '-wal'):
                shutil.copyfile(self.path + '-wal', target + '-wal')
            connection = sqlcipher.connect(target)
            try:
                connection.execute(f"PRAGMA key='{database_key()}'")
                playlists = connection.execute(
                    'SELECT ID, Seq, Name, Attribute, ParentID, SmartList FROM djmdPlaylist '
                    'WHERE COALESCE(rb_local_deleted, 0) = 0').fetchall()
                rows = connection.execute(
                    'SELECT sp.PlaylistID, c.FolderPath FROM djmdSongPlaylist sp JOIN djmdContent c ON c.ID = sp.ContentID '
                    'WHERE COALESCE(sp.rb_local_deleted, 0) = 0 AND COALESCE(c.rb_local_deleted, 0) = 0 '
                    'ORDER BY sp.PlaylistID, sp.TrackNo').fetchall()
                count = connection.execute('SELECT COUNT(*) FROM djmdContent WHERE COALESCE(rb_local_deleted, 0) = 0').fetchone()[0]
            finally:
                connection.close()
        finally:
            shutil.rmtree(copy, ignore_errors=True)
        songs = {}
        for playlist, folder_path in rows:
            path = _local_path(folder_path)
            if path:
                songs.setdefault(playlist, []).append(path)
        return _tree(playlists, songs), count
