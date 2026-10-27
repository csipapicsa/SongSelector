"""Similarity map: every track of the (filtered) library as a dot; similar tracks lie close.

- Positions come from core.similarity.tsne_layout, computed in a background thread and
  cached in embeddings.sqlite. Tracks analysed later are placed next to their most
  similar tracks (place_new) until the map is re-arranged.
- The map shows the rows the library list currently shows (same search and filters),
  and reads their table texts, so keys are tempo-adjusted exactly as in the list.
- "Closest matches" are exact (cosine similarity of the full vectors), because any 2D
  map distorts distances.
"""
import os
import threading
from html import escape
from dataclasses import dataclass, field

import numpy as np
from PyQt5.QtCore import QMimeData, QObject, QPointF, QRectF, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QDrag, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QGraphicsEllipseItem,
                             QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene,
                             QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QMenu,
                             QPushButton, QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

from traktor_key_calculator.config import COLOR_MAPPING_CATEGORY
from traktor_key_calculator.core.harmonic import MIX_TYPES, MIX_TYPES_BY_NAME, mix_type
from traktor_key_calculator.core.similarity import (EDGE_SAME_COLOR, EDGE_SAME_RATING, display_color,
                                                    nearest, place_new, track_vectors,
                                                    tsne_layout)

DEFAULT_HOVER_FIELDS = ['Artist', 'Title', 'Genre', 'Comment', 'Color - Song Selector',
                        'Rating - Song Selector', 'Color', 'Rating']
DEFAULT_EDGES = ['perfect_mix', 'plus_1_mix', 'minus_1_mix', 'energy_boost']
SCENE_SIZE = 1000.0          # the map is scaled to about this many scene units
DOT_SIZE = 9                 # pixels, independent of zoom
MAX_EDGES = 2500             # "between all visible tracks" is capped to stay readable
SUGGESTIONS = 15
NO_COLOR = QColor('#8a8f98')
SELECTED_RING, MATCH_RING, PREVIEW_RING = '#ffffff', '#40e0ff', '#ffb020'
PATH_ROLE = Qt.UserRole + 1    # file path of a closest-match row (for dragging)
SORT_ROLE = Qt.UserRole + 2    # value a closest-match column sorts by (number or text)
EDGE_COLORS = {
    'perfect_mix': '#4cd964', 'plus_1_mix': '#5ac8fa', 'minus_1_mix': '#5ac8fa',
    'scale_change': '#af7ff2', 'energy_boost': '#ff9f0a', 'mood_shifter': '#ff6fae',
    'jaws_mix': '#ffd60a', 'diagonal_mix': '#a0a4ab', EDGE_SAME_COLOR: None, EDGE_SAME_RATING: '#e5e5ea',
}
EDGE_LABELS = {**{mix.name: mix.label for mix in MIX_TYPES},
               EDGE_SAME_COLOR: 'Same colour', EDGE_SAME_RATING: 'Same rating'}


@dataclass
class MapData:
    keys: list = field(default_factory=list)                         # analysed tracks (path_key)
    vectors: np.ndarray = field(default_factory=lambda: np.zeros((0, 4096), np.float32))
    positions: dict = field(default_factory=dict)                    # path_key -> (x, y)

    def __post_init__(self):
        self.row = {key: index for index, key in enumerate(self.keys)}


def build_map_data(store, rearrange=False, should_stop=lambda: False):
    """Load embeddings, compute vectors and positions; None if stopped. Slow: run in a thread."""
    matrices = store.load_many()
    keys = sorted(matrices)
    vectors = track_vectors([matrices[key] for key in keys])
    stored = {} if rearrange else store.load_layout()
    placed = [key for key in keys if key in stored]
    if len(keys) >= 3 and len(placed) < len(keys) / 2:
        points = tsne_layout(vectors, should_stop=should_stop)  # first map, or mostly new tracks
        if points is None:
            return None
        positions = {key: tuple(point) for key, point in zip(keys, points)}
    else:
        positions = {key: stored[key] for key in placed}
        new = [key for key in keys if key not in stored]
        if new and placed:
            index = {key: i for i, key in enumerate(keys)}
            points = place_new(np.array([positions[key] for key in placed]),
                               vectors[[index[key] for key in placed]], vectors[[index[key] for key in new]])
            positions.update({key: tuple(point) for key, point in zip(new, points)})
    if positions != stored:
        store.save_layout(positions)
    return MapData(keys, vectors, positions)


def shown_fields(fields, names):
    """(name, text) pairs worth showing: non-empty, and colour 0 ("no colour") left out."""
    return [(name, fields[name]) for name in names
            if fields.get(name) and not (name in ('Color', 'Color - Song Selector') and fields[name] == '0')]


