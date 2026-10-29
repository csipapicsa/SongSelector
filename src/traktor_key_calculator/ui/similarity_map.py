"""Similarity map: every track of the (filtered) library as a dot; similar tracks lie close.

- Positions come from core.similarity.tsne_layout, computed in a background thread and
  cached in embeddings.sqlite. Tracks analysed later are placed next to their most
  similar tracks (place_new) until the map is re-arranged.
- The map shows the rows the library list currently shows (same search and filters),
  and reads their table texts, so keys are tempo-adjusted exactly as in the list.
- "Closest matches" are exact (cosine similarity of the full vectors), because any 2D
  map distorts distances.
- Edges go only to the N most similar partners of a track; weaker similarity is drawn more
  transparent. Dots can be coloured by unsupervised groups (core.clustering) instead of
  the Traktor colour.
"""
import os
import threading
from html import escape
from dataclasses import dataclass, field

import numpy as np
from PyQt5.QtCore import QMimeData, QObject, QPointF, QRectF, Qt, QUrl, QVariantAnimation, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QDrag, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
                             QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem,
                             QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel,
                             QMenu, QPushButton, QSizePolicy, QSpinBox, QSplitter, QToolButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from traktor_key_calculator.config import (COLOR_MAPPING_CATEGORY, HEADER_LABELS, SS_COLOR_COLUMN,
                                           SS_RATING_COLUMN)
from traktor_key_calculator.core.search_filters import NUMERIC_COLUMNS
from traktor_key_calculator.ui.delegates import ColorDotDelegate, StarRatingDelegate, stars
from traktor_key_calculator.core.clustering import GROUPING_BY_NAME, GROUPING_METHODS, group_tracks
from traktor_key_calculator.core.harmonic import MIX_TYPES, MIX_TYPES_BY_NAME, mix_type, parse_camelot
from traktor_key_calculator.core.traktor_collection import canonical_path
from traktor_key_calculator.core.similarity import (EDGE_SAME_COLOR, EDGE_SAME_RATING, display_color,
                                                    nearest, place_new, track_vectors,
                                                    tsne_layout)

DEFAULT_HOVER_FIELDS = ['Artist', 'Title', 'Genre', 'Comment', 'Color - Song Selector',
                        'Rating - Song Selector', 'Color', 'Rating']
DEFAULT_EDGES = ['perfect_mix', 'plus_1_mix', 'minus_1_mix', 'energy_boost']
SCENE_SIZE = 1000.0          # the map is scaled to about this many scene units
DOT_SIZE = 9                 # pixels, independent of zoom
GLOW_SIZE = 44               # pixels: pulsing halo around the selected track and a clicked match
MAX_EDGES = 2500             # "between all visible tracks" is capped to stay readable
LINES_PER_TRACK = 20         # default: edges from a track go to its N most similar partners
STRENGTH_LEVELS = 6          # edge opacity steps, weakest to strongest similarity
MATCH_COUNT = 50             # default number of closest matches listed
RINGED_MATCHES = 15          # of those, the most similar get a ring on the map (more would cover it)
# Closest-match columns: the two of the map, then the library list's (chosen by right-clicking the header).
MATCH_COLUMNS = ['Similarity', 'Mix'] + HEADER_LABELS
DEFAULT_MATCH_COLUMNS = ['Similarity', 'Mix', 'Artist', 'Title']
SIDE_MIN_WIDTH = 220         # pixels: the details and closest matches never collapse
NO_COLOR = QColor('#8a8f98')
UNGROUPED = QColor('#4a4e55')  # "Map density" leaves tracks in thin areas without a group
# Distinct colours for groups 1, 2, ... (largest first); no magenta, white or grey, which mark
# the clicked match, the selection and ungrouped tracks. Smaller groups beyond these are grey.
GROUP_COLOURS = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0',
                 '#bcf60c', '#fabebe', '#008080', '#e6beff', '#9a6324', '#fffac8', '#800000',
                 '#aaffc3', '#808000', '#ffd8b1']
