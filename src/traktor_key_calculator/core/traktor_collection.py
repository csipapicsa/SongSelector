"""Read-only, cached access to Traktor's NML collection."""
import ntpath
import os
from pathlib import Path
from xml.etree import ElementTree as ET
from traktor_key_calculator.core.key_formats import nml_key, parse_key, parse_bpm


def canonical_path(path):
    if path is None:
        return ''
    text = str(path).strip()
    if not text or text.lower() == 'nan':
        return ''
    return ntpath.normcase(ntpath.normpath(text))


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
            for event, entry in ET.iterparse(self.path, events=('end',)):
                if entry.tag != 'ENTRY':
                    continue
                location = entry.find('LOCATION')
                if location is None:
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
                          'rating': self._ranking(info.get('RANKING')), 'size_kb': info.get('FILESIZE')}
                paths[canonical_path(path)] = record
                names.setdefault(filename.casefold(), []).append(record)
                entry.clear()
            self.by_path, self.by_filename = paths, names
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
