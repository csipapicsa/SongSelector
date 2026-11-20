"""Time left of the embedding analysis (core/eta.py) and its place in the progress line."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from songselector.core.eta import Eta, format_left


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class EtaTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.eta = Eta(self.clock)

    def run_tracks(self, seconds_each, count, done=0, total=100):
        left = None
        for _ in range(count):
            self.clock.now += seconds_each
            done += 1
            left = self.eta.update(done, total)
        return done, left

    def test_no_estimate_until_a_few_tracks_have_shown_the_speed(self):
        self.assertIsNone(self.eta.update(0, 100))
        self.clock.now += 30  # loading the models
        self.assertIsNone(self.eta.update(1, 100))
        done, left = self.run_tracks(4, 3, done=1)
        self.assertIsNotNone(left)

    def test_estimate_follows_the_recent_speed(self):
        self.eta.update(0, 1000)
        done, left = self.run_tracks(5, 20, total=1000)            # 5 s per track
        self.assertAlmostEqual(left, (1000 - 20) * 5, delta=1)
        done, left = self.run_tracks(10, 100, done=done, total=1000)  # the computer got busier: 10 s per track
        self.assertAlmostEqual(left, (1000 - done) * 10, delta=(1000 - done) * 0.2)  # the old speed has left the window

    def test_skipped_files_do_not_make_it_look_fast_for_long(self):
        self.eta.update(0, 500)
        self.clock.now += 1
        self.eta.update(50, 500)  # 50 missing files finish at once
        done, left = self.run_tracks(6, 80, done=50, total=500)  # then 6 s per track for 8 minutes
        self.assertAlmostEqual(left, (500 - done) * 6, delta=(500 - done) * 6 * 0.1)

    def test_a_new_run_and_the_end(self):
        self.eta.update(0, 10)
        done, left = self.run_tracks(5, 5, total=10)
        self.assertIsNone(self.eta.update(3, 10))  # counting started again: no old speed
        self.assertIsNone(self.eta.update(10, 10))  # done

    def test_lightweight_wording(self):
        self.assertEqual(format_left(None), '')
        self.assertEqual(format_left(20), 'less than a minute left')
        self.assertEqual(format_left(12 * 60), 'about 12 min left')
        self.assertEqual(format_left(3 * 3600 + 23 * 60), 'about 3 h 23 min left')
        self.assertEqual(format_left(2 * 3600), 'about 2 h left')
        self.assertEqual(format_left(14 * 3600 + 40 * 60), 'about 15 h left')


class ProgressLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def test_the_progress_line_shows_the_time_left(self):
        from songselector.config import SETTINGS_DEFAULT
        from songselector.ui.main_window import MainWindow
        with tempfile.TemporaryDirectory(dir=os.environ['SONGSELECTOR_APP_DATA_DIR']) as folder:
            settings = Path(folder) / 'settings.json'
            settings.write_text(json.dumps(SETTINGS_DEFAULT))
            with patch('songselector.ui.main_window.SETTINGS_FILE', str(settings)):
                window = MainWindow()
                try:
                    clock = Clock()
                    window.analysis_eta = Eta(clock)
                    window._show_embedding_progress(0, 200, 0, 'a.mp3')
                    for done in range(1, 6):  # 12 s per track
                        clock.now += 12
                        window._show_embedding_progress(done, 200, 0, 'a.mp3')
                    self.assertIn('5/200, about 39 min left - a.mp3', window.embedding_label.text())
                    window._show_embedding_progress(200, 200, 0, '')
                    self.assertNotIn('left', window.embedding_label.text())
                finally:
                    window.close()


if __name__ == '__main__':
    unittest.main()
