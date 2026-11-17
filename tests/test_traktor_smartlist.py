"""Traktor smartlist queries (core.traktor_smartlist), checked against the user's real queries' syntax."""
import unittest
from datetime import date

from songselector.core.traktor_smartlist import SmartlistError, matches, open_key, parse, smartlist_paths

TODAY = date(2026, 11, 17)

# The query strings of the user's 43 Traktor smartlists (collection.nml, 2026-11-17): every one must be readable.
REAL_QUERIES = [
    '$BPM > 165.000000 & $COLOR == 0',
    '$BPM < 125.000000 & $BPM > 100.000000 & $GENRE !% "funk" & $GENRE !% "rock" & $GENRE <> "" & $TIME > 01:00 & '
    '$GENRE !% "rap" & $GENRE !% "glitch"',
    '$BPM > 99.000000 & $BPM <= 124.000000 & $COLOR <> 1 & $COMMENT !% "-s" & $GENRE !% "glitch" & $GENRE !% "funk" & '
    '$GENRE % "down"',
    '$BPM >= 125.000000 & $BPM <= 136.000000 & $COLOR <> 1 & $COLOR <> 2 & $COLOR <> 3',
    '$BPM ~ 130.000000',
    '$PLAYCOUNT <= 1 & $BPM > 125.000000 & $BPM <= 140.000000 & $RATING == 0',
    '$BPM > 110.000000 & $BPM < 140.000000 & $ARTIST <> "" & $GENRE <> "" & $RATING > 0 & $COMMENT !% "-s"',
    '$BPM < 180.000000 & $BPM > 168.000000 & $TIME >= 04:00 & $RATING >= 3 & $COLOR <> 0',
    '$GENRE % "downtempo" | $GENRE % "chill" | $GENRE % "drubeat" | $GENRE % "tribal"',
    '$KEY == 1m',
    '$FILEPATH % "audio_191124" & $KEY == 1d',
    '$ARTIST == ""',
    '$TITLE % "a" & $BPM ~ 130.000000',
    '$IMPORTDATE >= MONTHS_AGO(1)',
    '$FILEPATH % "SELECTOR" | $FILEPATH % "BREAKBEAT" | $FILEPATH % "DNB" | $GENRE % "downtempo"',
    '$FILEPATH % "DJ\\complete\\" & $GENRE !% "rock" & $GENRE <> "mix" & $COLOR <> 0 & $RATING >= 2',
    '$RATING == 5',
]


def record(**fields):
    base = {'path': r'E:\DJ\complete\Break\a.mp3', 'artist': 'Artist', 'title': 'Title', 'genre': 'Breakbeat',
            'comment': '', 'bpm': 130.0, 'key': ('A', 'minor'), 'color': '5', 'rating': 4, 'playcount': '2',
            'playtime': '300', 'import_date': '2026/11/1'}
    base.update(fields)
    return base


def check(query, **fields):
    return matches(record(**fields), parse(query, TODAY))


class TraktorSmartlistTests(unittest.TestCase):
    def test_every_real_query_is_readable(self):
        for query in REAL_QUERIES:
            with self.subTest(query=query):
                parse(query, TODAY)

    def test_numbers_and_about(self):
        self.assertTrue(check('$BPM > 126.000000 & $BPM < 142.000000'))
        self.assertFalse(check('$BPM > 126.000000 & $BPM < 142.000000', bpm=142.0))
        self.assertTrue(check('$BPM ~ 130.000000', bpm=130.9))
        self.assertFalse(check('$BPM ~ 130.000000', bpm=131.5))
        self.assertTrue(check('$BPM > 165.000000 & $COLOR == 0', bpm=170.0, color=None))  # no colour counts as 0
        self.assertTrue(check('$RATING == 0', rating=None))                                 # unrated
        self.assertTrue(check('$PLAYCOUNT <= 1', playcount=None))
        self.assertTrue(check('$TIME > 04:00'))                                             # 300 s = 5:00
        self.assertFalse(check('$TIME >= 04:00', playtime='200'))

    def test_text_ignores_case(self):
        self.assertTrue(check('$GENRE % "BREAK"'))
        self.assertTrue(check('$GENRE !% "rock"'))
        self.assertFalse(check('$GENRE !% "beat"'))
        self.assertTrue(check('$ARTIST == ""', artist=None))
        self.assertFalse(check('$GENRE <> ""', genre=''))
        self.assertTrue(check('$FILEPATH % "DJ\\complete\\"'))
        self.assertTrue(check('$TITLE % "a" & $BPM ~ 130.000000', title='Alarm'))

    def test_keys_in_open_key_notation(self):
        self.assertEqual(open_key(('A', 'minor')), '1m')
        self.assertEqual(open_key(('C', 'major')), '1d')
        self.assertTrue(check('$KEY == 1m'))
        self.assertFalse(check('$KEY == 1d'))
        self.assertTrue(check('$KEY == 1M'))
        self.assertFalse(check('$KEY == 1m', key=None))

    def test_dates(self):
        self.assertTrue(check('$IMPORTDATE >= MONTHS_AGO(1)'))                      # 2026/11/1 is in the last month
        self.assertFalse(check('$IMPORTDATE >= MONTHS_AGO(1)', import_date='2026/9/1'))
        self.assertFalse(check('$IMPORTDATE >= MONTHS_AGO(1)', import_date=None))
        self.assertTrue(check('$IMPORTDATE < 2026/01/01', import_date='2025/12/31'))

    def test_and_binds_tighter_than_or_and_parentheses(self):
        self.assertTrue(check('$GENRE % "house" | $BPM > 120.000000 & $RATING >= 4'))   # house | (fast & rated)
        self.assertFalse(check('($GENRE % "house" | $BPM > 120.000000) & $RATING >= 5'))
        self.assertTrue(check('($GENRE % "house" | $BPM > 120.000000) & $RATING >= 4'))

    def test_what_cannot_be_evaluated_says_why(self):
        for query, message in (('$PLAYED == TRUE', 'only Traktor knows'), ('$NONSENSE == 1', 'unknown field'),
                               ('$BPM > fast', 'needs a number'), ('$BPM >', 'unexpected end'),
                               ('($BPM > 1', 'unexpected end'), ('', 'no query'), ('$GENRE % "a" $BPM', 'unexpected')):
            with self.subTest(query=query):
                with self.assertRaises(SmartlistError) as raised:
                    parse(query, TODAY)
                self.assertIn(message, str(raised.exception))

    def test_smartlist_paths_keep_the_collection_order(self):
        records = [record(path='b.mp3', bpm=170.0), record(path='a.mp3', bpm=120.0), record(path='c.mp3', bpm=171.0)]
        self.assertEqual(smartlist_paths(records, '$BPM > 165.000000', TODAY), ['b.mp3', 'c.mp3'])


if __name__ == '__main__':
    unittest.main()
