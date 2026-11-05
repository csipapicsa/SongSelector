"""Take changes made in Traktor (key, BPM, colour, rating) into the library table.

The app remembers each track's values as Traktor had them at the last sync ("seen",
stored in library.sqlite). A value Traktor has changed since then replaces the library
value, also a cleared colour or rating. Values Traktor did not change are left alone,
so a rating or key read from the file's tags is not overwritten by an old Traktor value.

A track Traktor has not been seen with yet (first sync, new track): its colour is taken
from Traktor (as an import does); key, BPM and rating only fill empty values.
"""
from traktor_key_calculator.core.key_formats import parse_bpm, parse_key
from traktor_key_calculator.core.traktor_collection import canonical_path

TRAKTOR_SOURCE = 'Traktor collection'
BPM_TOLERANCE = 0.005
FIELDS = ('key', 'bpm', 'color', 'rating')


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN: no value


def seen_values(record):
    """{'key': 'A minor' or None, 'bpm', 'color' (0 = none), 'rating'} of a collection record."""
    key = record.get('key')
    colour = _number(record.get('color'))
    return {'key': f'{key[0]} {key[1]}' if key else None, 'bpm': record.get('bpm'),
            'color': int(colour) if colour is not None else 0, 'rating': record.get('rating')}


def _same(field, a, b):
    if field == 'bpm' and a is not None and b is not None:
        return abs(a - b) <= BPM_TOLERANCE
    if field == 'rating':
        a, b = _number(a), _number(b)
    return a == b


def _row_value(field, row):
    if field == 'key':
        key = parse_key(f"{row.get('Musical_Key_Base') or ''} {row.get('BaseMinorOrMajor') or ''}")
        return f'{key[0]} {key[1]}' if key else None
    if field == 'bpm':
        return parse_bpm(row.get('BPM'))
    if field == 'color':
        return int(_number(row.get('Color')) or 0)
    rating = _number(row.get('Rating'))
    return rating if rating else None  # 0: unrated


def _columns(field, value):
    if field == 'key':
        base, scale = value.split(' ') if value else (None, None)
        return {'Musical_Key_Base': base, 'BaseMinorOrMajor': scale, 'Key_Source': TRAKTOR_SOURCE}
    if field == 'bpm':
        return {'BPM': value, 'BPM_Source': TRAKTOR_SOURCE}
    if field == 'color':
        return {'Color': value, 'Color_Source': TRAKTOR_SOURCE}
    return {'Rating': value}


def track_changes(row, now, seen=None):
    """{column: new value} for one library row (a dict). now: seen_values of the track in
    the collection; seen: its values at the last sync, or None if it was never seen."""
    changes = {}
    for field in FIELDS:
        value, current = now[field], _row_value(field, row)
        if seen is not None:
            changed_in_traktor = not _same(field, value, seen.get(field))
            # Traktor dropping an analysis (key/BPM gone) does not clear the library's value.
            apply = changed_in_traktor and (value is not None or field in ('color', 'rating'))
        elif field == 'color':
            apply = True
        else:
            apply = current is None and value is not None
        if apply and not _same(field, value, current):
            changes.update(_columns(field, value))
    return changes


def collection_changes(table, by_path, seen):
    """{row index: {column: new value}} for library rows in the collection.
    by_path: canonical path -> record (TraktorCollection.by_path); seen: path -> seen values."""
    if table is None or table.empty or 'File_Path' not in table or not by_path:
        return {}
    changes = {}
    for index, row in zip(table.index, table.to_dict('records')):
        key = canonical_path(row.get('File_Path'))
        record = by_path.get(key)
        if record is not None:
            changed = track_changes(row, seen_values(record), seen.get(key))
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
