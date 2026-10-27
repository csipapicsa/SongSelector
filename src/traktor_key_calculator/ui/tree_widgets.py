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
from traktor_key_calculator.config import HEADER_INDEX, AUDIO_EXTENSIONS
from traktor_key_calculator.core.audio_metadata import get_file_extension, extract_audio_metadata



class DraggableTreeWidget(QTreeWidget):
    """Custom QTreeWidget that supports dragging files"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.parent_app = parent
        
        # Set the color delegate for the color column (column 10)
        self.color_delegate = ColorDotDelegate(self)
        self.setItemDelegateForColumn(HEADER_INDEX.get("Color"), self.color_delegate)
        
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
            
        # Get the selected item
        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        # Get the file path from the item's data
        file_path = selected_items[0].text(HEADER_INDEX.get("Path"))
        if not file_path or not os.path.exists(file_path):
            self.parent_app.status_bar.showMessage(f"File not found: {file_path}")
            return
        
        # Start the drag operation
        drag = QDrag(self)
        mime_data = QMimeData()
        
        # Set the URL for the file (this is what makes the drag work with external apps)
        mime_data.setUrls([QUrl.fromLocalFile(file_path)])
        drag.setMimeData(mime_data)
        
        # Execute the drag
        result = drag.exec_(Qt.CopyAction)
        
        # Update status
        if result == Qt.CopyAction:
            self.parent_app.status_bar.showMessage(f"File dragged successfully: {os.path.basename(file_path)}")
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
        self.parent_app.status_bar.setStyleSheet('color: red;' if missing else '')
        self.parent_app.status_bar.showMessage(f'File not found: {path}' if missing else '')


class PlaylistTreeWidget(AudioDropMixin, DraggableTreeWidget):
    playlist_drop = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
