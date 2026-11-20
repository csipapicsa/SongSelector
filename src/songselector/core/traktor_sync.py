"""Take changes made in a DJ program (Traktor, Mixxx: key, BPM, colour, rating) into the library table.

The app remembers each track's values as each program had them at its last sync ("seen", stored in
library.sqlite per program). A value the program has changed since then replaces the library value, also a
cleared colour or rating. Values the program did not change are left alone, so a rating or key read from the
file's tags is not overwritten by an old value.

Several programs (core/dj_programs.py): the program that *decides* a track (the primary one if it knows the
track, else the next one that does) works as above. Every other program only fills values that are still
empty, so it never overrides the deciding program.

A track the deciding program has not been seen with yet (first sync, new track): its colour is taken from the
program when it has one (as an import does); key, BPM and rating only fill empty values.
"""
from songselector.core.dj_programs import MIXXX, SOURCES, TRAKTOR
from songselector.core.key_formats import parse_bpm, parse_key
from songselector.core.track_colors import normalize
from songselector.core.traktor_collection import canonical_path

TRAKTOR_SOURCE = SOURCES[TRAKTOR]
MIXXX_SOURCE = SOURCES[MIXXX]
BPM_TOLERANCE = 0.005
FIELDS = ('key', 'bpm', 'color', 'rating')


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN: no value


def _colour(value):
    """A stored colour (family number or '#RRGGBB'); 0 for none or anything unreadable."""
    return normalize(value) or 0


def seen_values(record):
    """{'key': 'A minor' or None, 'bpm', 'color' (0 = none; a family number or '#RRGGBB'), 'rating'} of a
    program's record."""
    key = record.get('key')
    return {'key': f'{key[0]} {key[1]}' if key else None, 'bpm': record.get('bpm'),
            'color': _colour(record.get('color')), 'rating': record.get('rating')}


def _same(field, a, b):
    if field == 'bpm' and a is not None and b is not None:
        return abs(a - b) <= BPM_TOLERANCE
    if field == 'rating':
        a, b = _number(a), _number(b)
    if field == 'color':
        a, b = _colour(a), _colour(b)
    return a == b


def _row_value(field, row):
    if field == 'key':
        key = parse_key(f"{row.get('Musical_Key_Base') or ''} {row.get('BaseMinorOrMajor') or ''}")
        return f'{key[0]} {key[1]}' if key else None
    if field == 'bpm':
        return parse_bpm(row.get('BPM'))
    if field == 'color':
        return _colour(row.get('Color'))
    rating = _number(row.get('Rating'))
    return rating if rating else None  # 0: unrated


def _columns(field, value, source):
    if field == 'key':
        base, scale = value.split(' ') if value else (None, None)
        return {'Musical_Key_Base': base, 'BaseMinorOrMajor': scale, 'Key_Source': source}
    if field == 'bpm':
        return {'BPM': value, 'BPM_Source': source}
    if field == 'color':
        return {'Color': value, 'Color_Source': source}
    return {'Rating': value}


def track_changes(row, now, seen=None, source=TRAKTOR_SOURCE, fill_only=False):
    """{column: new value} for one library row (a dict). now: seen_values of the track in the program;
    seen: its values at the program's last sync, or None if it was never seen there. fill_only: the program
    does not decide this track, so it only fills empty values."""
    changes = {}
    for field in FIELDS:
        value, current = now[field], _row_value(field, row)
        if fill_only:
            apply = not current and bool(value)
        elif seen is not None:
            changed_in_program = not _same(field, value, seen.get(field))
            # A program dropping an analysis (key/BPM gone) does not clear the library's value.
            apply = changed_in_program and (value is not None or field in ('color', 'rating'))
        elif field == 'color':
            apply = bool(value)  # its colour, if it has one; no colour there does not clear the tags' colour
        else:
            apply = current is None and value is not None
        if apply and not _same(field, value, current):
            changes.update(_columns(field, value, source))
    return changes


def collection_changes(table, by_path, seen, source=TRAKTOR_SOURCE, decides=None):
    """{row index: {column: new value}} for library rows the program has.
    by_path: canonical path -> record (TraktorCollection.by_path / MixxxLibrary.by_path); seen: path -> seen
    values; decides(path key) -> whether this program decides the track (None: it decides every track)."""
    if table is None or table.empty or 'File_Path' not in table or not by_path:
        return {}
    changes = {}
    for index, row in zip(table.index, table.to_dict('records')):
        key = canonical_path(row.get('File_Path'))
        record = by_path.get(key)
        if record is not None:
            if decides is None or decides(key):
                changed = track_changes(row, seen_values(record), seen.get(key), source)
            else:
                changed = track_changes(row, seen_values(record), source=source, fill_only=True)
            if changed:
                changes[index] = changed
    return changes


def _fits(dtype, value):
    """Whether a pandas column of this dtype takes the value without a type change."""
    if dtype.kind == 'O':  # object column
        return True
    if dtype.kind == 'f':
        return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))
    if dtype.kind in 'iu':
        return isinstance(value, int) and not isinstance(value, bool)
    return False


def apply_changes(table, changes):
    """A copy of the table with the changes written in."""
    result = table.copy()
    for index, changed in changes.items():
        for column, value in changed.items():
            if column not in result:
                result[column] = None
            if not _fits(result[column].dtype, value):
                result[column] = result[column].astype(object)
            result.at[index, column] = value
    return result


def summary(changes):
    """'12 tracks (BPM 3, key 1, colour 8, rating 2)'."""
    counts = {label: sum(column in changed for changed in changes.values())
              for label, column in (('BPM', 'BPM'), ('key', 'Musical_Key_Base'), ('colour', 'Color'),
                                    ('rating', 'Rating'))}
    details = ', '.join(f'{label} {count}' for label, count in counts.items() if count)
    return f"{len(changes)} track{'s' if len(changes) != 1 else ''} ({details})"
