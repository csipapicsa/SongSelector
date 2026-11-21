"""Turn dropped files into library rows; keep user imports in this app's own data."""
import json
import os
import tempfile
import warnings
from pathlib import Path

import pandas as pd

from songselector.config import AUDIO_EXTENSIONS
from songselector.core.audio_metadata import extract_audio_metadata
from songselector.core.dj_programs import MIXXX, SOURCES, TRAKTOR, priority
from songselector.core.key_formats import parse_bpm, parse_key
from songselector.core.mixxx_library import MixxxLibrary
from songselector.core.track_colors import normalize
from songselector.core.traktor_collection import TraktorCollection, canonical_path


class TrackImporter:
    """Reads an audio file's tags and fills them in from the DJ programs' libraries (Traktor's collection,
    Mixxx's library), the primary program first (core/dj_programs.py)."""

    def __init__(self, collection_path='', mixxx_path='', primary=TRAKTOR):
        self.collection = TraktorCollection(collection_path)
        self.mixxx = MixxxLibrary(mixxx_path)
        self.primary = primary

    def library(self, program):
        return {TRAKTOR: self.collection, MIXXX: self.mixxx}[program]

    def sources(self):
        """[(program, library)] in priority order: the primary program first."""
        return [(program, self.library(program)) for program in priority(self.primary)]

    def libraries(self):
        return [library for _program, library in self.sources()]

    def read(self, path, existing=None):
        path = Path(path).resolve()
        if not path.is_file() or path.suffix.lower().lstrip('.') not in AUDIO_EXTENSIONS:
            raise ValueError(f'Unsupported or missing audio file: {path}')
        tags = extract_audio_metadata(path)
        # The track's records in the programs that have it, the primary program first.
        found = [(SOURCES[program], record) for program, library in self.sources()
                 for record in (library.find(path),) if record]
        existing = {} if existing is None else existing

        def available(value):
            return value is not None and not pd.isna(value) and str(value).strip().lower() not in ('', 'none', 'nan')

        def first(name):
            """(source, value) of the first program that has a value for this field, else (None, None)."""
            return next(((source, record[name]) for source, record in found if record.get(name) is not None),
                        (None, None))

        previous_source = 'Saved import' if available(existing.get('Imported')) and existing.get('Imported') else 'Loaded CSV'
        key = parse_key(tags.key)
        key_source = 'File tags' if key else ''
        if key is None:
            source, key = first('key')
            key_source = source if key else key_source
        if key is None:
            key = parse_key(f"{existing.get('Musical_Key_Base', '')} {existing.get('BaseMinorOrMajor', '')}")
            if key:
                key_source = previous_source
        bpm = parse_bpm(tags.bpm)
        bpm_source = 'File tags' if bpm is not None else ''
        source, analyzed_bpm = first('bpm')
        if analyzed_bpm is not None and (bpm is None or abs(bpm - round(analyzed_bpm)) < 0.000001):
            bpm = analyzed_bpm
            bpm_source = source
        if bpm is None:
            bpm = parse_bpm(existing.get('BPM'))
            if bpm is not None:
                bpm_source = previous_source

        fields = {'artist': 'Artist', 'title': 'Title', 'album': 'Album', 'rating': 'Rating',
                  'genre': 'Genre', 'comment': 'Comment'}
        def field(name):
            values = [getattr(tags, name, None), *(record.get(name) for _source, record in found),
                      existing.get(fields[name])]
            return next((value for value in values if available(value)), None)

        # A program's colour wins over the tags'. A collection value of zero is an explicit cleared color,
        # not missing metadata.
        color_source, color_value = first('color')
        color_source = color_source or ''
        if color_value is None and available(tags.color):
            color_value = tags.color
            color_source = 'File tags'
        elif color_value is None and available(existing.get('Color')):
            color_value = existing['Color']
            color_source = previous_source
        color = normalize(color_value) or 0  # a family number or a program's exact '#RRGGBB'
        return {'Artist': field('artist') or '', 'Title': field('title') or path.stem,
                'Album': field('album') or '', 'Rating': field('rating'),
                'File_Path': str(path), 'BPM': bpm,
                'Musical_Key_Base': key[0] if key else None,
                'BaseMinorOrMajor': key[1] if key else None,
                'Genre': field('genre') or '', 'Comment': field('comment') or '', 'Color': color,
                'Key_Source': key_source, 'BPM_Source': bpm_source, 'Color_Source': color_source,
                'Metadata_Error': tags.error or '', 'Imported': True}


