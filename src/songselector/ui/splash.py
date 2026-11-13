"""Startup splash screen: immediate feedback after a double-click, until the main window is up.

Two layers with the same image (splash.png, drawn by packaging/make_splash.py):
1. The exe's own splash (PyInstaller, packaging/SongSelector.spec) appears at once, while the one-file exe
   unpacks itself, before any Python runs. Only in builds made with Tcl/Tk available.
2. Once Qt runs, StartupSplash takes over (and closes the first), while the main window is built
   (library, Traktor collection, tables: a few seconds). Also shown when running from source.
"""
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QPixmap
from PyQt5.QtWidgets import QApplication, QSplashScreen

IMAGE = Path(__file__).with_name('splash.png')
TEXT_POSITION = (34, 212)  # bottom-left of the status text; the same as text_pos in the spec
TEXT_COLOUR = QColor('#8c9096')


def close_exe_splash():
    """Close the exe's own splash, if it has one. Does nothing when running from source."""
    try:
        import pyi_splash  # exists only inside a PyInstaller exe built with a splash screen
        pyi_splash.close()
    except Exception:
        pass


class StartupSplash(QSplashScreen):
    def __init__(self, version):
        pixmap = QPixmap(str(IMAGE))
        super().__init__(pixmap if not pixmap.isNull() else QPixmap(520, 260))
        self.version = version
        self.text = ''
        # Own title: without one, Qt uses the exe's name ("SongSelector-1.0.1"), which window lookups such as
        # scripts/verify_release.ps1 would mistake for the main window ("SongSelector 1.0.1").
        self.setWindowTitle('Starting SongSelector')

    def show_status(self, text):
        """Show a line of status text and repaint now (the event loop is not running yet)."""
        self.text = text
        self.repaint()
        QApplication.processEvents()

    def drawContents(self, painter):
        painter.setPen(TEXT_COLOUR)
        painter.setFont(QFont('Segoe UI', 9))
        painter.drawText(*TEXT_POSITION, self.text)
        painter.drawText(self.rect().adjusted(0, 0, -14, -10), Qt.AlignRight | Qt.AlignBottom, f'v{self.version}')


def start_splash(version):
    """Show the Qt splash and hand over from the exe's splash. Returns it, to finish() once the window shows."""
    splash = StartupSplash(version)
    splash.show()
    splash.show_status('Loading your library...')
    close_exe_splash()  # after the Qt splash is visible, so there is no gap
    return splash