class _Loader(QObject):
    done = pyqtSignal(object)


class DotItem(QGraphicsEllipseItem):
    def __init__(self, key, owner):
        super().__init__(-DOT_SIZE / 2, -DOT_SIZE / 2, DOT_SIZE, DOT_SIZE)
        self.key, self.owner = key, owner
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)  # same pixel size at any zoom
        self.setAcceptHoverEvents(True)
        self.setZValue(1)

    def mousePressEvent(self, event):
        self.owner.select(self.key)
        self._press = event.screenPos() if event.button() == Qt.LeftButton else None
        if event.button() == Qt.RightButton:
            self.owner.request_context_menu.emit(self.key, event.screenPos())
        event.accept()

    def mouseMoveEvent(self, event):
        press = getattr(self, '_press', None)
        if press is not None and (event.screenPos() - press).manhattanLength() >= QApplication.startDragDistance():
            self._press = None
            self.owner.drag_files([self.key])

    def mouseDoubleClickEvent(self, event):
        self.owner.request_add_to_playlist.emit(self.key)
        event.accept()


class MatchItem(QTreeWidgetItem):
    """Sorts by SORT_ROLE: similarity as a number, mix by strength, names case-insensitively."""

    def __lt__(self, other):
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        mine, theirs = self.data(column, SORT_ROLE), other.data(column, SORT_ROLE)
        if mine is None or theirs is None:
            return self.text(column).casefold() < other.text(column).casefold()
        return mine < theirs


