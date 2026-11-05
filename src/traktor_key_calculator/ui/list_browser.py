"""
list_browser.py
Browser tab, as in Traktor: the track collection (all tracks, by artist, album, genre),
the user's playlists and smartlists, and Traktor's own playlists (read-only).

Every entry is a node {'kind', 'name'}: kind 'all', 'artist', 'album', 'genre',
'playlist', 'smartlist', 'traktor' or 'rekordbox' (track sources; a Traktor or Rekordbox
playlist also has 'path', its folders and name), or 'group' / 'collection' / 'playlists' /
'traktor_root' / 'traktor_folder' / 'rekordbox_root' / 'rekordbox_folder' (folders) or
'traktor_smartlist' / 'rekordbox_smartlist' (listed, not evaluated yet).
The window decides what a node shows; this widget only lists them.
"""
import json

from PyQt5.QtCore import QMimeData, QPoint, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QDrag, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QAbstractItemView, QApplication, QStyle, QTreeWidget, QTreeWidgetItem

from traktor_key_calculator.core.library_store import PLAYLIST, SMARTLIST
from traktor_key_calculator.ui.tree_widgets import NODE_MIME, dragged_tracks, dropped_paths

NODE_ROLE = Qt.UserRole + 1
# Collection folders: node kind -> (folder label, track column)
COLLECTION_GROUPS = {'artist': ('Artists', 'Artist'), 'album': ('Albums', 'Album'), 'genre': ('Genres', 'Genre')}
TRAKTOR = 'traktor'      # a playlist in Traktor's collection.nml
REKORDBOX = 'rekordbox'  # a playlist in Rekordbox's master.db
FOREIGN_KINDS = {TRAKTOR: 'Traktor', REKORDBOX: 'Rekordbox'}  # playlists of other programs, read-only
TRACK_SOURCES = {'all', 'artist', 'album', 'genre', PLAYLIST, SMARTLIST, *FOREIGN_KINDS}
SAVED_KINDS = {PLAYLIST, SMARTLIST}
ORDERED_KINDS = {PLAYLIST, *FOREIGN_KINDS}  # shown in the List in their order (# column)
LOADABLE_KINDS = {PLAYLIST, SMARTLIST, *FOREIGN_KINDS}  # double-click loads into the Playlist tab


def node_label(node):
    """'Playlist: Warm-up', 'Artist: Cat Power', ..."""
    if node['kind'] == 'all':
        return 'All Tracks'
    if node['kind'] in FOREIGN_KINDS:
        return f"{FOREIGN_KINDS[node['kind']]} playlist: {node['name']}"
    return f"{node['kind'].title()}: {node['name']}"


