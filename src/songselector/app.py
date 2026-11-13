"""Application entry point: creates the Qt application and the main window."""
import sys

from PyQt5.QtWidgets import QApplication, QMessageBox

from songselector.config import init_settings
from songselector.ui.main_window import MainWindow


def main():
    application = QApplication(sys.argv)
    ok, error = init_settings()
    if not ok:
        QMessageBox.critical(None, 'Cannot start', str(error))
        return 1
    window = MainWindow()
    window.show()
    return application.exec_()


if __name__ == '__main__':
    sys.exit(main())