class MatchList(QTreeWidget):
    """Closest matches; rows can be dragged out as files (e.g. into Traktor)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Click a column header to sort; click again to reverse. Default: most similar first.
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.DescendingOrder)

    def mimeTypes(self):
        return ['text/uri-list']

    def mimeData(self, items):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in (item.data(0, PATH_ROLE) for item in items)
                      if path and os.path.exists(path)])
        return mime

    def supportedDropActions(self):
        return Qt.CopyAction


class MapView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)

    def wheelEvent(self, event):
        factor = 1.2 ** (event.angleDelta().y() / 120)
        self.scale(factor, factor)


class SimilarityMapWidget(QWidget):
    request_context_menu = pyqtSignal(str, object)    # path_key, global position
    request_add_to_playlist = pyqtSignal(str)          # path_key
    selected = pyqtSignal(str)                         # path_key

    def __init__(self, store, settings, parent=None):
        super().__init__(parent)
        self.store, self.settings = store, settings
        self.data = None
        self.fields = {}          # path_key -> {column: text} of the rows the list shows
        self.dots = {}
        self.selected_key = None
        self.preview_key = None   # a closest match clicked in the list: ringed, not selected
        self.match_keys = []      # closest matches of the selected track, ringed on the map
        self._base_status = ''
        self._loading = False
        self._stop = threading.Event()
        self._loader = _Loader()
        self._loader.done.connect(self._loaded)

        self.scene = QGraphicsScene(self)
        self.view = MapView(self.scene)
        self.edge_items = []
        # Label next to the selected dot: artist - title, key and BPM at the current tempo.
        self.label = QGraphicsRectItem()
        self.label.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.label.setBrush(QBrush(QColor(20, 22, 25, 225)))
        self.label.setPen(QPen(QColor(SELECTED_RING), 1))
        self.label.setZValue(10)
        self.label_text = QGraphicsSimpleTextItem(self.label)
        self.label_text.setBrush(QBrush(QColor('#f0f0f0')))
        self.label.hide()
        self.scene.addItem(self.label)

        self.status = QLabel('')
        self.edges_button = QToolButton()
        self.edges_button.setText('Edges')
        self.edges_button.setPopupMode(QToolButton.InstantPopup)
        edges_menu = QMenu(self.edges_button)
        self.edge_actions = {}
        for name, label in EDGE_LABELS.items():
            action = edges_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(name in settings.get('Map edges', DEFAULT_EDGES))
            action.toggled.connect(self._edges_changed)
            self.edge_actions[name] = action
        self.edges_button.setMenu(edges_menu)
        self.all_edges = QCheckBox('Edges between all visible tracks')
        self.all_edges.setToolTip('Otherwise edges start at the selected track only.')
        self.all_edges.setChecked(settings.get('Map edges between all', False))
        self.all_edges.toggled.connect(self._edges_changed)
        self.harmonic_only = QCheckBox('Closest matches: harmonic only')
        self.harmonic_only.setChecked(settings.get('Map harmonic only', False))
        self.harmonic_only.toggled.connect(self._update_suggestions)
        fit = QPushButton('Fit')
        fit.clicked.connect(self.fit)
        self.rearrange_button = QPushButton('Re-arrange map')
        self.rearrange_button.setToolTip('Compute the map again from all analysed tracks (takes a few minutes).')
        self.rearrange_button.clicked.connect(lambda: self.load(rearrange=True))

        self.details = QLabel('Click a track on the map.')
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.suggestions = MatchList()
        self.suggestions.setHeaderLabels(['Similarity', 'Mix', 'Artist', 'Title'])
        self.suggestions.setRootIsDecorated(False)
        # Clicking a match shows where it is but keeps the selected track selected.
        self.suggestions.itemClicked.connect(lambda item: self.preview(item.data(0, Qt.UserRole)))
        self.suggestions.itemDoubleClicked.connect(
            lambda item: self.request_add_to_playlist.emit(item.data(0, Qt.UserRole)))

        bar = QHBoxLayout()
        for widget in (self.edges_button, self.all_edges, self.harmonic_only):
            bar.addWidget(widget)
        bar.addStretch()
        bar.addWidget(fit)
        bar.addWidget(self.rearrange_button)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(self.details)
        side_layout.addWidget(QLabel('Closest matches (click: show on map, double-click: add to\n'
                                     'playlist, drag: to Traktor or Explorer)'))
        side_layout.addWidget(self.suggestions)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.view)
        splitter.addWidget(side)
        splitter.setSizes([700, 300])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(splitter, 1)  # the map gets all spare space
        layout.addWidget(self.status)

    # -- data ---------------------------------------------------------------

    def load(self, rearrange=False):
        """(Re)compute map data in the background; the view keeps working meanwhile."""
        if self._loading:
            return
        self._loading = True
        self.rearrange_button.setEnabled(False)
        self.status.setText('Arranging the map... (similar tracks are being placed close together)'
                            if rearrange or self.data is None else 'Updating the map...')
        self._stop.clear()

        def work():
            try:
                result = build_map_data(self.store, rearrange, self._stop.is_set)
            except Exception as error:  # e.g. database busy: report, keep the old map
                result = error
            self._loader.done.emit(result)
        threading.Thread(target=work, name='similarity-map', daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loaded(self, result):
        self._loading = False
        self.rearrange_button.setEnabled(True)
        if isinstance(result, Exception):
            self.status.setText(f'Could not build the map: {result}')
            return
        if result is None:
            return
        first = self.data is None
        self.data = result
        self._rebuild_dots()
        if first:
            self.fit()

    def set_tracks(self, fields):
        """The rows the library list shows now: {path_key: {column: text}}."""
        self.fields = fields
        if self.data is not None:
            self._refresh()

    # -- drawing ------------------------------------------------------------

    def _scaled(self, key):
        x, y = self.data.positions[key]
        return QPointF(x * self._scale, y * self._scale)

    def _rebuild_dots(self):
        for dot in self.dots.values():
            self.scene.removeItem(dot)
        self.dots = {}
        points = np.array(list(self.data.positions.values()) or [(0, 0)])
        spread = float(np.ptp(points, axis=0).max()) or 1.0
        self._scale = SCENE_SIZE / spread
        for key in self.data.positions:
            dot = DotItem(key, self)
            dot.setPos(self._scaled(key))
            self.scene.addItem(dot)
            self.dots[key] = dot
        margin = SCENE_SIZE * 0.05
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-margin, -margin, margin, margin))
        self._refresh()

    def _refresh(self):
        hover = self.settings.get('Map hover fields', DEFAULT_HOVER_FIELDS)
        shown = 0
        for key, dot in self.dots.items():
            fields = self.fields.get(key)
            dot.setVisible(fields is not None)
            if fields is None:
                continue
            shown += 1
            colour = COLOR_MAPPING_CATEGORY.get(display_color(fields)) or NO_COLOR
            dot.setBrush(QBrush(colour))
            self._outline(key)
            dot.setToolTip('\n'.join(f'{name}: {text}' for name, text in shown_fields(fields, hover)))
        missing = len(self.fields) - shown
        self._base_status = (f'{shown} tracks on the map' +
                             (f'; {missing} listed tracks are not analysed yet' if missing > 0 else '') +
                             '. Scroll: zoom, drag background: move, drag dot: file to Traktor, '
                             'hover: details, click: closest matches.')
        if self.selected_key not in self.fields:
            self.selected_key = None
        self._draw_edges()
        self._update_suggestions()
        self._show_selected_details()

    def fit(self):
        visible = [dot for dot in self.dots.values() if dot.isVisible()] or list(self.dots.values())
        if visible:
            xs = [dot.pos().x() for dot in visible]
            ys = [dot.pos().y() for dot in visible]
            rect = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            margin = max(rect.width(), rect.height(), 1) * 0.05
            self.view.fitInView(rect.adjusted(-margin, -margin, margin, margin), Qt.KeepAspectRatio)

    def select(self, key):
        if key is None or key not in self.dots:
            return
        previous, self.selected_key = self.selected_key, key
        preview, self.preview_key = self.preview_key, None
        for changed in (previous, preview, key):
            self._outline(changed)
        self._draw_edges()
        self._update_suggestions()
        self._show_selected_details()
        self.selected.emit(key)

    def preview(self, key):
        """Ring a closest match on the map and bring it into view; the selection stays."""
        previous, self.preview_key = self.preview_key, key
        for changed in (previous, key):
            self._outline(changed)
        if key in self.dots:
            self.view.ensureVisible(QRectF(self.dots[key].pos(), self.dots[key].pos()).adjusted(-40, -40, 40, 40))

    def _show_selected_details(self):
        fields = self.fields.get(self.selected_key)
        if fields is None or self.selected_key not in self.dots:
            self.label.hide()
            self.details.setText('Click a track on the map.')
            return
        key_now = f"{fields.get('New Key', '')} ({fields.get('Camelot Key New', '')})"
        self.label_text.setText(f"{fields.get('Artist', '')} - {fields.get('Title', '')}\n"
                                f"{key_now} at master tempo, {fields.get('Original BPM', '')} BPM")
        # The label ignores zoom, so these offsets are pixels: right of and above the dot.
        text_box = self.label_text.boundingRect()
        top = -(text_box.height() + 8) - DOT_SIZE
        self.label.setRect(QRectF(DOT_SIZE, top, text_box.width() + 12, text_box.height() + 8))
        self.label_text.setPos(DOT_SIZE + 6, top + 4)
        self.label.setPos(self.dots[self.selected_key].pos())
        self.label.show()
        hover = self.settings.get('Map hover fields', DEFAULT_HOVER_FIELDS)
        rows = ''.join(f'<tr><td><i>{name}</i></td><td>{escape(text)}</td></tr>'
                       for name, text in shown_fields(fields, hover))
        self.details.setText(f'<b>{escape(fields.get("Artist", ""))} - {escape(fields.get("Title", ""))}</b><br>'
                             f'Key now: {escape(key_now)}, {escape(fields.get("Original BPM", ""))} BPM'
                             f'<table cellspacing="4">{rows}</table>')

    def drag_files(self, keys):
        """Drag the files of these tracks out of the map (Traktor, Explorer, the playlist)."""
        paths = [self.fields.get(key, {}).get('Path', '') for key in keys]
        paths = [path for path in paths if path and os.path.exists(path)]
        if not paths:
            self.status.setText('File not found, nothing to drag.')
            return Qt.IgnoreAction
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        drag = QDrag(self.view)
        drag.setMimeData(mime)
        return drag.exec_(Qt.CopyAction)

    def _outline(self, key):
        """Selected track: white ring on top; its closest matches: cyan ring; others: thin dark edge."""
        dot = self.dots.get(key)
        if dot is None:
            return
        if key == self.selected_key:
            dot.setPen(QPen(QColor(SELECTED_RING), 3))
            dot.setZValue(4)
        elif key == self.preview_key:
            dot.setPen(QPen(QColor(PREVIEW_RING), 3))
            dot.setZValue(3.5)
        elif key in self.match_keys:
            dot.setPen(QPen(QColor(MATCH_RING), 2.5))
            dot.setZValue(3)
        else:
            dot.setPen(QPen(QColor(20, 20, 20, 160), 1))
            dot.setZValue(1)

    def criteria(self):
        return {name for name, action in self.edge_actions.items() if action.isChecked()}

    def _edges_changed(self, _checked=False):
        self.settings['Map edges'] = sorted(self.criteria())
        self.settings['Map edges between all'] = self.all_edges.isChecked()
        self._draw_edges()

    def _edges(self, criteria):
        """[(source, target, reason)] for the visible dots, at most MAX_EDGES.

        Tracks are grouped by tempo-adjusted Camelot key, colour and rating, so matches are
        looked up instead of comparing every pair (thousands of tracks stay fast).
        """
        visible = [key for key, dot in self.dots.items() if dot.isVisible()]
        sources = visible if self.all_edges.isChecked() else \
            ([self.selected_key] if self.selected_key in visible else [])
        by_key, by_colour, by_rating = {}, {}, {}
        for key in visible:
            fields = self.fields[key]
            by_key.setdefault(str(fields.get('Camelot Key New', '')).upper(), []).append(key)
            by_colour.setdefault(display_color(fields), []).append(key)
            by_rating.setdefault(fields.get('Rating - Song Selector') or fields.get('Rating') or '', []).append(key)
        edges, seen = [], set()
        for source in sources:
            fields = self.fields[source]
            candidates = []
            for target_key, targets in by_key.items():
                mix = mix_type(fields.get('Camelot Key New'), target_key)
                if mix is not None and mix.name in criteria:
                    candidates += [(target, mix.name) for target in targets]
            if EDGE_SAME_COLOR in criteria and display_color(fields):
                candidates += [(target, EDGE_SAME_COLOR) for target in by_colour[display_color(fields)]]
            rating = fields.get('Rating - Song Selector') or fields.get('Rating') or ''
            if EDGE_SAME_RATING in criteria and rating:
                candidates += [(target, EDGE_SAME_RATING) for target in by_rating[rating]]
            for target, reason in candidates:
                pair = frozenset((source, target))
                if target == source or pair in seen:
                    continue  # one edge per pair, strongest reason first
                seen.add(pair)
                edges.append((source, target, reason))
                if len(edges) >= MAX_EDGES:
                    return edges
        return edges

    def _draw_edges(self):
        for item in self.edge_items:
            self.scene.removeItem(item)
        self.edge_items = []
        criteria = self.criteria()
        self.status.setText(self._base_status)
        if not criteria or self.data is None:
            return
        paths = {}
        edges = self._edges(criteria)
        for source, target, reason in edges:
            if reason == EDGE_SAME_COLOR:
                colour = (COLOR_MAPPING_CATEGORY.get(display_color(self.fields[source])) or NO_COLOR).name()
            else:
                colour = EDGE_COLORS[reason]
            path = paths.setdefault((reason, colour), QPainterPath())
            path.moveTo(self._scaled(source))
            path.lineTo(self._scaled(target))
        if len(edges) >= MAX_EDGES:
            self.status.setText(f'Showing the first {MAX_EDGES} edges; filter the list to see fewer tracks. '
                                + self._base_status)
        for (reason, colour), path in paths.items():
            weight = MIX_TYPES_BY_NAME[reason].weight if reason in MIX_TYPES_BY_NAME else 4
            pen = QPen(QColor(colour), 0.6 + weight / 5)
            pen.setCosmetic(True)                      # constant width at any zoom
            colour_alpha = QColor(colour)
            colour_alpha.setAlpha(170 if not self.all_edges.isChecked() else 90)
            pen.setColor(colour_alpha)
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(0)
            self.scene.addItem(item)
            self.edge_items.append(item)

    def _update_suggestions(self, _checked=False):
        self.settings['Map harmonic only'] = self.harmonic_only.isChecked()
        self.suggestions.clear()
        previous, self.match_keys = self.match_keys, []
        preview, self.preview_key = self.preview_key, None
        for key in previous + [preview]:
            self._outline(key)
        if self.data is None or self.selected_key not in self.data.row:
            return
        visible = [self.data.row[key] for key, dot in self.dots.items()
                   if dot.isVisible() and key in self.data.row]
        source = self.fields.get(self.selected_key, {})
        added = 0
        for row, score in nearest(self.data.vectors, self.data.row[self.selected_key], count=len(visible), among=visible):
            key = self.data.keys[row]
            target = self.fields.get(key, {})
            mix = mix_type(source.get('Camelot Key New'), target.get('Camelot Key New'))
            if self.harmonic_only.isChecked() and mix is None:
                continue
            item = MatchItem([f'{score * 100:.0f} %', mix.label if mix else '',
                              target.get('Artist', ''), target.get('Title', '')])
            item.setData(0, SORT_ROLE, score)
            item.setData(1, SORT_ROLE, mix.weight if mix else 0)
            item.setData(2, SORT_ROLE, target.get('Artist', '').casefold())
            item.setData(3, SORT_ROLE, target.get('Title', '').casefold())
            item.setData(0, Qt.UserRole, key)
            item.setData(0, PATH_ROLE, target.get('Path', ''))
            if mix is not None:
                item.setForeground(1, QBrush(QColor(EDGE_COLORS[mix.name])))
            self.suggestions.addTopLevelItem(item)
            self.match_keys.append(key)
            self._outline(key)
            added += 1
            if added >= SUGGESTIONS:
                break
        for column in range(4):
            self.suggestions.resizeColumnToContents(column)
