"""Startup splash: the image ships with the package and the splash draws without the exe's own splash."""
import unittest

from PyQt5.QtWidgets import QApplication

from songselector.ui.splash import IMAGE, StartupSplash, close_exe_splash, start_splash


class SplashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_image_is_in_the_package(self):
        self.assertTrue(IMAGE.is_file())

    def test_splash_shows_the_image_and_status_text(self):
        splash = StartupSplash('1.2.3')
        self.assertEqual((splash.pixmap().width(), splash.pixmap().height()), (520, 260))
        splash.show_status('Loading your library...')
        self.assertEqual(splash.text, 'Loading your library...')
        splash.close()

    def test_title_cannot_be_mistaken_for_the_main_window(self):
        # verify_release.ps1 finds the main window by its title, "SongSelector <version>".
        self.assertFalse(StartupSplash('1.2.3').windowTitle().startswith('SongSelector'))

    def test_runs_from_source_where_there_is_no_exe_splash(self):
        close_exe_splash()  # no pyi_splash module outside the exe: must do nothing
        splash = start_splash('1.2.3')
        self.assertTrue(splash.isVisible())
        splash.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
