"""
treee_widgets.py
Custom tree widgets for the Traktor Key Calculator
"""
import os
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QAbstractItemView, QMessageBox
from PyQt5.QtCore import Qt, QMimeData, QUrl
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import (QTreeWidget, QTreeWidgetItem, QAbstractItemView, 
                             QMessageBox, QApplication)

from traktor_key_calculator.ui.delegates import ColorDotDelegate
from traktor_key_calculator.ui.theme import status_style
from traktor_key_calculator.config import HEADER_INDEX, AUDIO_EXTENSIONS, SS_COLOR_COLUMN
from traktor_key_calculator.core.audio_metadata import get_file_extension, extract_audio_metadata



class DraggableTreeWidget(QTreeWidget):
    """Custom QTreeWidget that supports dragging files"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        # Click, Shift+click (range) and Ctrl+click (toggle), as in Explorer / Traktor
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.parent_app = parent
        
        # Set the color delegate for the color column (column 10)
        self.color_delegate = ColorDotDelegate(self)
        self.setItemDelegateForColumn(HEADER_INDEX.get("Color"), self.color_delegate)
        self.setItemDelegateForColumn(HEADER_INDEX.get(SS_COLOR_COLUMN), self.color_delegate)
        
        # Sort state
        self.sort_column = 0
        self.sort_order = True  # True = ascending, False = descending

        self.header().sectionClicked.connect(self._store_sort_state)

    def sortItems(self, column, order):
        super().sortItems(column, order)
        self.sort_column = column
        self.sort_order = (order == Qt.AscendingOrder)

    def _store_sort_state(self, column):
        """Update stored sort state when user clicks column header"""
        order = self.header().sortIndicatorOrder()
        self.sort_column = column
        self.sort_order = (order == Qt.AscendingOrder)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete and self.selectedItems():
            self.parent_app.remove_selected_tracks(self)
            event.accept()
            return
        super().keyPressEvent(event)

    def selected_paths(self):
        return [item.text(HEADER_INDEX['Path']) for item in self.selectedItems() if item.text(HEADER_INDEX['Path'])]

    def mousePressEvent(self, event):
        """Handle mouse press event to prepare for dragging"""
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()

    def mouseMoveEvent(self, event):
        """Handle mouse move event for dragging"""
        if not (event.buttons() & Qt.LeftButton):
            return
            
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return
            
        selected = self.selected_paths()
        if not selected:
            return
        # Drag every selected file that exists (e.g. into Traktor, Explorer or the other panel)
        files = [path for path in selected if os.path.exists(path)]
        if not files:
            self.parent_app.status_bar.showMessage(f"File not found: {selected[0]}")
            return

        drag = QDrag(self)
        mime_data = QMimeData()
        # File URLs are what make the drag work with external apps
        mime_data.setUrls([QUrl.fromLocalFile(path) for path in files])
        drag.setMimeData(mime_data)
        result = drag.exec_(Qt.CopyAction)

        if result == Qt.CopyAction:
            name = os.path.basename(files[0]) if len(files) == 1 else f'{len(files)} files'
            self.parent_app.status_bar.showMessage(f"Dragged {name}")
        else:
            self.parent_app.status_bar.showMessage("Drag cancelled")


def audio_paths(mime):
    """Only local audio files; incoming drops never move or edit them."""
    if not mime.hasUrls():
        return []
    return [url.toLocalFile() for url in mime.urls()
            if url.isLocalFile() and os.path.isfile(url.toLocalFile())
            and get_file_extension(url.toLocalFile()) in AUDIO_EXTENSIONS]


class AudioDropMixin:
    playlist_drop = False

    def dragEnterEvent(self, event):
        if audio_paths(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = audio_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        self.parent_app.import_audio_files(paths, to_playlist=self.playlist_drop)
        event.setDropAction(Qt.CopyAction)
        event.accept()


class PoolTreeWidget(AudioDropMixin, DraggableTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.selectionModel().selectionChanged.connect(self.handle_selection_feedback)

    def handle_selection_feedback(self, selected, deselected):
        items = self.selectedItems()
        if not items:
            return
        path = items[0].text(HEADER_INDEX['Path'])
        missing = not path or not os.path.isfile(path)
        self.parent_app.status_bar.setStyleSheet(status_style('error') if missing else '')
        self.parent_app.status_bar.showMessage(f'File not found: {path}' if missing else '')


class PlaylistTreeWidget(AudioDropMixin, DraggableTreeWidget):
    playlist_drop = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
