"""The similarity map in a window of its own (*Own window* on the map), e.g. on a second screen.

The map widget itself moves between this window and its tab in the main window; the main window decides (it owns
the map's data flow). Closing this window puts the map back in its tab.

The window has its own search bar (asked 2026-11-20): with text in it, the map shows the tracks that match it, out
of the List's source (All Tracks, a playlist, ...), instead of the tracks the main window's search leaves in the
List. Empty, the map follows the List as in its tab. It understands what the main search bar does (text, color:).
"""
from PyQt5.QtCore import QByteArray, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

GEOMETRY_SETTING = 'Map window geometry'
SEARCH_DELAY_MS = 250   # typing: the map follows after this pause, not on every key


class MapWindow(QWidget):
    closed = pyqtSignal()           # the user closed the window: dock the map again
    search_changed = pyqtSignal()   # the map's own search text changed (after a short pause)

    def __init__(self, map_widget, settings, icon=None):
        # No parent: its own taskbar entry and free placement (another screen); the main window closes it.
        super().__init__(None, Qt.Window)
        self.settings = settings
        self.setWindowTitle('SongSelector - Similarity map')
        if icon is not None:
            self.setWindowIcon(icon)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel('Search the map:'))
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText('artist, title, genre, comment... or color:orange  (empty: the map follows '
                                       "the main window's List)")
        self.search.setToolTip("While this has text, the map shows the tracks that match it, out of the List's "
                               "source (All Tracks, a playlist...); the main window's search then only filters the "
                               'List. Clear it to follow the List again.')
        search_row.addWidget(self.search, 1)
        layout.addLayout(search_row)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self.search_changed.emit)
        self.search.textChanged.connect(lambda _text: self._search_timer.start())
        layout.addWidget(map_widget)
        # The tab widget hides the pages that are not current, and a hidden widget stays hidden when it moves: e.g.
        # at a start that reopens the map detached while the List tab is current, the window was empty (grey).
        map_widget.show()
        self.resize(1100, 750)
        saved = settings.get(GEOMETRY_SETTING)
        if saved:
            self.restoreGeometry(QByteArray.fromBase64(saved.encode('ascii')))
        self.closing_with_app = False

    def search_text(self):
        return self.search.text().strip()

    def save_geometry(self):
        self.settings[GEOMETRY_SETTING] = bytes(self.saveGeometry().toBase64()).decode('ascii')

    def closeEvent(self, event):
        self.save_geometry()
        super().closeEvent(event)
        if not self.closing_with_app:
            self.closed.emit()


class MapPlaceholder(QWidget):
    """Shown in the map's tab while the map is in its own window."""

    def __init__(self, show_window, dock, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch()
        text = QLabel('The similarity map is in its own window.')
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(text)
        for label, action in (('Bring that window to the front', show_window), ('Show the map here again', dock)):
            button = QPushButton(label)
            button.clicked.connect(action)
            layout.addWidget(button, 0, Qt.AlignHCenter)
        layout.addStretch()
