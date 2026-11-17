"""The background writer: jobs off the UI thread, in order, results back on the UI thread."""
import threading
import time
import unittest

from PyQt5.QtWidgets import QApplication

from songselector.ui.background import BackgroundWriter


class BackgroundWriterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.writer = BackgroundWriter()
        self.addCleanup(self.writer.stop)

    def test_jobs_run_off_the_ui_thread_in_order_and_report_on_it(self):
        ran_on, delivered_on, results = [], [], []

        def job(number):
            def run():
                ran_on.append(threading.current_thread())
                time.sleep(0.02 * (3 - number))  # the first job is the slowest: order must still hold
                return number
            return run

        for number in range(3):
            self.writer.submit(job(number), lambda result: (results.append(result),
                                                            delivered_on.append(threading.current_thread())))
        self.assertTrue(self.writer.flush())
        self.assertEqual(results, [0, 1, 2])
        self.assertTrue(all(thread is not threading.main_thread() for thread in ran_on))
        self.assertTrue(all(thread is threading.main_thread() for thread in delivered_on))

    def test_an_exception_goes_to_on_error_and_the_next_job_still_runs(self):
        errors, results = [], []
        self.writer.submit(lambda: 1 / 0, results.append, errors.append)
        self.writer.submit(lambda: 'next', results.append)
        self.assertTrue(self.writer.flush())
        self.assertIsInstance(errors[0], ZeroDivisionError)
        self.assertEqual(results, ['next'])

    def test_an_exception_without_on_error_is_reported_by_the_failed_signal(self):
        failures = []
        self.writer.failed.connect(failures.append)
        self.writer.submit(lambda: [][0])
        self.assertTrue(self.writer.flush())
        self.assertIsInstance(failures[0], IndexError)

    def test_busy_from_the_first_job_until_the_last_is_delivered(self):
        states = []
        self.writer.busy_changed.connect(states.append)
        self.assertFalse(self.writer.busy())
        for _ in range(3):
            self.writer.submit(lambda: time.sleep(0.01))
        self.assertTrue(self.writer.busy())
        self.assertTrue(self.writer.flush())
        self.assertFalse(self.writer.busy())
        self.assertEqual(states, [True, False])

    def test_flush_gives_up_after_the_timeout(self):
        release = threading.Event()
        self.writer.submit(release.wait)
        self.assertFalse(self.writer.flush(timeout=0.1))
        release.set()
        self.assertTrue(self.writer.flush())


if __name__ == '__main__':
    unittest.main()