def _glyph_icon(text):
    """Small icon from a character; mid grey, readable on light and dark backgrounds."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setPen(QColor('#8a8f98'))
    font = painter.font()
    font.setPixelSize(14)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


class ListBrowser(QTreeWidget):
    node_selected = pyqtSignal(object)        # a track source was clicked
    node_activated = pyqtSignal(object)       # a playlist or smartlist was double-clicked
    tracks_dropped = pyqtSignal(object, object)  # (playlist node, QMimeData) tracks dropped on a playlist
    menu_requested = pyqtSignal(object, QPoint)  # (node or None, global position)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.values = {kind: {} for kind in COLLECTION_GROUPS}  # kind -> {name: track count}
        self._quiet = False
        folder = self.style().standardIcon(QStyle.SP_DirIcon)
        self.list_icon, self.smart_icon = _glyph_icon('≡'), _glyph_icon('⚙')

        self.collection_root = self._item(self, 'Track Collection', {'kind': 'collection'},
                                          self.style().standardIcon(QStyle.SP_DriveHDIcon))
        self.all_item = self._item(self.collection_root, 'All Tracks', {'kind': 'all', 'name': ''}, self.list_icon)
        self.groups = {}
        for kind, (label, _column) in COLLECTION_GROUPS.items():
            self.groups[kind] = self._item(self.collection_root, label, {'kind': 'group', 'name': kind}, folder)
            self.groups[kind].setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        self.playlists_root = self._item(self, 'Playlists', {'kind': 'playlists'},
                                         self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.traktor_root = self._item(self, 'Traktor Playlists', {'kind': 'traktor_root'},
                                       self.style().standardIcon(QStyle.SP_DirIcon))
        self.traktor_root.setToolTip(0, "Traktor's playlists, read from its collection.nml (read-only). "
                                        'Updated when Traktor saves.')
        self.rekordbox_root = self._item(self, 'Rekordbox Playlists', {'kind': 'rekordbox_root'},
                                         self.style().standardIcon(QStyle.SP_DirIcon))
        self.rekordbox_root.setToolTip(0, "Rekordbox's playlists, read from its library (read-only; Rekordbox is not "
                                          'touched and does not have to be closed). Updated when Rekordbox saves.')
        self.rekordbox_root.setHidden(True)  # shown once a Rekordbox library has been read
        self.roots = {TRAKTOR: self.traktor_root, REKORDBOX: self.rekordbox_root}
        self.collection_root.setExpanded(True)
        self.playlists_root.setExpanded(True)

        self.itemExpanded.connect(self._fill_group)
        self.itemSelectionChanged.connect(self._selection_changed)
        self.itemDoubleClicked.connect(self._double_clicked)
        self.customContextMenuRequested.connect(
            lambda pos: self.menu_requested.emit(self.node_at(pos), self.viewport().mapToGlobal(pos)))

    @staticmethod
    def _item(parent, text, node, icon=None):
        item = QTreeWidgetItem(parent, [text])
        item.setData(0, NODE_ROLE, node)
        if icon is not None:
            item.setIcon(0, icon)
        return item

    @staticmethod
    def node(item):
        return item.data(0, NODE_ROLE) if item is not None else None

    def node_at(self, pos):
        return self.node(self.itemAt(pos))

    def current_node(self):
        return self.node(self.currentItem())

    # -- contents -------------------------------------------------------------

    def set_collection(self, table):
        """Artists, albums and genres of the library list; folders refill when opened."""
        selected = self.current_node()
        for kind, (label, column) in COLLECTION_GROUPS.items():
            values = {}
            if table is not None and column in table:
                for value in table[column].dropna().astype(str).str.strip():
                    if value and value.lower() != 'nan':
                        values[value] = values.get(value, 0) + 1
            self.values[kind] = values
            group = self.groups[kind]
            group.setText(0, f'{label} ({len(values):,})')
            self._quiet = True
            group.takeChildren()
            self._quiet = False
            if group.isExpanded():
                self._fill_group(group)
                if selected and selected['kind'] == kind:
                    self.select_node(selected)

    def _fill_group(self, group):
        node = self.node(group)
        if not node or node['kind'] != 'group' or group.childCount():
            return
        kind = node['name']
        for name in sorted(self.values[kind], key=str.casefold):
            self._item(group, name, {'kind': kind, 'name': name})

    def set_lists(self, lists):
        """[(name, kind)] of saved playlists and smartlists."""
        selected = self.current_node()
        self._quiet = True
        self.playlists_root.takeChildren()
        for name, kind in lists:
            self._item(self.playlists_root, name, {'kind': kind, 'name': name},
                       self.smart_icon if kind == SMARTLIST else self.list_icon)
        self._quiet = False
        if selected and selected['kind'] in SAVED_KINDS:
            self.select_node(selected)

    def set_traktor_playlists(self, playlists):
        """Traktor's playlist tree (TraktorCollection.playlists), in Traktor's order."""
        self.set_foreign_playlists(TRAKTOR, playlists)

    def set_rekordbox_playlists(self, playlists):
        """Rekordbox's playlist tree (RekordboxLibrary.playlists), in Rekordbox's order;
        None: no Rekordbox library, the entry is hidden."""
        self.rekordbox_root.setHidden(playlists is None)
        self.set_foreign_playlists(REKORDBOX, playlists or [])

    def set_foreign_playlists(self, kind, playlists):
        selected = self.current_node()
        root, program = self.roots[kind], FOREIGN_KINDS[kind]
        folder = self.style().standardIcon(QStyle.SP_DirIcon)
        self._quiet = True
        root.takeChildren()

        def add(parent, nodes, path):
            count = 0
            for entry in nodes:
                here = path + [entry['name']]
                if entry['type'] == 'FOLDER':
                    item = self._item(parent, entry['name'], {'kind': f'{kind}_folder', 'path': here}, folder)
                    count += add(item, entry.get('children', []), here)
                elif entry['type'] == 'PLAYLIST':
                    item = self._item(parent, entry['name'], {'kind': kind, 'name': entry['name'], 'path': here},
                                      self.list_icon)
                    item.setToolTip(0, f"{len(entry['tracks'])} tracks")
                    count += 1
                elif entry['type'] == 'SMARTLIST':
                    item = self._item(parent, entry['name'], {'kind': f'{kind}_smartlist', 'path': here},
                                      self.smart_icon)
                    item.setForeground(0, QColor('#8a8f98'))
                    item.setToolTip(0, f"{program} smartlist (not supported yet): {entry.get('query', '')}")
            return count

        count = add(root, playlists, [])
        root.setText(0, f'{program} Playlists ({count})')
        self._quiet = False
        if selected and selected['kind'] == kind:
            self.select_node(selected)

    def _find_foreign(self, kind, path):
        item = self.roots[kind]
        for name in path:
            item = next((item.child(i) for i in range(item.childCount())
                         if (self.node(item.child(i)) or {}).get('path', [])[-1:] == [name]), None)
            if item is None:
                return None
        return item

    def find(self, node):
        if node is None or node['kind'] == 'all':
            return self.all_item
        if node['kind'] in FOREIGN_KINDS:
            return self._find_foreign(node['kind'], node.get('path', []))
        if node['kind'] in SAVED_KINDS:
            parent = self.playlists_root
        elif node['kind'] in self.groups:
            parent = self.groups[node['kind']]
            if not parent.childCount():
                self._fill_group(parent)
        else:
            return None
        for index in range(parent.childCount()):
            child = parent.child(index)
            if self.node(child) == node:
                return child
        return None

    def select_node(self, node):
        """Select an entry without announcing it (the window already shows it)."""
        item = self.find(node)
        self._quiet = True
        if item is None:
            self.clearSelection()
        else:
            if item.parent() is not None:
                item.parent().setExpanded(True)
            self.setCurrentItem(item)
            self.scrollToItem(item)
        self._quiet = False

    # -- interaction ----------------------------------------------------------

    def _selection_changed(self):
        node = self.current_node()
        if not self._quiet and self.currentItem() is not None and self.currentItem().isSelected() \
                and node and node['kind'] in TRACK_SOURCES:
            self.node_selected.emit(node)

    def _double_clicked(self, item, _column):
        node = self.node(item)
        if node and node['kind'] in LOADABLE_KINDS:
            self.node_activated.emit(node)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._press = event.pos()

    def mouseMoveEvent(self, event):
        """Drag an entry to the List view (shows it) or a playlist/smartlist to the Playlist tab."""
        if not (event.buttons() & Qt.LeftButton) or not hasattr(self, '_press'):
            return
        if (event.pos() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        node = self.node_at(self._press)
        if not node or node['kind'] not in TRACK_SOURCES:
            return
        mime = QMimeData()
        mime.setData(NODE_MIME, json.dumps(node).encode('utf-8'))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec_(Qt.CopyAction)

    def _playlist_drop(self, event):
        """The playlist under a drag of tracks (from the List, the Playlist or Explorer), else None."""
        node = self.node_at(event.pos())
        mime = event.mimeData()
        if node and node['kind'] == PLAYLIST and (dragged_tracks(mime) or dropped_paths(mime)):
            return node
        return None

    def dragEnterEvent(self, event):
        # Accepted anywhere, so the drag can move on to a playlist entry
        if dragged_tracks(event.mimeData()) or dropped_paths(event.mimeData()):
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._playlist_drop(event):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        node = self._playlist_drop(event)
        if node is None:
            event.ignore()
            return
        self.tracks_dropped.emit(node, event.mimeData())
        event.setDropAction(Qt.CopyAction)
        event.accept()
