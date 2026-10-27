"""Harmonic mixing relations between Camelot keys (Mixed In Key's harmonic mixing table).

Ported from the master thesis project (E:\\GITHUB_E\\MasterThesis\\functions.py,
get_mix_type_new_wheel(..., connection_mode="commercial") and its edge weights).

A relation is directional: mix_type('1A', '3A') is an energy boost (+2), while
mix_type('3A', '1A') is not a named mix. "From" is the playing track, "to" the next one.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MixType:
    name: str
    label: str
    weight: int       # how safe / common the transition is (thesis weights, 10 = best)
    special: bool     # Mixed In Key's "special effect" columns


# Strongest first. Weights are the edge weights of the thesis project.
MIX_TYPES = (
    MixType('perfect_mix', 'Perfect mix', 10, False),
    MixType('plus_1_mix', '+1 mix', 9, False),
    MixType('minus_1_mix', '-1 mix', 8, False),
    MixType('scale_change', 'Scale change', 7, False),
    MixType('energy_boost', 'Energy boost', 6, False),
    MixType('mood_shifter', 'Mood shifter', 5, True),
    MixType('jaws_mix', "Jaw's mix", 4, True),
    MixType('diagonal_mix', 'Diagonal mix', 3, False),
)
MIX_TYPES_BY_NAME = {mix.name: mix for mix in MIX_TYPES}


def parse_camelot(key):
    """'8a' / ' 8A ' -> (8, 'A'); None for anything else (e.g. 'Unknown')."""
    text = str(key or '').strip().upper()
    if len(text) < 2 or text[-1] not in 'AB' or not text[:-1].isdigit():
        return None
    number = int(text[:-1])
    return (number, text[-1]) if 1 <= number <= 12 else None


def mix_type(from_key, to_key):
    """The named harmonic relation from one Camelot key to the next, or None."""
    start, target = parse_camelot(from_key), parse_camelot(to_key)
    if start is None or target is None:
        return None
    (number, letter), (other_number, other_letter) = start, target
    step = (other_number - number) % 12          # clockwise steps on the Camelot wheel
    if letter == other_letter:
        name = {0: 'perfect_mix', 1: 'plus_1_mix', 11: 'minus_1_mix', 2: 'energy_boost', 7: 'jaws_mix'}.get(step)
    elif step == 0:
        name = 'scale_change'
    elif letter == 'A':                          # minor -> major
        name = {11: 'diagonal_mix', 3: 'mood_shifter'}.get(step)
    else:                                        # major -> minor
        name = {1: 'diagonal_mix', 9: 'mood_shifter'}.get(step)
    return MIX_TYPES_BY_NAME[name] if name else None


def compatible_keys(from_key):
    """{mix name: target Camelot key} for every named mix from this key."""
    start = parse_camelot(from_key)
    if start is None:
        return {}
    result = {}
    for number in range(1, 13):
        for letter in 'AB':
            mix = mix_type(from_key, f'{number}{letter}')
            if mix is not None:
                result[mix.name] = f'{number}{letter}'
    return result
