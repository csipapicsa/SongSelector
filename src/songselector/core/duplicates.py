"""Duplicate rows in the library list, three ways, and which row of each group stays.

- PATH: the same file path (case and slashes ignored), e.g. a CSV that lists a file twice.
- ARTIST_TITLE: the same artist and title (case and spaces ignored), e.g. the same track bought twice.
- SAME_FILE: the same content: same size, then the same SHA-256, e.g. a copy in another folder.

Which row stays (the user's rule, 2026-11-17): 1) its file still exists, 2) the richest row (most filled-in
fields: comment, colour, rating, key, BPM...), 3) on a tie the one in the Traktor / Rekordbox collection, 4) the
first. Only list rows are removed; files on disk are never touched.

Plain data, no Qt: the window shows the plan and removes the rows the user confirms.
"""
import hashlib
import os
import re
from dataclasses import dataclass, field

from songselector.core.traktor_collection import canonical_path

PATH, ARTIST_TITLE, SAME_FILE = 'path', 'artist_title', 'same_file'
MODES = {PATH: 'Same file path', ARTIST_TITLE: 'Same Artist - Title', SAME_FILE: 'Same file (copies in other folders)'}

# Fields that make a row "richer"; a value counts when it is filled in (colour / rating 0 mean none).
RICH_FIELDS = ('Artist', 'Title', 'Album', 'Genre', 'Comment', 'BPM', 'Musical_Key_Base', 'Rating', 'Color',
               'SS_Rating', 'SS_Color')
_ZERO_IS_EMPTY = {'Rating', 'Color', 'SS_Rating', 'SS_Color'}


@dataclass
class Group:
    keep: int                                     # row index (table.index) that stays
    remove: list = field(default_factory=list)    # row indexes to remove
    reasons: dict = field(default_factory=dict)   # row index -> why it ranks where it does, for the preview


def filled(value, name=''):
    """A field counts as filled in: not None / NaN / empty, and not 0 for colours and ratings."""
    if value is None:
        return False
    try:
        if value != value:  # NaN
            return False
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in ('nan', 'none'):
        return False
    if name in _ZERO_IS_EMPTY:
        try:
            return float(text) != 0
        except ValueError:
            return True
    return True


def richness(row):
    """How many of RICH_FIELDS the row has filled in."""
    return sum(filled(row.get(name), name) for name in RICH_FIELDS)


def artist_title_key(row):
    """'artist\ttitle' with case and spaces ignored; '' when either is missing (such rows are never grouped)."""
    def norm(value):
        return re.sub(r'\s+', ' ', str(value)).strip().casefold() if filled(value) else ''
    artist, title = norm(row.get('Artist')), norm(row.get('Title'))
    return f'{artist}\t{title}' if artist and title else ''


def file_digest(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def _same_file_keys(rows, exists, size, digest):
    """{row index: content key} for rows whose file exists: size first, a hash only where sizes collide."""
    by_size = {}
    for index, row in rows:
        path = str(row.get('File_Path') or '')
        if path and exists(path):
            try:
                by_size.setdefault(size(path), []).append((index, path))
            except OSError:
                continue
    keys, hashed = {}, {}
    for file_size, entries in by_size.items():
        if len(entries) < 2:  # a size no other row has: no copy
            continue
        for index, path in entries:
            key = canonical_path(path)
            if key not in hashed:  # the same path twice is hashed once
                try:
                    hashed[key] = digest(path)
                except OSError:
                    continue
            keys[index] = (file_size, hashed[key])
    return keys


def find_duplicates(table, mode, in_collection=lambda path: False, exists=os.path.exists,
                    size=os.path.getsize, digest=file_digest):
    """[Group] of rows that are duplicates by `mode`, each with the row to keep first. table: the library DataFrame
    (its index identifies the rows). in_collection(path): the track is in the Traktor / Rekordbox library."""
    if table is None or table.empty or 'File_Path' not in table:
        return []
    rows = list(table.to_dict('index').items())
    if mode == PATH:
        keys = {index: canonical_path(row.get('File_Path')) for index, row in rows}
    elif mode == ARTIST_TITLE:
        keys = {index: artist_title_key(row) for index, row in rows}
    elif mode == SAME_FILE:
        keys = _same_file_keys(rows, exists, size, digest)
    else:
        raise ValueError(f'Unknown duplicate mode: {mode}')
    groups = {}
    for index, _row in rows:
        key = keys.get(index)
        if key:
            groups.setdefault(key, []).append(index)
    by_index = dict(rows)
    result = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ranked, reasons = rank(by_index, members, in_collection, exists)
        result.append(Group(ranked[0], ranked[1:], reasons))
    return sorted(result, key=lambda group: group.keep)


def rank(rows, members, in_collection=lambda path: False, exists=os.path.exists):
    """(members best first, {index: reason}) by the keep rule: file exists, richest, in a collection, first."""
    facts = {}
    for position, index in enumerate(members):
        row = rows[index]
        path = str(row.get('File_Path') or '')
        facts[index] = (bool(path) and exists(path), richness(row), bool(path) and in_collection(path), position)
    ranked = sorted(members, key=lambda index: (not facts[index][0], -facts[index][1], not facts[index][2],
                                                facts[index][3]))
    reasons = {index: ', '.join(part for part in (
        'file exists' if facts[index][0] else 'file missing',
        f'{facts[index][1]} fields filled in',
        'in the Traktor / Rekordbox collection' if facts[index][2] else '',
    ) if part) for index in members}
    return ranked, reasons