def merge_tracks(table, records):
    result = table.copy() if table is not None else pd.DataFrame()
    indexes = {}
    if 'File_Path' in result:
        indexes = {canonical_path(path): index for index, path in result['File_Path'].items()
                   if canonical_path(path)}
    new_records = []
    for record in records:
        key = canonical_path(record.get('File_Path'))
        if not key:
            continue
        if key in indexes:
            for name, value in record.items():
                if name not in result:
                    result[name] = None
                result.at[indexes[key], name] = value
        else:
            new_records.append(record)
    if new_records:
        # Keep one row per normalized path in a batch, including paths differing only in case.
        unique = {canonical_path(row['File_Path']): row for row in new_records}
        with warnings.catch_warnings():
            # pandas will change how all-empty columns (e.g. untagged WAV/FLAC files) affect
            # the merged column types. Either way works here: every value is read through
            # parse_key/parse_bpm/_text, never by its pandas dtype.
            warnings.filterwarnings('ignore', category=FutureWarning, message='.*empty or all-NA.*')
            result = pd.concat([result, pd.DataFrame(unique.values())], ignore_index=True)
    return result


def drop_duplicate_paths(table):
    """Remove rows whose file path repeats an earlier row; returns (table, removed count).

    Paths are compared with canonical_path, so case and slash differences count as
    the same file (as on Windows). The first occurrence is kept.
    """
    if table is None or table.empty or 'File_Path' not in table:
        return table, 0
    keys = table['File_Path'].map(canonical_path)
    duplicated = keys.duplicated() & (keys != '')
    return table.loc[~duplicated].reset_index(drop=True), int(duplicated.sum())


def enrich_ratings(table, *collections):
    """Fill absent CSV ratings from exact collection paths without reading audio files; with several
    collections (DJ programs, the primary one first) the first that has a rating gives it."""
    result = table.copy()
    if 'Rating' not in result:
        result['Rating'] = None
    if result.empty or 'File_Path' not in result:
        return result
    missing = result['Rating'].isna() | result['Rating'].astype(str).str.strip().str.lower().isin(('', 'none', 'nan'))
    if not missing.any():
        return result
    for collection in collections:
        collection._load()
    collections = [collection for collection in collections if collection.by_path]
    if not collections:
        return result

    def rating(path):
        key = canonical_path(path)
        return next((value for value in (collection.by_path.get(key, {}).get('rating') for collection in collections)
                     if value is not None), None)

    ratings = result.loc[missing, 'File_Path'].map(rating)
    # Only exact paths match: identically named songs must never receive another song's rating.
    # Numeric (NaN for unrated) so it also fits a float Rating column loaded from the store.
    result.loc[missing, 'Rating'] = pd.to_numeric(ratings, errors='coerce')
    return result


class ImportedTrackStore:
    def __init__(self, path):
        self.path = Path(path)
        self.error = ''

    def load(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, list):
                raise ValueError('Expected a list of imported tracks')
            return {canonical_path(row['File_Path']): row for row in data
                    if isinstance(row, dict) and isinstance(row.get('File_Path'), str)}
        except (OSError, ValueError) as error:
            self.error = f'Cannot load saved imports: {error}'
            return {}

    def save(self, records):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='imports_', suffix='.tmp', delete=False) as handle:
                temporary_path = Path(handle.name)
                json.dump(list(records.values()), handle, ensure_ascii=False, indent=2, allow_nan=False)
            os.replace(temporary_path, self.path)
            self.error = ''
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
