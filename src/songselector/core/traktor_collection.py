"""Read-only, cached access to Traktor's NML collection."""
import ntpath
import os
import posixpath
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from songselector.core.key_formats import nml_key, parse_bpm, parse_key

_WINDOWS_PATH = re.compile(r'^(?:[A-Za-z]:|\\\\)')   # a drive letter, or a network share (\\server\...)


def canonical_path(path):
    r"""The key a track is known by (library, embeddings, map, playlists): one per file, however its path is spelt.

    Windows paths are case-insensitive and take either slash, so they become lower case with backslashes
    ('E:/DJ/A.mp3' -> 'e:\dj\a.mp3'); on any system, as they also come from Traktor's or Rekordbox's files. Other
    paths (Linux) are only normalised: there 'A.mp3' and 'a.mp3' are two files. Until 1.3 every path was folded the
    Windows way, also on Linux, where nobody used the app yet."""
    if path is None:
        return ''
    text = str(path).strip()
    if not text or text.lower() == 'nan':
        return ''
    if sys.platform == 'win32' or _WINDOWS_PATH.match(text):
        return ntpath.normcase(ntpath.normpath(text))
    return posixpath.normpath(text)


def nml_track_path(key):
    r"""Path of a playlist entry's PRIMARYKEY, e.g. 'E:/:DJ/:Break/:a.mp3' -> 'E:\DJ\Break\a.mp3'."""
    return ntpath.normpath(key.replace('/:', '\\')) if key else ''


def discover_collection():
    candidates = [Path(r'E:\DJ\TRAKTOR\collection.nml')]
    home = Path.home()
    for documents in (home / 'Documents', home / 'OneDrive' / 'Documents', home / 'OneDrive' / 'Dokumentumok'):
        parent = documents / 'Native Instruments'
        if parent.is_dir():
            candidates.extend(parent.glob('Traktor*/collection.nml'))
    existing = [path for path in candidates if path.is_file()]
    return str(max(existing, key=lambda path: path.stat().st_mtime)) if existing else ''


class TraktorCollection:
    def __init__(self, path=''):
        self.path = str(path or '')
        self.error = ''
        self.by_path = {}
        self.by_filename = {}
        # Traktor's playlist tree, in Traktor's order: [{'type': 'FOLDER', 'name', 'children'},
        # {'type': 'PLAYLIST', 'name', 'tracks': [path, ...]}, {'type': 'SMARTLIST', 'name', 'query'}]
        self.playlists = []
        self._signature = None

    def _load(self):
        if not self.path:
            return
        try:
            stat = Path(self.path).stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if signature == self._signature:
                return
            paths, names = {}, {}
            root = {'type': 'FOLDER', 'name': '', 'children': []}
            nodes = [root]  # PLAYLISTS NODE elements open at this point of the file
            for event, entry in ET.iterparse(self.path, events=('start', 'end')):
                if entry.tag == 'NODE':
                    if event == 'start':
                        kind = entry.get('TYPE', '')
                        node = {'type': kind, 'name': entry.get('NAME', '')}
                        node.update({'FOLDER': {'children': []}, 'PLAYLIST': {'tracks': []},
                                     'SMARTLIST': {'query': ''}}.get(kind, {}))
                        nodes[-1].setdefault('children', []).append(node)
                        nodes.append(node)
                    else:
                        nodes.pop()
                    continue
                if event != 'end':
                    continue
                if entry.tag == 'SEARCH_EXPRESSION':
                    nodes[-1]['query'] = entry.get('QUERY', '')
                    continue
                if entry.tag != 'ENTRY':
                    continue
                location = entry.find('LOCATION')
                if location is None:
                    key = entry.find('PRIMARYKEY')
                    if key is not None and 'tracks' in nodes[-1]:  # a playlist entry
                        nodes[-1]['tracks'].append(nml_track_path(key.get('KEY')))
                    entry.clear()
                    continue
                filename = location.get('FILE', '')
                directory = location.get('DIR', '').replace('/:', '/').replace('/', '\\')
                volume = location.get('VOLUME', '')
                if len(volume) == 1 and volume.isalpha():
                    volume += ':'
                path = ntpath.normpath(volume + directory + filename)
                info = entry.find('INFO')
                info = info.attrib if info is not None else {}
                tempo = entry.find('TEMPO')
                musical = entry.find('MUSICAL_KEY')
                parsed_key = nml_key(musical.get('VALUE')) if musical is not None else None
                if parsed_key is None:
                    parsed_key = parse_key(info.get('KEY'))
                album = entry.find('ALBUM')
                record = {'path': path, 'artist': entry.get('ARTIST'), 'title': entry.get('TITLE'),
                          'album': album.get('TITLE') if album is not None else None,
                          'genre': info.get('GENRE'), 'comment': info.get('COMMENT'),
                          'bpm': parse_bpm(tempo.get('BPM')) if tempo is not None else None,
                          'key': parsed_key, 'color': info.get('COLOR'),
                          'rating': self._ranking(info.get('RANKING')), 'size_kb': info.get('FILESIZE'),
                          # for Traktor smartlists (core.traktor_smartlist)
                          'playcount': info.get('PLAYCOUNT'), 'playtime': info.get('PLAYTIME'),
                          'import_date': info.get('IMPORT_DATE'), 'label': info.get('LABEL'),
                          'remixer': info.get('REMIXER')}
                paths[canonical_path(path)] = record
                names.setdefault(filename.casefold(), []).append(record)
                entry.clear()
            self.by_path, self.by_filename = paths, names
            # Traktor's tree has one '$ROOT' folder; its contents are the playlists
            top = root['children']
            self.playlists = top[0].get('children', []) if len(top) == 1 and top[0]['type'] == 'FOLDER' else top
            self._signature = signature
            self.error = ''
        except (OSError, ET.ParseError) as error:
            self.error = f'Cannot read Traktor collection: {error}'
            # Retain the last valid index if Traktor is currently rewriting the NML.

    @staticmethod
    def _ranking(value):
        try:
            number = int(value)
            return min(5, max(1, round(number / 51))) if number > 0 else None
        except (TypeError, ValueError):
            return None

    def keys(self):
        """path_keys of every track in the collection (loads it first if needed)."""
        self._load()
        return set(self.by_path)

    def find(self, filepath):
        self._load()
        exact = self.by_path.get(canonical_path(filepath))
        if exact is not None:
            return exact
        candidates = self.by_filename.get(ntpath.basename(str(filepath)).casefold(), [])
        if len(candidates) != 1:
            return None
        record = candidates[0]
        try:
            if record['size_kb'] and abs(int(record['size_kb']) - os.path.getsize(filepath) / 1024) > 2:
                return None
        except (OSError, ValueError):
            return None
        return record
