"""Application entry point: creates the Qt application and the main window."""
import sys

from PyQt5.QtWidgets import QApplication, QMessageBox

from songselector import __version__
from songselector.config import init_settings
from songselector.ui.splash import close_exe_splash, start_splash


def main():
    application = QApplication(sys.argv)
    splash = start_splash(__version__)
    ok, error = init_settings()
    if not ok:
        splash.close()
        QMessageBox.critical(None, 'Cannot start', str(error))
        return 1
    from songselector.ui.main_window import MainWindow  # imported here: the splash is up meanwhile
    window = MainWindow()
    window.show()
    splash.finish(window)
    splash.deleteLater()  # gone for good, not a hidden window that lingers
    close_exe_splash()  # in case the Qt splash could not take over
    return application.exec_()


if __name__ == '__main__':
    sys.exit(main())
