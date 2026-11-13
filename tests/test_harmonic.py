"""Harmonic mixing relations, checked cell by cell against Mixed In Key's published table."""
import unittest

from songselector.core.harmonic import MIX_TYPES, compatible_keys, mix_type, parse_camelot

COLUMNS = ('perfect_mix', 'minus_1_mix', 'plus_1_mix', 'energy_boost', 'scale_change',
           'diagonal_mix', 'jaws_mix', 'mood_shifter')

# Mixed In Key's Harmonic Mixing table, typed in as published (starting key -> one key per column).
MIXED_IN_KEY_TABLE = '''
1A  1A  12A 2A  3A  1B  12B 8A  4B
2A  2A  1A  3A  4A  2B  1B  9A  5B
3A  3A  2A  4A  5A  3B  2B  10A 6B
4A  4A  3A  5A  6A  4B  3B  11A 7B
5A  5A  4A  6A  7A  5B  4B  12A 8B
6A  6A  5A  7A  8A  6B  5B  1A  9B
7A  7A  6A  8A  9A  7B  6B  2A  10B
8A  8A  7A  9A  10A 8B  7B  3A  11B
9A  9A  8A  10A 11A 9B  8B  4A  12B
10A 10A 9A  11A 12A 10B 9B  5A  1B
11A 11A 10A 12A 1A  11B 10B 6A  2B
12A 12A 11A 1A  2A  12B 11B 7A  3B
1B  1B  12B 2B  3B  1A  2A  8B  10A
2B  2B  1B  3B  4B  2A  3A  9B  11A
3B  3B  2B  4B  5B  3A  4A  10B 12A
4B  4B  3B  5B  6B  4A  5A  11B 1A
5B  5B  4B  6B  7B  5A  6A  12B 2A
6B  6B  5B  7B  8B  6A  7A  1B  3A
7B  7B  6B  8B  9B  7A  8A  2B  4A
8B  8B  7B  9B  10B 8A  9A  3B  5A
9B  9B  8B  10B 11B 9A  10A 4B  6A
10B 10B 9B  11B 12B 10A 11A 5B  7A
11B 11B 10B 12B 1B  11A 12A 6B  8A
12B 12B 11B 1B  2B  12A 1A  7B  9A
'''


class HarmonicTests(unittest.TestCase):
    def table(self):
        for line in MIXED_IN_KEY_TABLE.strip().splitlines():
            start, *targets = line.split()
            yield start, dict(zip(COLUMNS, targets))

    def test_every_cell_of_the_mixed_in_key_table(self):
        cells = 0
        for start, expected in self.table():
            for name, target in expected.items():
                with self.subTest(start=start, mix=name):
                    self.assertEqual(mix_type(start, target).name, name)
                    cells += 1
        self.assertEqual(cells, 24 * 8)

    def test_compatible_keys_are_exactly_the_table_row(self):
        for start, expected in self.table():
            self.assertEqual(compatible_keys(start), expected, start)

    def test_other_keys_are_not_named_mixes_and_relations_are_directional(self):
        for start, expected in self.table():
            named = set(expected.values())
            for number in range(1, 13):
                for letter in 'AB':
                    if f'{number}{letter}' not in named:
                        self.assertIsNone(mix_type(start, f'{number}{letter}'))
        self.assertEqual(mix_type('1A', '3A').name, 'energy_boost')
        self.assertIsNone(mix_type('3A', '1A'))

    def test_parsing_and_weights(self):
        self.assertEqual(parse_camelot(' 8a '), (8, 'A'))
        for bad in ('Unknown', '', None, '13A', '0B', 'A', '8C'):
            self.assertIsNone(parse_camelot(bad), bad)
            self.assertIsNone(mix_type(bad, '8A'))
        self.assertEqual([mix.weight for mix in MIX_TYPES], sorted((mix.weight for mix in MIX_TYPES), reverse=True))
        self.assertEqual(mix_type('5B', '5B').weight, 10)
