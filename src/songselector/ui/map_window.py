"""The similarity map in a window of its own (*Own window* on the map), e.g. on a second screen.

The map widget itself moves between this window and its tab in the main window; the main window decides (it owns
the map's data flow). Closing this window puts the map back in its tab.
"""
from PyQt5.QtCore import QByteArray, Qt, pyqtSignal
from PyQt5.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

GEOMETRY_SETTING = 'Map window geometry'


class MapWindow(QWidget):
    closed = pyqtSignal()   # the user closed the window: dock the map again

    def __init__(self, map_widget, settings, icon=None):
        # No parent: its own taskbar entry and free placement (another screen); the main window closes it.
        super().__init__(None, Qt.Window)
        self.settings = settings
        self.setWindowTitle('SongSelector - Similarity map')
        if icon is not None:
            self.setWindowIcon(icon)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(map_widget)
        self.resize(1100, 750)
        saved = settings.get(GEOMETRY_SETTING)
        if saved:
            self.restoreGeometry(QByteArray.fromBase64(saved.encode('ascii')))
        self.closing_with_app = False

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