# The clicked match is magenta: no Traktor colour is, so it stands out on orange/yellow-heavy maps.
SELECTED_RING, MATCH_RING, PREVIEW_RING = '#ffffff', '#40e0ff', '#ff2bd6'
EDGE_ALPHA_SELECTED, EDGE_ALPHA_PREVIEW, EDGE_ALPHA_ALL = 170, 85, 90   # a clicked match's edges: half
NO_KEY_TEXT = 'no key'       # Mix column when either track has no key in Traktor
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
    """(name, text) pairs worth showing: non-empty, colour 0 ("no colour") and rating 0
    ("unrated") left out; ratings as stars."""
    zero_means_none = ('Color', SS_COLOR_COLUMN, 'Rating', SS_RATING_COLUMN)
    shown = [(name, fields[name]) for name in names
             if fields.get(name) and not (name in zero_means_none and fields[name] == '0')]
    return [(name, stars(text, text) if name in ('Rating', SS_RATING_COLUMN) else text) for name, text in shown]


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


class Halo(QGraphicsEllipseItem):
    """Pulsing glow behind a dot, so it stands out on a busy map (same pixel size at any zoom)."""

    def __init__(self, colour, z, animation_parent):
        super().__init__(-GLOW_SIZE / 2, -GLOW_SIZE / 2, GLOW_SIZE, GLOW_SIZE)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setAcceptedMouseButtons(Qt.NoButton)  # clicks reach the dots underneath
        gradient = QRadialGradient(0, 0, GLOW_SIZE / 2)
        for stop, alpha in ((0, 240), (0.3, 170), (1, 0)):
            shade = QColor(colour)
            shade.setAlpha(alpha)
            gradient.setColorAt(stop, shade)
        self.setBrush(QBrush(gradient))
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(z)
        self.hide()
        self.pulse = QVariantAnimation(animation_parent)
        self.pulse.setDuration(1200)
        self.pulse.setLoopCount(-1)
        for step, scale in ((0, 0.75), (0.5, 1.25), (1, 0.75)):
            self.pulse.setKeyValueAt(step, scale)
        self.pulse.valueChanged.connect(self.setScale)

    def follow(self, dot):
        """Glow behind this dot; hidden when there is none or it is filtered out."""
        if dot is not None and dot.isVisible():
            self.setPos(dot.pos())
            self.show()
            self.pulse.start()
        else:
            self.pulse.stop()
            self.hide()


def _sort_value(name, text):
    """What a closest-match column sorts by: numbers as numbers (blank first), else the text."""
    if name in NUMERIC_COLUMNS:
        try:
            return float(text)
        except ValueError:
            return -1.0
    return text.casefold()


class MatchItem(QTreeWidgetItem):
    """Sorts by SORT_ROLE: similarity as a number, mix by strength, names case-insensitively."""

    def __lt__(self, other):
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        mine, theirs = self.data(column, SORT_ROLE), other.data(column, SORT_ROLE)
        if mine is None or theirs is None:
            return self.text(column).casefold() < other.text(column).casefold()
        return mine < theirs


