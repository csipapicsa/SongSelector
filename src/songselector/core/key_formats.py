"""Normalize musical, Camelot, Open Key, and NML analyzed keys."""
import math
import re

NOTES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
CAMELOT_MAJOR = ('B', 'F#', 'C#', 'G#', 'D#', 'A#', 'F', 'C', 'G', 'D', 'A', 'E')
CAMELOT_MINOR = ('G#', 'D#', 'A#', 'F', 'C', 'G', 'D', 'A', 'E', 'B', 'F#', 'C#')
OPEN_MAJOR = ('C', 'G', 'D', 'A', 'E', 'B', 'F#', 'C#', 'G#', 'D#', 'A#', 'F')
OPEN_MINOR = ('A', 'E', 'B', 'F#', 'C#', 'G#', 'D#', 'A#', 'F', 'C', 'G', 'D')


def parse_key(value):
    if value is None:
        return None
    text = str(value).strip().replace('\u266f', '#').replace('\u266d', 'b')
    numeric = re.fullmatch(r'(1[0-2]|[1-9])\s*([aAbBdDmM])', text)
    if numeric:
        number = int(numeric.group(1)) - 1
        suffix = numeric.group(2).lower()
        mapping, scale = {'a': (CAMELOT_MINOR, 'minor'), 'b': (CAMELOT_MAJOR, 'major'),
                          'd': (OPEN_MAJOR, 'major'), 'm': (OPEN_MINOR, 'minor')}[suffix]
        return mapping[number], scale
    musical = re.fullmatch(r'([a-gA-G])([#bB]?)(?:\s*(m|min|minor|maj|major))?', text, re.I)
    if not musical:
        return None
    note, accidental, suffix = musical.groups()
    semitone = NOTES.index(note.upper())
    if accidental == '#':
        semitone += 1
    elif accidental:
        semitone -= 1
    scale = 'minor' if suffix and suffix.lower() in ('m', 'min', 'minor') else 'major'
    return NOTES[semitone % 12], scale


def nml_key(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= number < 24:
        return NOTES[number % 12], 'minor' if number >= 12 else 'major'
    return None


def parse_bpm(value):
    try:
        bpm = float(str(value).strip().replace(',', '.'))
    except (TypeError, ValueError):
        return None
    return bpm if math.isfinite(bpm) and bpm > 0 else None
