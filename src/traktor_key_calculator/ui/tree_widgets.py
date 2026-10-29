"""
treee_widgets.py
Custom tree widgets for the Traktor Key Calculator
"""
import os
import re
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QAbstractItemView, QMessageBox
from PyQt5.QtCore import Qt, QMimeData, QUrl
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import (QTreeWidget, QTreeWidgetItem, QAbstractItemView, 
                             QMessageBox, QApplication)

from traktor_key_calculator.ui.delegates import ColorDotDelegate, StarRatingDelegate
from traktor_key_calculator.ui.theme import status_style
from traktor_key_calculator.config import HEADER_INDEX, AUDIO_EXTENSIONS, SS_COLOR_COLUMN, SS_RATING_COLUMN
from traktor_key_calculator.core.audio_metadata import get_file_extension, extract_audio_metadata



_NUMBER_COLUMNS = {HEADER_INDEX[name] for name in ('Original BPM', 'Rating', SS_RATING_COLUMN, 'Color', SS_COLOR_COLUMN)}


def track_sort_key(column, text):
    """What a library/playlist column sorts by: numbers as numbers, Camelot keys by number
    then letter, text case-insensitively; empty and unknown values last (ascending)."""
    text = text.strip()
    if column in _NUMBER_COLUMNS:
        try:
            number = float(text)
        except ValueError:
            number = float('nan')
        return (1, 0.0) if number != number else (0, number)
    if column == HEADER_INDEX['Camelot Key New']:
        match = re.fullmatch(r'(\d+)\s*([A-Za-z])', text)
        return (0, (int(match[1]), match[2].upper())) if match else (1, (0, ''))
    if not text or text.lower() == 'nan':
        return (1, '')
    return (0, text.casefold())


class TrackItem(QTreeWidgetItem):
    """Library and playlist row; Qt's own sorting uses track_sort_key. Sorting inside Qt keeps
    the rows in place: taking out and re-adding thousands of rows froze the window for seconds."""

    def __lt__(self, other):
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        return track_sort_key(column, self.text(column)) < track_sort_key(column, other.text(column))


class DraggableTreeWidget(QTreeWidget):
    """Custom QTreeWidget that supports dragging files"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        # Click, Shift+click (range) and Ctrl+click (toggle), as in Explorer / Traktor
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setUniformRowHeights(True)  # every row has the same columns; Qt need not measure each
        self.parent_app = parent
        
        # Set the color delegate for the color column (column 10)
        self.color_delegate = ColorDotDelegate(self)
        self.setItemDelegateForColumn(HEADER_INDEX.get("Color"), self.color_delegate)
        self.setItemDelegateForColumn(HEADER_INDEX.get(SS_COLOR_COLUMN), self.color_delegate)
        self.star_delegate = StarRatingDelegate(self)
        for column in ('Rating', SS_RATING_COLUMN):
            self.setItemDelegateForColumn(HEADER_INDEX[column], self.star_delegate)
        
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


def is_audio_file(path):
    return os.path.isfile(path) and get_file_extension(path) in AUDIO_EXTENSIONS


def find_audio_files(paths):
    """Audio files among `paths`; folders are searched with all their subfolders.

    Sorted by folder and name, so an import always has the same order.
    """
    found = []
    for path in paths:
        if os.path.isdir(path):
            for folder, subfolders, files in os.walk(path):
                subfolders.sort(key=str.casefold)
                found += [os.path.join(folder, name) for name in sorted(files, key=str.casefold)
                          if get_file_extension(name) in AUDIO_EXTENSIONS]
        elif is_audio_file(path):
            found.append(path)
    return found


def dropped_paths(mime):
    """Local audio files and folders being dragged, not expanded yet: cheap enough to run
    on every drag-move event. Incoming drops never move or edit files."""
    if not mime.hasUrls():
        return []
    # Qt gives "C:/Users/..."; normpath makes it the platform form so joined subfolder
    # paths are not mixed ("C:/Users/...\\a.mp3").
    paths = [os.path.normpath(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]
    return [path for path in paths if os.path.isdir(path) or is_audio_file(path)]


def audio_paths(mime):
    """All audio files of a drop, with dropped folders searched recursively."""
    return find_audio_files(dropped_paths(mime))


class AudioDropMixin:
    playlist_drop = False

    def dragEnterEvent(self, event):
        if dropped_paths(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = audio_paths(event.mimeData())
        if not paths:
            self.parent_app.status_label.setStyleSheet(status_style('warning'))
            self.parent_app.status_label.setText('No MP3, WAV or FLAC files in what was dropped')
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