class MatchList(QTreeWidget):
    """Closest matches; rows can be dragged out as files (e.g. into Traktor). Right-click the
    header to choose the columns."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setHeaderLabels(MATCH_COLUMNS)
        self.color_delegate, self.star_delegate = ColorDotDelegate(self), StarRatingDelegate(self)
        for name in ('Color', SS_COLOR_COLUMN):
            self.setItemDelegateForColumn(MATCH_COLUMNS.index(name), self.color_delegate)
        for name in ('Rating', SS_RATING_COLUMN):
            self.setItemDelegateForColumn(MATCH_COLUMNS.index(name), self.star_delegate)
        shown = settings.get('Map match columns', DEFAULT_MATCH_COLUMNS)
        for column, name in enumerate(MATCH_COLUMNS):
            self.setColumnHidden(column, name not in shown)
        self.header().setContextMenuPolicy(Qt.CustomContextMenu)
        self.header().customContextMenuRequested.connect(self._column_menu)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Click a column header to sort; click again to reverse. Default: most similar first.
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.DescendingOrder)

    def _column_menu(self, pos):
        menu = QMenu(self)
        for column, name in enumerate(MATCH_COLUMNS):
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(not self.isColumnHidden(column))
            action.toggled.connect(lambda checked, column=column: self.show_column(column, checked))
        menu.exec_(self.header().mapToGlobal(pos))

    def show_column(self, column, shown):
        self.setColumnHidden(column, not shown)
        if shown:
            self.resizeColumnToContents(column)
        self.settings['Map match columns'] = [name for index, name in enumerate(MATCH_COLUMNS)
                                              if not self.isColumnHidden(index)]

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
    dropped = pyqtSignal(list)   # file paths dropped on the map (e.g. from the playlist)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setAcceptDrops(True)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)

    def wheelEvent(self, event):
        factor = 1.2 ** (event.angleDelta().y() / 120)
        self.scale(factor, factor)

    # Dropping a track selects it on the map. The view handles drops itself instead of
    # passing them to the scene, whose items do not accept drops.
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = [os.path.normpath(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.dropped.emit(paths)
        else:
            event.ignore()


class SimilarityMapWidget(QWidget):
    request_context_menu = pyqtSignal(str, object)    # path_key, global position
    request_add_to_playlist = pyqtSignal(str)          # path_key
    selected = pyqtSignal(str)                         # path_key

    def __init__(self, store, settings, parent=None):
        super().__init__(parent)
        self.store, self.settings = store, settings
        self.data = None
        self.listed = {}          # path_key -> {column: text} of the rows the list shows
        self.fields = {}          # listed rows plus the reference track, if any
        # A track dropped on the map that the list does not show (e.g. a playlist track):
        # shown and selected anyway, so its closest matches can be explored. (key, fields)
        self.reference = None
        # key -> {column: text} for any library or playlist track; set by the main window.
        self.fields_provider = lambda key: None
        # path_keys of the playlist tracks (set by the main window): italic in the closest matches.
        self.playlist_keys = lambda: set()
        self.dots = {}
        self.selected_key = None
        self.preview_key = None   # a closest match clicked in the list: glows, the selection stays
        self.groups = {}          # path_key -> group (0 = largest, -1 = none) while grouping is on
        self._group_request = 0   # only the latest grouping result is used
        self._grouper = _Loader()
        self._grouper.done.connect(self._grouped)
        self.match_keys = []      # closest matches of the selected track, ringed on the map
        self._base_status = ''
        self._loading = False
        self._stop = threading.Event()
        self._loader = _Loader()
        self._loader.done.connect(self._loaded)

        self.scene = QGraphicsScene(self)
        self.view = MapView(self.scene)
        self.view.dropped.connect(self.drop_paths)
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
        # Glows behind the selected track (white) and a clicked closest match (magenta).
        self.selected_glow = Halo(SELECTED_RING, 3.9, self)
        self.preview_glow = Halo(PREVIEW_RING, 3.4, self)
        for halo in (self.selected_glow, self.preview_glow):
            self.scene.addItem(halo)

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
        self.lines_per_track = QSpinBox()
        self.lines_per_track.setRange(1, 500)
        self.lines_per_track.setPrefix('to the ')
        self.lines_per_track.setSuffix(' most similar')
        self.lines_per_track.setToolTip('Edges from a track go only to this many partners: those that sound most\n'
                                        'similar. The more similar, the more opaque the line.')
        self.lines_per_track.setValue(settings.get('Map lines per track', LINES_PER_TRACK))
        self.lines_per_track.setKeyboardTracking(False)
        self.lines_per_track.valueChanged.connect(self._edges_changed)
        self.all_edges = QCheckBox('Edges between all visible tracks')
        self.all_edges.setToolTip('Otherwise edges start at the selected track only.')
        self.all_edges.setChecked(settings.get('Map edges between all', False))
        self.all_edges.toggled.connect(self._edges_changed)
        self.harmonic_only = QCheckBox('Closest matches: harmonic only')
        self.harmonic_only.setToolTip('Tracks without a key in Traktor stay in the list (Mix: "no key"):\n'
                                      'their sound can still match.')
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
        self.suggestions = MatchList(settings)
        self.suggestions.setRootIsDecorated(False)
        # A click highlights the match on the map (the selected track stays); a double-click makes
        # it the selected track. Dragging a match adds it to the playlist or Traktor.
        self.suggestions.itemClicked.connect(lambda item: self.preview(item.data(0, Qt.UserRole)))
        self.suggestions.itemDoubleClicked.connect(lambda item: self.select_and_show(item.data(0, Qt.UserRole)))

        # Grouping: colour the dots by unsupervised groups instead of the Traktor colour.
        self.grouping = QComboBox()
        self.grouping.addItem('Off (Traktor colours)', None)
        for method in GROUPING_METHODS:
            self.grouping.addItem(method.label, method.name)
        self.grouping.setToolTip('k-means: a fixed number of groups from the sound.\n'
                                 'Neighbour communities: tracks linked to their most similar tracks, split\n'
                                 '  where the links are sparse (resolution: higher gives more groups).\n'
                                 'Map density: the clumps visible on the map; thin areas stay grey.')
        self.grouping_parameter = QDoubleSpinBox()
        self.grouping_parameter.setKeyboardTracking(False)
        self.grouping_summary = QLabel('')
        index = self.grouping.findData(settings.get('Map grouping'))
        self.grouping.setCurrentIndex(max(index, 0))
        self._configure_grouping_parameter()
        self.grouping.currentIndexChanged.connect(self._grouping_method_changed)
        self.grouping_parameter.valueChanged.connect(self._update_groups)

        bar = QHBoxLayout()
        for widget in (self.edges_button, self.lines_per_track, self.all_edges, self.harmonic_only):
            bar.addWidget(widget)
        bar.addStretch()
        bar.addWidget(fit)
        bar.addWidget(self.rearrange_button)
        group_bar = QHBoxLayout()
        for widget in (QLabel('Groups:'), self.grouping, self.grouping_parameter, self.grouping_summary):
            group_bar.addWidget(widget)
        group_bar.addStretch()
        side = QWidget()
        side.setMinimumWidth(SIDE_MIN_WIDTH)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(self.details)
        caption = QLabel('Closest matches (click: show on the map, double-click: select, drag: to the '
                         'playlist, Traktor or Explorer; italic: on the playlist)')
        caption.setWordWrap(True)
        side_layout.addWidget(caption)
        self.match_count = QSpinBox()
        self.match_count.setRange(5, 2000)
        self.match_count.setSingleStep(10)
        self.match_count.setPrefix('List the ')
        self.match_count.setSuffix(' closest')
        self.match_count.setToolTip(f'How many closest matches to list; the {RINGED_MATCHES} most similar are '
                                    'ringed on the map.\nRight-click the list header to choose its columns.')
        self.match_count.setValue(settings.get('Map match count', MATCH_COUNT))
        self.match_count.setKeyboardTracking(False)
        self.match_count.valueChanged.connect(self._update_suggestions)
        count_row = QHBoxLayout()
        count_row.addWidget(self.match_count)
        count_row.addStretch()
        side_layout.addLayout(count_row)
        side_layout.addWidget(self.suggestions)
        # Long one-line texts must not set the widget's minimum width: on a narrow window that
        # pushed the map wider than the window, and the splitter collapsed the matches to nothing.
        self.status.setWordWrap(True)
        self.grouping_summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.view)
        self.splitter.addWidget(side)
        self.splitter.setCollapsible(1, False)
        self.splitter.setSizes(settings.get('Map splitter', [700, 300]))
        self.splitter.splitterMoved.connect(lambda *_: self.settings.__setitem__('Map splitter', self.splitter.sizes()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addLayout(group_bar)
        layout.addWidget(self.splitter, 1)  # the map gets all spare space
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
        self._update_groups()

    # -- grouping -----------------------------------------------------------

    def _configure_grouping_parameter(self):
        """The parameter box shows the chosen method's parameter (or hides when grouping is off)."""
        method = GROUPING_BY_NAME.get(self.grouping.currentData())
        self.grouping_parameter.setVisible(method is not None)
        if method is None:
            return
        self.grouping_parameter.blockSignals(True)
        self.grouping_parameter.setDecimals(method.decimals)
        self.grouping_parameter.setRange(method.minimum, method.maximum)
        self.grouping_parameter.setSingleStep(method.step)
        self.grouping_parameter.setPrefix(f'{method.parameter}: ')
        self.grouping_parameter.setValue(self.settings.get('Map grouping parameters', {}).get(method.name, method.default))
        self.grouping_parameter.blockSignals(False)

    def _grouping_method_changed(self, _index=0):
        self._configure_grouping_parameter()
        self._update_groups()

    def _update_groups(self, _value=None):
        """Group all analysed tracks with the chosen method, in a thread (about a second for 3,500)."""
        method = self.grouping.currentData()
        self.settings['Map grouping'] = method
        self._group_request += 1
        if method is None or self.data is None:
            self.grouping_summary.setText('')
            if self.groups:
                self.groups = {}
                self._refresh()
            return
        parameter = self.grouping_parameter.value()
        self.settings.setdefault('Map grouping parameters', {})[method] = parameter
        request, data = self._group_request, self.data
        self.grouping_summary.setText('Grouping...')

        def work():
            try:
                points = np.array([data.positions.get(key, (0, 0)) for key in data.keys])
                labels = group_tracks(method, data.vectors, points, parameter)
                result = dict(zip(data.keys, labels.tolist()))
            except Exception as error:  # report, keep the dots as they are
                result = error
            self._grouper.done.emit((request, result))
        threading.Thread(target=work, name='similarity-groups', daemon=True).start()

    def _grouped(self, answer):
        request, result = answer
        if request != self._group_request:
            return  # the method or parameter changed meanwhile
        if isinstance(result, Exception):
            self.grouping_summary.setText(f'Could not group: {result}')
            return
        self.groups = result
        labels = np.array(list(result.values()))
        sizes = np.bincount(labels[labels >= 0]) if (labels >= 0).any() else np.zeros(0, int)
        summary = f'{len(sizes)} groups of all {len(labels)} analysed tracks'
        if len(sizes):
            summary += f'; largest {sizes[0] / len(labels):.0%}'
        if (labels < 0).any():
            summary += f'; {np.mean(labels < 0):.0%} in no group (dark grey)'
        if len(sizes) > len(GROUP_COLOURS):
            summary += f'; groups after {len(GROUP_COLOURS)} are light grey'
        self.grouping_summary.setText(summary)
        self._refresh()

    def _dot_colour(self, key, fields):
        if not self.groups:
            return COLOR_MAPPING_CATEGORY.get(display_color(fields)) or NO_COLOR
        group = self.groups.get(key, -1)
        if group < 0:
            return UNGROUPED
        return QColor(GROUP_COLOURS[group]) if group < len(GROUP_COLOURS) else NO_COLOR

    def _group_text(self, key):
        """'Group 3' while grouping is on (1 = largest), else ''."""
        if not self.groups:
            return ''
        group = self.groups.get(key, -1)
        return f'Group {group + 1}' if group >= 0 else 'No group'

    def set_tracks(self, fields):
        """The rows the library list shows now: {path_key: {column: text}}."""
        self.listed = fields
        self._merge_reference()
        if self.data is not None:
            self._refresh()

    def _merge_reference(self):
        self.fields = dict(self.listed)
        if self.reference is not None:
            self.fields.setdefault(*self.reference)

    def drop_paths(self, paths):
        """Select the first dropped track that is on the map (analysed)."""
        for path in paths:
            key = canonical_path(path)
            if self.data is not None and key in self.dots:
                fields = self.fields.get(key) or self.fields_provider(key) or \
                    {'Title': os.path.basename(path), 'Path': path}
                self.show_reference(key, fields)
                return True
        name = os.path.basename(paths[0]) if paths else ''
        self.status.setText(f'{name} is not on the map yet: it has not been analysed.')
        return False

    def show_reference(self, key, fields):
        """Show and select a track even if the list does not show it (e.g. a playlist track)."""
        self.reference = None if key in self.listed else (key, fields)
        self._merge_reference()
        self._refresh()
        self.select(key)
        self.view.centerOn(self.dots[key])

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
            dot.setBrush(QBrush(self._dot_colour(key, fields)))
            self._outline(key)
            lines = [f'{name}: {text}' for name, text in shown_fields(fields, hover)]
            dot.setToolTip('\n'.join(lines + ([self._group_text(key)] if self.groups else [])))
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
        self._clear_preview()
        if self.reference is not None and self.reference[0] != key:
            self.reference = None  # selecting another track: the reference dot goes away
            self._merge_reference()
            self._refresh()
        for changed in (previous, key):
            self._outline(changed)
        self._draw_edges()
        self._update_suggestions()
        self._show_selected_details()
        self.selected.emit(key)

    def preview(self, key):
        """Highlight a closest match on the map: glow, orange ring, its edges pale. The selection stays."""
        previous, self.preview_key = self.preview_key, key
        for changed in (previous, key):
            self._outline(changed)
        self._show_halos()
        self._draw_edges()
        if key in self.dots:
            self.view.ensureVisible(QRectF(self.dots[key].pos(), self.dots[key].pos()).adjusted(-40, -40, 40, 40))

    def _clear_preview(self):
        previous, self.preview_key = self.preview_key, None
        self._outline(previous)
        self._show_halos()

    def _show_halos(self):
        self.selected_glow.follow(self.dots.get(self.selected_key) if self.selected_key in self.fields else None)
        self.preview_glow.follow(self.dots.get(self.preview_key))

    def select_and_show(self, key):
        """Select a track and scroll the map to it (double-click in the closest matches)."""
        self.select(key)
        if key in self.dots:
            self.view.centerOn(self.dots[key])

    def _show_selected_details(self):
        self._show_halos()
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
        note = ('<i>Not in the list view (e.g. a playlist track); its matches come from the list.</i><br>'
                if self.reference is not None and self.reference[0] == self.selected_key else '')
        group = f'<br>{self._group_text(self.selected_key)}' if self.groups else ''
        self.details.setText(f'{note}<b>{escape(fields.get("Artist", ""))} - {escape(fields.get("Title", ""))}</b><br>'
                             f'Key now: {escape(key_now)}, {escape(fields.get("Original BPM", ""))} BPM{group}'
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
        """Selected track: white ring on top; a clicked match: thick magenta ring (plus the glow);
        the other closest matches: cyan ring; others: thin dark edge."""
        dot = self.dots.get(key)
        if dot is None:
            return
        if key == self.selected_key:
            dot.setPen(QPen(QColor(SELECTED_RING), 3))
            dot.setZValue(4)
        elif key == self.preview_key:
            dot.setPen(QPen(QColor(PREVIEW_RING), 3.5))
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
        self.settings['Map lines per track'] = self.lines_per_track.value()
        self._draw_edges()

    def _edge_sources(self):
        """[(sources, alpha)] to draw; pale first, so the selected track's edges lie on top."""
        if self.all_edges.isChecked():
            return [(list(self.dots), EDGE_ALPHA_ALL)]
        return [([self.preview_key], EDGE_ALPHA_PREVIEW), ([self.selected_key], EDGE_ALPHA_SELECTED)]

    def _edges(self, criteria, sources=None):
        """[(source, target, reason, similarity)] from the visible sources to the visible dots:
        per source, the partners that sound most similar (lines per track); at most MAX_EDGES.
        sources: by default all visible dots or the selected track, as the checkbox says.

        Tracks are grouped by tempo-adjusted Camelot key, colour and rating, so matches are
        looked up instead of comparing every pair (thousands of tracks stay fast).
        """
        visible = [key for key, dot in self.dots.items() if dot.isVisible()]
        if sources is None:
            sources = visible if self.all_edges.isChecked() else [self.selected_key]
        shown = set(visible)
        sources = [key for key in sources if key in shown]
        by_key, by_colour, by_rating = {}, {}, {}
        for key in visible:
            fields = self.fields[key]
            by_key.setdefault(str(fields.get('Camelot Key New', '')).upper(), []).append(key)
            by_colour.setdefault(display_color(fields), []).append(key)
            by_rating.setdefault(fields.get('Rating - Song Selector') or fields.get('Rating') or '', []).append(key)
        edges, seen = [], set()
        limit = self.lines_per_track.value()
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
            reasons = {}
            for target, reason in candidates:
                if target != source:
                    reasons.setdefault(target, reason)  # one reason per partner, the first found
            targets = list(reasons)
            if not targets:
                continue
            similarity = self.data.vectors[[self.data.row[target] for target in targets]] @ \
                self.data.vectors[self.data.row[source]]
            for index in np.argsort(-similarity)[:limit]:
                target = targets[index]
                pair = frozenset((source, target))
                if pair in seen:
                    continue  # one edge per pair
                seen.add(pair)
                edges.append((source, target, reasons[target], float(similarity[index])))
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
        for sources, alpha in self._edge_sources():
            edges = self._edges(criteria, sources)
            if len(edges) >= MAX_EDGES:
                self.status.setText(f'Showing the first {MAX_EDGES} edges; filter the list to see fewer tracks. '
                                    + self._base_status)
            self._add_edge_items(edges, alpha)

    def _add_edge_items(self, edges, alpha):
        """One path item per reason, colour and opacity step (thousands of single lines would be
        slow). The most similar pair of the layer gets `alpha`, the least similar 15 % of it."""
        paths = {}
        strengths = [similarity for *_, similarity in edges]
        low, high = (min(strengths), max(strengths)) if strengths else (0, 0)
        for source, target, reason, similarity in edges:
            if reason == EDGE_SAME_COLOR:
                colour = (COLOR_MAPPING_CATEGORY.get(display_color(self.fields[source])) or NO_COLOR).name()
            else:
                colour = EDGE_COLORS[reason]
            level = round((STRENGTH_LEVELS - 1) * (similarity - low) / (high - low)) if high > low \
                else STRENGTH_LEVELS - 1
            path = paths.setdefault((reason, colour, level), QPainterPath())
            path.moveTo(self._scaled(source))
            path.lineTo(self._scaled(target))
        for (reason, colour, level), path in paths.items():
            weight = MIX_TYPES_BY_NAME[reason].weight if reason in MIX_TYPES_BY_NAME else 4
            colour_alpha = QColor(colour)
            colour_alpha.setAlpha(round(alpha * (0.15 + 0.85 * level / (STRENGTH_LEVELS - 1))))
            pen = QPen(colour_alpha, 0.6 + weight / 5)
            pen.setCosmetic(True)                      # constant width at any zoom
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(0)
            self.scene.addItem(item)
            self.edge_items.append(item)

    def _update_suggestions(self, _checked=False):
        self.settings['Map harmonic only'] = self.harmonic_only.isChecked()
        self.settings['Map match count'] = self.match_count.value()
        self.suggestions.clear()
        previous, self.match_keys = self.match_keys, []
        for key in previous:
            self._outline(key)
        if self.preview_key is not None:  # the list is rebuilt: the clicked match is gone
            self._clear_preview()
            self._draw_edges()
        if self.data is None or self.selected_key not in self.data.row:
            return
        visible = [self.data.row[key] for key, dot in self.dots.items()
                   if dot.isVisible() and key in self.data.row]
        source = self.fields.get(self.selected_key, {})
        on_playlist = self.playlist_keys()
        added = 0
        for row, score in nearest(self.data.vectors, self.data.row[self.selected_key], count=len(visible), among=visible):
            key = self.data.keys[row]
            target = self.fields.get(key, {})
            mix = mix_type(source.get('Camelot Key New'), target.get('Camelot Key New'))
            # A track Traktor has not analysed has no key, but its sound can still match:
            # "harmonic only" cannot rule it out, so it stays.
            keys_known = all(parse_camelot(fields.get('Camelot Key New')) is not None for fields in (source, target))
            if self.harmonic_only.isChecked() and mix is None and keys_known:
                continue
            item = MatchItem([f'{score * 100:.0f} %', mix.label if mix else ('' if keys_known else NO_KEY_TEXT)]
                             + [target.get(name, '') for name in HEADER_LABELS])
            item.setData(0, SORT_ROLE, score)
            item.setData(1, SORT_ROLE, mix.weight if mix else 0)
            for column, name in enumerate(HEADER_LABELS, start=2):
                item.setData(column, SORT_ROLE, _sort_value(name, target.get(name, '')))
            item.setData(0, Qt.UserRole, key)
            item.setData(0, PATH_ROLE, target.get('Path', ''))
            if mix is not None:
                item.setForeground(1, QBrush(QColor(EDGE_COLORS[mix.name])))
            elif not keys_known:
                item.setForeground(1, QBrush(NO_COLOR))
            if key in on_playlist:
                font = item.font(0)
                font.setItalic(True)
                for column in range(len(MATCH_COLUMNS)):
                    item.setFont(column, font)
                    item.setToolTip(column, 'Already on the playlist')
            self.suggestions.addTopLevelItem(item)
            if added < RINGED_MATCHES:  # the most similar come first
                self.match_keys.append(key)
                self._outline(key)
            added += 1
            if added >= self.match_count.value():
                break
        for column in range(len(MATCH_COLUMNS)):
            if not self.suggestions.isColumnHidden(column):
                self.suggestions.resizeColumnToContents(column)
