"""Exact DJ-program colours and their families (core/track_colors.py)."""
import unittest

from songselector.core.color_search import COLOR_NAMES, parse_color_search
from songselector.core.track_colors import family, hex_color, normalize

# Track colour palettes from Mixxx 2.5's src/util/color/predefinedcolorpalettes.cpp -> expected family.
MIXXX_TRACK_COLORS = {
    '#880000': 'red', '#FF0000': 'red', '#FF8800': 'orange', '#FFFF00': 'yellow', '#88FF00': 'green',
    '#00FF00': 'green', '#008800': 'green', '#008888': 'cyan', '#0088FF': 'blue', '#0000FF': 'blue',
    '#000088': 'blue', '#880088': 'violet', '#AA00FF': 'violet', '#FF00FF': 'violet', '#FF88FF': 'pink',
    '#FFFFFF': 'grey', '#00FFFF': 'cyan', '#00FF88': 'green', '#888888': 'grey'}
REKORDBOX_TRACK_COLORS = {  # Rekordbox's own names: pink, red, orange, yellow, green, aqua, blue, purple
    '#F870F8': 'pink', '#F87090': 'red', '#F8A030': 'orange', '#F8E331': 'yellow', '#1EE000': 'green',
    '#16C0F8': 'cyan', '#0150F8': 'blue', '#9808F8': 'violet'}
TRAKTOR_TRACK_COLORS = {  # Traktor's 1-7: red, orange, yellow, green, blue, violet, magenta
    '#FA4B35': 'red', '#FF8402': 'orange', '#FFF700': 'yellow', '#00F329': 'green', '#0187FF': 'blue',
    '#A669FF': 'violet', '#FE55EA': 'violet'}


class TrackColorTests(unittest.TestCase):
    def test_palettes_of_mixxx_rekordbox_and_traktor_fall_into_the_families_their_programs_name(self):
        for palette in (MIXXX_TRACK_COLORS, REKORDBOX_TRACK_COLORS, TRAKTOR_TRACK_COLORS):
            for colour, name in palette.items():
                with self.subTest(colour=colour):
                    self.assertEqual(COLOR_NAMES[family(colour)], name)

    def test_stored_values(self):
        self.assertEqual(normalize(4), 4)
        self.assertEqual(normalize('4.0'), 4)
        self.assertEqual(normalize('#ff8800'), '#FF8800')
        for empty in (None, '', 'nan', float('nan'), 0):
            self.assertEqual(normalize(empty), 0)
        self.assertIsNone(normalize('#12'))
        self.assertIsNone(normalize(42))
        self.assertEqual(hex_color(0x00FFFF), '#00FFFF')
        self.assertEqual(family(5), 5)  # a family number is its own family

    def test_search_finds_exact_colours_by_family_name(self):
        search = parse_color_search('color:cyan,orange')
        self.assertTrue(search.matches('#00FFFF'))
        self.assertTrue(search.matches('#FF8800'))
        self.assertTrue(search.matches(2))
        self.assertFalse(search.matches('#880000'))
        self.assertTrue(parse_color_search('color:aqua').matches('#16C0F8'))
        self.assertTrue(parse_color_search('-color:red').matches('#00FF00'))


if __name__ == '__main__':
    unittest.main()
