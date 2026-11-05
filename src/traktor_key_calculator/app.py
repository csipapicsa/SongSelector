"""Application entry point: creates the Qt application and the main window."""
import sys

from PyQt5.QtWidgets import QApplication, QMessageBox

from traktor_key_calculator.config import init_settings
from traktor_key_calculator.ui.main_window import TraktorKeyCalculator


def main():
    application = QApplication(sys.argv)
    ok, error = init_settings()
    if not ok:
        QMessageBox.critical(None, 'Cannot start', str(error))
        return 1
    window = TraktorKeyCalculator()
    window.show()
    return application.exec_()


if __name__ == '__main__':
    sys.exit(main())
