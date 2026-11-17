"""The busy spinner: turns while any reason is on, idle costs nothing."""
import unittest

from PyQt5.QtWidgets import QApplication

from songselector.ui.busy_spinner import BusySpinner


class BusySpinnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_idle_spinner_is_hidden_and_its_timer_stopped(self):
        spinner = BusySpinner()
        self.assertFalse(spinner.busy())
        self.assertFalse(spinner.running())
        self.assertTrue(spinner.isHidden())

    def test_turns_while_any_reason_is_on(self):
        spinner = BusySpinner()
        spinner.set_busy('Saving')
        spinner.set_busy('Searching')
        spinner.set_busy('Saving')  # the same reason twice counts once
        self.assertTrue(spinner.running())
        self.assertFalse(spinner.isHidden())
        self.assertEqual(spinner.reasons(), ['Saving', 'Searching'])
        self.assertEqual(spinner.toolTip(), 'Saving...\nSearching...')
        spinner.set_busy('Saving', False)
        self.assertTrue(spinner.running())  # still searching
        self.assertEqual(spinner.toolTip(), 'Searching...')
        spinner.set_busy('Searching', False)
        self.assertFalse(spinner.running())
        self.assertTrue(spinner.isHidden())
        spinner.set_busy('never started', False)  # harmless
        self.assertFalse(spinner.busy())

    def test_paints_and_advances(self):
        spinner = BusySpinner(size=20)
        spinner.set_busy('Working')
        angle = spinner._angle
        spinner._turn()
        self.assertNotEqual(spinner._angle, angle)
        self.assertFalse(spinner.grab().isNull())  # paintEvent runs without errors
        self.assertEqual(spinner.sizeHint().width(), 24)


if __name__ == '__main__':
    unittest.main()
