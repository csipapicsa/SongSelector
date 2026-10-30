"""
treee_widgets.py
Custom tree widgets for the Traktor Key Calculator
"""
import json
import os
import re
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QAbstractItemView, QMessageBox
from PyQt5.QtCore import Qt, QMimeData, QUrl
from PyQt5.QtGui import QDrag, QPainter, QPen
from PyQt5.QtWidgets import (QTreeWidget, QTreeWidgetItem, QAbstractItemView, 
                             QMessageBox, QApplication)

from traktor_key_calculator.ui.delegates import ColorDotDelegate, StarRatingDelegate
from traktor_key_calculator.ui.theme import status_style
from traktor_key_calculator.config import (HEADER_INDEX, AUDIO_EXTENSIONS, SS_COLOR_COLUMN, SS_RATING_COLUMN,
                                           POSITION_COLUMN, GROUP_COLUMN)
from traktor_key_calculator.core.audio_metadata import get_file_extension, extract_audio_metadata



_NUMBER_COLUMNS = {HEADER_INDEX[name] for name in ('Original BPM', 'Rating', SS_RATING_COLUMN, 'Color', SS_COLOR_COLUMN,
                                                   POSITION_COLUMN, GROUP_COLUMN)}
# Paths of tracks dragged inside the app (one per line), next to the file URLs other apps use.
# Also carries tracks whose file is missing.
TRACKS_MIME = 'application/x-songselector-tracks'
# A Browser entry (playlist, smartlist, artist, ...) being dragged; JSON, see list_browser.py
NODE_MIME = 'application/x-songselector-node'


def dragged_tracks(mime):
    """Paths of tracks dragged from the List or the Playlist, else []."""
    if not mime.hasFormat(TRACKS_MIME):
        return []
    return [path for path in bytes(mime.data(TRACKS_MIME)).decode('utf-8').split('\n') if path]


def dragged_node(mime):
    """The Browser entry being dragged ({'kind', 'name'}), else None."""
    if not mime.hasFormat(NODE_MIME):
        return None
    return json.loads(bytes(mime.data(NODE_MIME)).decode('utf-8'))


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
        # Flat lists: no branch indent. It sits in front of the first logical column (Artist), so
        # with # shown first it was an unshaded gap between # and Artist.
        self.setRootIsDecorated(False)
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

    def selected_items_in_order(self):
        """Selected rows top to bottom, as shown (selectedItems() is in click order)."""
        return sorted(self.selectedItems(), key=lambda item: self.indexFromItem(item).row())

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
            
        selected = [item.text(HEADER_INDEX['Path']) for item in self.selected_items_in_order()
                    if item.text(HEADER_INDEX['Path'])]
        if not selected:
            return
        # Drag every selected file that exists (e.g. into Traktor, Explorer or the other panel)
        files = [path for path in selected if os.path.exists(path)]
        if not files:
            self.parent_app.status_bar.showMessage(f"File not found: {selected[0]}")

        drag = QDrag(self)
        mime_data = QMimeData()
        # File URLs are what make the drag work with external apps; the app itself reads
        # TRACKS_MIME, so rows of missing files can still be moved within the app.
        mime_data.setUrls([QUrl.fromLocalFile(path) for path in files])
        mime_data.setData(TRACKS_MIME, '\n'.join(selected).encode('utf-8'))
        drag.setMimeData(mime_data)
        result = drag.exec_(Qt.CopyAction)

        if not files:
            return
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
    """The List view. Files dropped from outside are imported; a Browser entry dropped here
    is shown (its tracks only)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.selectionModel().selectionChanged.connect(self.handle_selection_feedback)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(NODE_MIME):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        elif event.source() is self:
            event.ignore()  # rows dragged onto their own list: nothing to do
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        node = dragged_node(event.mimeData())
        if node is None:
            super().dropEvent(event)
            return
        self.parent_app.show_list_source(node)
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def handle_selection_feedback(self, selected, deselected):
        items = self.selectedItems()
        if not items:
            return
        path = items[0].text(HEADER_INDEX['Path'])
        missing = not path or not os.path.isfile(path)
        self.parent_app.status_bar.setStyleSheet(status_style('error') if missing else '')
        self.parent_app.status_bar.showMessage(f'File not found: {path}' if missing else '')


class PlaylistTreeWidget(AudioDropMixin, DraggableTreeWidget):
    """The Playlist tab, in play order. Rows dragged within it move; rows from the List are
    inserted where they are dropped; a playlist or smartlist from the Browser is loaded."""
    playlist_drop = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._drop_row = None  # where the insertion line is drawn during a drag

    def _internal(self, event):
        return event.source() in (self, self.parent_app.candidate_tree) and bool(dragged_tracks(event.mimeData()))

    def row_at(self, pos):
        """Insertion row for a drop at this viewport position: before or after the row under it."""
        item = self.itemAt(pos)
        if item is None:
            return self.topLevelItemCount()
        row = self.indexOfTopLevelItem(item)
        return row + 1 if pos.y() > self.visualItemRect(item).center().y() else row

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(NODE_MIME) or self._internal(event):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)
        row = self.row_at(event.pos()) if event.isAccepted() and self._internal(event) else None
        if row != self._drop_row:
            self._drop_row = row
            self.viewport().update()

    def dragLeaveEvent(self, event):
        self._drop_row = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._drop_row = None
        self.viewport().update()
        node = dragged_node(event.mimeData())
        if node is not None:
            self.parent_app.load_into_playlist(node)
        elif event.source() is self and self._internal(event):
            self.move_selected(self.row_at(event.pos()))
        elif self._internal(event):
            self.parent_app.add_paths_to_playlist(dragged_tracks(event.mimeData()), self.row_at(event.pos()))
        else:
            super().dropEvent(event)
            return
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def move_selected(self, row):
        """Move the selected rows, keeping their order, to insertion row `row`."""
        items = self.selected_items_in_order()
        if not items:
            return
        row -= sum(self.indexOfTopLevelItem(item) < row for item in items)
        for item in items:
            self.takeTopLevelItem(self.indexOfTopLevelItem(item))
        for offset, item in enumerate(items):
            self.insertTopLevelItem(row + offset, item)
            item.setSelected(True)
        self.parent_app.playlist_changed()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_row is None:
            return
        count = self.topLevelItemCount()
        if count == 0:
            y = 0
        elif self._drop_row < count:
            y = self.visualItemRect(self.topLevelItem(self._drop_row)).top()
        else:
            y = self.visualItemRect(self.topLevelItem(count - 1)).bottom()
        painter = QPainter(self.viewport())
        painter.setPen(QPen(self.palette().highlight().color(), 2))
        painter.drawLine(0, y, self.viewport().width(), y)
        painter.end()
