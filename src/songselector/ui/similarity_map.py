"""Similarity map: every track of the (filtered) library as a dot; similar tracks lie close.

- Positions come from the chosen layout (core.similarity.PROJECTIONS: t-SNE, UMAP or PCA),
  computed in a background thread; t-SNE and UMAP layouts are cached in embeddings.sqlite.
  Tracks analysed later are placed next to their most similar tracks (place_new) until the
  map is re-arranged.
- The map shows the rows the library list currently shows (same search and filters),
  and reads their table texts, so keys are tempo-adjusted exactly as in the list.
- "Closest matches" are exact (cosine similarity of the full vectors), because any 2D
  map distorts distances.
- Edges go only to the N most similar partners of a track; weaker similarity is drawn more
  transparent. Dots can be coloured by unsupervised groups (core.clustering) instead of
  the Traktor colour.
"""
import math
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from html import escape

import numpy as np
from PyQt5.QtCore import QMimeData, QObject, QPointF, QRectF, Qt, QTimer, QUrl, QVariantAnimation, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QDrag,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QTextOption,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolBar,
    QToolButton,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from songselector.config import FIELD_LABELS, SS_COLOR_COLUMN, SS_RATING_COLUMN, track_qcolor
from songselector.core.clustering import GROUPING_BY_NAME, GROUPING_METHODS, group_tracks
from songselector.core.color_search import COLOR_NAMES
from songselector.core.color_search import color_id as color_family
from songselector.core.harmonic import MIX_TYPES, MIX_TYPES_BY_NAME, mix_type, parse_camelot
from songselector.core.placement import (
    ABOVE_LEFT,
    ABOVE_RIGHT,
    BELOW_LEFT,
    BELOW_RIGHT,
    CORNERS,
    corner_rect,
    place_box,
)
from songselector.core.search_filters import NUMERIC_COLUMNS
from songselector.core.similarity import (
    DEFAULT_PROJECTION,
    EDGE_SAME_COLOR,
    EDGE_SAME_RATING,
    PROJECTIONS,
    centred_unit,
    connection,
    display_color,
    nearest,
    place_new,
    project,
    raw_vectors,
    track_vectors,
)
from songselector.core.traktor_collection import canonical_path
from songselector.ui.busy_spinner import BusySpinner
from songselector.ui.covers import SQUARE, CoverDelegate
from songselector.ui.delegates import ColorDotDelegate, StarRatingDelegate, stars

DEFAULT_HOVER_FIELDS = ['Artist', 'Title', 'Genre', 'Comment', 'Color - Song Selector',
                        'Rating - Song Selector', 'Color', 'Rating']
# What the map adds about a track besides the List's columns (name -> tooltip). Every part of the hover card, the
# selected track's label and the details panel can be switched on or off for each of them (View -> Map track
# details...); asked 2026-11-20: "there is no hard coded thing which cannot be changed". The defaults are what the
# three showed before.
COVER_ITEM, NAME_ITEM, KEY_ITEM, RELATION_ITEM, GROUP_ITEM = (
    'Cover art', 'Artist - Title', 'Key at master tempo, BPM', 'Mix and similarity', 'Group')
MAP_ITEMS = {
    COVER_ITEM: 'The picture in the file, else cover.jpg / folder.jpg next to it.',
    NAME_ITEM: 'In bold; the file name for a track with neither tag.',
    KEY_ITEM: 'One line, e.g. "C minor (5A), 104 BPM": the key at the master tempo and the track\'s own tempo.',
    RELATION_ITEM: 'How the track mixes with the selected track, and how similar they sound.',
    GROUP_ITEM: 'Its group on the map, while Groups is on.',
}
# Where track details appear: the cards (the hovered dot and the compared track), the label next to the selected
# dot, and the panel above the closest matches.
CARD, LABEL, PANEL = 'card', 'label', 'panel'
DETAIL_PLACES = {CARD: 'Hover card', LABEL: 'Selected track label', PANEL: 'Details panel'}
NOT_APPLICABLE = {LABEL: {RELATION_ITEM}, PANEL: {RELATION_ITEM}}   # the selected track has no mix with itself
DEFAULT_DETAILS = {CARD: [COVER_ITEM, NAME_ITEM, KEY_ITEM, RELATION_ITEM, GROUP_ITEM] + DEFAULT_HOVER_FIELDS,
                   LABEL: [NAME_ITEM, KEY_ITEM],
                   PANEL: [COVER_ITEM, NAME_ITEM, KEY_ITEM, GROUP_ITEM] + DEFAULT_HOVER_FIELDS}
DEFAULT_EDGES = ['perfect_mix', 'plus_1_mix', 'minus_1_mix', 'energy_boost']
SCENE_SIZE = 1000.0          # the map is scaled to about this many scene units
PAN_ROOM = 3                 # the view can be dragged this many map sizes past each edge of the map
DOT_SIZE = 9                 # pixels, independent of zoom
GLOW_SIZE = 44               # pixels: pulsing halo around the selected track and a clicked match
MAX_EDGES = 2500             # "between all visible tracks" is capped to stay readable
LINES_PER_TRACK = 20         # default: edges from a track go to its N most similar partners
STRENGTH_LEVELS = 6          # edge opacity steps, weakest to strongest similarity
MATCH_COUNT = 50             # default number of closest matches listed
RINGED_MATCHES = 15          # of those, the most similar get a ring on the map (more would cover it)
# Closest-match columns: the two of the map, then the library list's (chosen by right-clicking the header).
# 'Cover' comes last here (the other columns keep their indexes) and is moved to the front on screen.
MATCH_COLUMNS = ['Similarity', 'Mix'] + FIELD_LABELS + ['Cover']
MATCH_COVER_COLUMN = MATCH_COLUMNS.index('Cover')
DEFAULT_MATCH_COLUMNS = ['Similarity', 'Mix', 'Artist', 'Title', 'Cover']
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
# Edges bend to one side like an arc: the control point lies this far (share of the edge's
# length) beside its middle. Edges from one track then fan out in one direction of turn.
CURVE_BEND = 0.18
ONLY_LIST_TEXT = 'Map the List only'
CARD_COVER, DETAILS_COVER, MATCH_COVER = 64, 96, 28   # px: cover thumbnails in the cards, details, closest matches
# The info boxes on the map (hover card, compared track's card, the selected track's label) wrap their text at this
# many pixels: setting `Map info width` (View -> Map track details...), never below the minimum.
INFO_WIDTH, MIN_INFO_WIDTH, MAX_INFO_WIDTH = 360, 200, 1200
# Tracks selected in the Playlist: amber ring; those the List does not show also get a paler dot.
PLAYLIST_RING, MARKER_ALPHA = '#ffb000', 120
ARRANGING, GROUPING = 'Arranging the map', 'Grouping'   # reasons the map's spinner turns
# The selected track's label prefers the top of its dot, the cards the bottom: they rarely collide to begin with.
LABEL_CORNERS = (ABOVE_RIGHT, ABOVE_LEFT, BELOW_RIGHT, BELOW_LEFT)
# Closest matches: all similar tracks, only harmonic partners, or only the relations checked under Edges.
MATCHES_ALL, MATCHES_HARMONIC, MATCHES_EDGES = 'all', 'harmonic', 'edges'
# Shown after "List the N closest" in the side panel: "List the 35 closest | of all tracks".
MATCH_FILTERS = {MATCHES_ALL: 'of all tracks',
                 MATCHES_HARMONIC: 'harmonic partners only',
                 MATCHES_EDGES: 'with an Edges relation'}
MAP_HELP = ('Scroll: zoom. Drag the background: move. Shift+right-drag (2D): turn the map. Shift+drag (3D): rotate.\n'
            'Hover a dot: details. Click: its closest matches. Ctrl+click: compare with the selected track.\n'
            'Double-click: add to the playlist. Drag a dot: the file to Traktor, the playlist or Explorer.\n'
            'Right-click beside the map: show or hide the selected track\'s details. What the cards, the label and\n'
            'the details show: View -> Map track details...')
# "Map the List only" re-maps this long after the List's last change (typing a filter, scrolling Top N).
FOLLOW_DELAY_MS = 300
# 3D view: Shift+drag rotates (radians per pixel; also the 2D map's Shift+right-drag turn); far dots fade to this
# opacity; nearer dots lie above farther ones within their ring tier (selected, clicked, matches, others).
ROTATE_SPEED, FAR_OPACITY, DEPTH_Z = 0.008, 0.35, 0.3
FAR_SIZE, NEAR_SIZE = 0.5, 1.6   # 3D view: dot size (times DOT_SIZE) at the back and the front
PERSPECTIVE = 3.0            # eye distance in radii of the cloud: lower is a stronger 3D effect
DEFAULT_ANGLES = (0.6, -0.35)  # yaw, pitch of the first 3D view
# Info cards on the map (hover, and a compared track): dark and rounded, like the selected label.
CARD_BACKGROUND, CARD_TEXT, CARD_BORDER = QColor(24, 26, 30), '#e8eaed', '#5f6672'   # opaque: cards may overlap
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
    positions3d: dict = field(default_factory=dict)                  # path_key -> (x, y, z), 3D view only
    centre: np.ndarray = None   # mean raw vector of the mapped tracks: more tracks are centred the same way

    def __post_init__(self):
        self.row = {key: index for index, key in enumerate(self.keys)}

    def place(self, matrices):
        """Add tracks that were not mapped (e.g. Playlist tracks on a "Map the List only" map), each next to its most
        similar mapped tracks, in the same vector space; no new layout. matrices: {path_key: (frames, dim)}."""
        keys = [key for key in matrices if key not in self.row]
        if not keys or self.centre is None or not self.keys:
            return []
        vectors = centred_unit(raw_vectors([matrices[key] for key in keys]), self.centre)
        known = self.vectors
        for positions in (self.positions, self.positions3d):
            if positions and all(key in positions for key in self.keys):
                points = place_new(np.array([positions[key] for key in self.keys]), known, vectors)
                positions.update({key: tuple(point) for key, point in zip(keys, points)})
        self.vectors = np.vstack([known, vectors])
        for key in keys:
            self.row[key] = len(self.keys)
            self.keys.append(key)
        return keys


def _layout(keys, vectors, stored, dims, should_stop, projection=DEFAULT_PROJECTION):
    """{key: position} from the stored layout, with new tracks placed near their most similar
    tracks; a new layout when there is none yet or most tracks are new. None if stopped."""
    placed = [key for key in keys if key in stored]
    if len(keys) >= 3 and len(placed) < len(keys) / 2:
        points = project(vectors, projection, should_stop, dims)  # first map, or mostly new tracks
        if points is None:
            return None
        return {key: tuple(point) for key, point in zip(keys, points)}
    positions = {key: stored[key] for key in placed}
    new = [key for key in keys if key not in stored]
    if new and placed:
        index = {key: i for i, key in enumerate(keys)}
        points = place_new(np.array([positions[key] for key in placed]),
                           vectors[[index[key] for key in placed]], vectors[[index[key] for key in new]])
        positions.update({key: tuple(point) for key, point in zip(new, points)})
    return positions


def layout_cache_id(store, projection):
    """The `model` a layout is cached under: t-SNE under the model's own id (as before layouts could be chosen, so
    those caches stay valid), others under '<model id>:<projection>'; None for PCA, which is computed every time (a
    second, and exact)."""
    if projection == 'pca':
        return None
    return store.spec.id if projection == 'tsne' else f'{store.spec.id}:{projection}'


def build_map_data(store, rearrange=False, should_stop=lambda: False, with_3d=False, only=None,
                   projection=DEFAULT_PROJECTION):
    """Load embeddings, compute vectors and positions (and the 3D view's, if asked); None if
    stopped. Slow: run in a thread.

    only: path_keys to map on their own. Vectors (centred on these tracks), layout and
    everything built on them then fit just this set, e.g. one genre, which separates it better
    than the whole library does. Computed fresh and not stored: the library's layout stays.
    projection: a PROJECTIONS name; each one keeps its own cached library layout."""
    matrices = store.load_many() if only is None else store.load_many(only)
    keys = sorted(matrices)
    vectors, centre = track_vectors([matrices[key] for key in keys], with_centre=True)
    cache = None if only is not None else layout_cache_id(store, projection)
    stored = {} if rearrange or cache is None else store.load_layout(cache)
    positions = _layout(keys, vectors, stored, 2, should_stop, projection)
    if positions is None:
        return None
    if cache is not None and positions != stored:
        store.save_layout(positions, cache)
    positions3d = {}
    if with_3d:
        stored = {} if rearrange or cache is None else store.load_layout_3d(cache)
        positions3d = _layout(keys, vectors, stored, 3, should_stop, projection)
        if positions3d is None:
            return None
        if cache is not None and positions3d != stored:
            store.save_layout_3d(positions3d, cache)
    return MapData(keys, vectors, positions, positions3d, centre)


def shown_fields(fields, names):
    """(name, text) pairs worth showing: non-empty, colour 0 ("no colour") and rating 0
    ("unrated") left out; ratings as stars."""
    zero_means_none = ('Color', SS_COLOR_COLUMN, 'Rating', SS_RATING_COLUMN)
    shown = [(name, fields[name]) for name in names
             if fields.get(name) and not (name in zero_means_none and fields[name] == '0')]
    return [(name, stars(text, text) if name in ('Rating', SS_RATING_COLUMN) else text) for name, text in shown]


def field_html(name, text):
    """A field's value for the details box and the cards: colours as a coloured dot and name."""
    if name in ('Color', SS_COLOR_COLUMN):
        number = color_family(text)
        if number is None:
            return escape(text)
        colour = track_qcolor(text)
        name = COLOR_NAMES.get(number, text).capitalize()
        return f'<span style="color:{colour.name()}">&#9679;</span> {name}' if colour is not None else name
    return escape(text)


def track_name(fields):
    """'Artist - Title', or just the one that is filled in (a track without an artist tag is not ' - Title')."""
    parts = (str(fields.get('Artist') or '').strip(), str(fields.get('Title') or '').strip())
    return ' - '.join(part for part in parts if part) or os.path.basename(str(fields.get('Path') or ''))


def fields_table(fields, names, panel=False):
    """The chosen columns as a table ('' if none has a value): grey names on the cards, plain in the panel."""
    shown = shown_fields(fields, names)
    if not shown:
        return ''
    if panel:
        return ('<table cellspacing="4">' + ''.join(f'<tr><td><i>{name}</i></td><td>{field_html(name, text)}</td></tr>'
                                                    for name, text in shown) + '</table>')
    return ('<table cellspacing="0" cellpadding="1">' +
            ''.join(f'<tr><td style="color:#9aa0a6; padding-right:8px"><i>{name}</i></td><td>{field_html(name, text)}</td></tr>'
                    for name, text in shown) + '</table>')


def detail_items(settings, place):
    """What a place (CARD, LABEL, PANEL) shows: MAP_ITEMS and List columns (setting `Map details`, {place: [items]}).
    Until 2026-11-20 only the columns could be chosen, for the card and the panel alike (`Map hover fields`): they
    carry over, with the map's own items on, as they were always shown then."""
    chosen = (settings.get('Map details') or {}).get(place)
    if chosen is not None:
        return list(chosen)
    columns = settings.get('Map hover fields')
    if columns is None or place == LABEL:
        return list(DEFAULT_DETAILS[place])
    return [item for item in DEFAULT_DETAILS[place] if item in MAP_ITEMS] + list(columns)


def key_now(fields):
    """'C minor (5A)': the key at the master tempo, as the List shows it; '' without one."""
    key, camelot = (str(fields.get(name) or '').strip() for name in ('New Key', 'Camelot Key New'))
    return f'{key} ({camelot})' if key and camelot else key or camelot


def key_line(fields, place):
    """The key at the master tempo and the track's own BPM, worded for the place; parts without a value left out."""
    key, bpm = key_now(fields), str(fields.get('Original BPM') or '').strip()
    if key:
        key = {LABEL: f'{key} at master tempo', PANEL: f'Key now: {key}'}.get(place, key)
    return ', '.join(part for part in (key, f'{bpm} BPM' if bpm else '') if part)


def turned(points, angle):
    """Points (n, 2) turned by angle (radians) about the origin: clockwise on screen, where y points down."""
    cos, sin = math.cos(angle), math.sin(angle)
    return np.asarray(points, dtype=np.float64) @ np.array([[cos, sin], [-sin, cos]])


def wrapping_text(parent):
    """A text item that can wrap (see fit_width); long words such as file names break anywhere."""
    item = QGraphicsTextItem(parent)
    item.setAcceptedMouseButtons(Qt.NoButton)
    option = item.document().defaultTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    item.document().setDefaultTextOption(option)
    return item


def fit_width(item, max_width):
    """Wrap the item's text at max_width pixels; text that is narrower keeps its own width (a short card stays
    small). Without this a long file name made a card as wide as the map and hid the dots under it."""
    item.setTextWidth(-1)
    if item.boundingRect().width() > max_width:
        item.setTextWidth(max_width)


class Card(QGraphicsPathItem):
    """Rounded info card below and right of a dot (same pixel size at any zoom), at most `Map info width` pixels
    wide. Mouse clicks and hovering go through it to the dots underneath."""

    def __init__(self, border, z):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setPen(QPen(QColor(border), 1.2))
        self.setBrush(QBrush(CARD_BACKGROUND))
        self.setZValue(z)
        self.text = wrapping_text(self)
        self.text.setDefaultTextColor(QColor(CARD_TEXT))
        self.text.document().setDocumentMargin(8)
        self.hide()

    def show_at(self, dot, html, max_width=INFO_WIDTH):
        """Show the card at the dot, below and right of it; the map then moves it to a free corner."""
        self.text.setHtml(html)
        fit_width(self.text, max_width)
        self.setPos(dot.pos())
        self.set_corner(BELOW_RIGHT)
        self.show()

    def box_size(self):
        box = self.text.boundingRect()
        return box.width(), box.height()

    def set_corner(self, corner):
        """Draw the card at this corner of its dot (core.placement corners), in pixels."""
        x, y, width, height = corner_rect((0, 0), self.box_size(), corner, DOT_SIZE)
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, width, height), 8, 8)
        self.setPath(path)
        self.text.setPos(x, y)
        self.corner = corner


class MapLabel(QGraphicsRectItem):
    """Label next to the selected dot (by default artist - title, key at master tempo and BPM; View -> Map track
    details...); same pixel size at any zoom. Above and right of the dot unless the map moves it to another corner."""

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setBrush(QBrush(QColor(20, 22, 25, 225)))
        self.setPen(QPen(QColor(SELECTED_RING), 1))
        self.setZValue(10)
        self.text = wrapping_text(self)
        self.text.setDefaultTextColor(QColor('#f0f0f0'))
        self.text.document().setDocumentMargin(0)  # the padding is the box's (box_size, set_corner)
        self.corner = ABOVE_RIGHT
        self.hide()

    def set_html(self, html, max_width=INFO_WIDTH):
        """Rich text, wrapped so the whole label (with its padding) is at most max_width pixels wide."""
        self.text.setHtml(html)
        fit_width(self.text, max_width - 12)

    def box_size(self):
        box = self.text.boundingRect()
        return box.width() + 12, box.height() + 8

    def set_corner(self, corner):
        x, y, width, height = corner_rect((0, 0), self.box_size(), corner, DOT_SIZE)
        self.setRect(QRectF(x, y, width, height))
        self.text.setPos(x + 6, y + 4)
        self.corner = corner


def group_colour(group):
    """Colour of a group as on the map (-1 = in no group). Groups are numbered along the map, so the colours repeat
    after the palette, for groups far apart, instead of making every later group grey."""
    if group < 0:
        return UNGROUPED
    return QColor(GROUP_COLOURS[group % len(GROUP_COLOURS)])


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
        if event.modifiers() & Qt.ControlModifier and self.owner.selected_key not in (None, self.key):
            self.owner.compare(self.key)  # the selection stays
        else:
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

    def hoverEnterEvent(self, event):
        self.owner.hover(self.key)

    def hoverLeaveEvent(self, event):
        self.owner.hover(None)


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
        if not settings.get('Map match cover column version'):  # 1.2.0: the Cover column, shown once
            if 'Cover' not in shown:
                shown = list(shown) + ['Cover']
                settings['Map match columns'] = shown
            settings['Map match cover column version'] = 1
        for column, name in enumerate(MATCH_COLUMNS):
            self.setColumnHidden(column, name not in shown)
        self.header().moveSection(self.header().visualIndex(MATCH_COVER_COLUMN), 0)
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
        # The scene reaches far beyond the dots (PAN_ROOM), so scroll bars would always show: dragging pans instead.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)

    rotator = None    # set by the map widget: rotates the 3D view on Shift+drag, turns the 2D map on Shift+right-drag
    _rotate_from = None
    _turn_from = None
    _turned = False   # a turn just ended: the context menu event that follows the right button is not for a menu

    def mousePressEvent(self, event):
        self._turned = False
        # Asked 2026-11-20: turn the 2D map left and right with Shift+right-drag. Handled here, before the scene, so a
        # Shift+right-press on a dot turns the map instead of selecting the dot and opening its menu.
        if (event.button() == Qt.RightButton and event.modifiers() & Qt.ShiftModifier
                and self.rotator is not None and not self.rotator.showing_3d()):
            self._turn_from = event.pos()
            self.viewport().setCursor(Qt.SizeHorCursor)
            event.accept()
            return
        if (event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier
                and self.rotator is not None and self.rotator.view_3d):
            self._rotate_from = event.pos()
            self.viewport().setCursor(Qt.SizeAllCursor)
            event.accept()
            return
        if (event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier and self.rotator is not None
                and not any(isinstance(item, DotItem) for item in self.items(event.pos()))):
            self.rotator.end_compare()  # Ctrl+click on empty space: the compared track goes, the selection stays
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._turn_from is not None:
            delta = event.pos().x() - self._turn_from.x()   # right: clockwise, left: anticlockwise
            self._turn_from = event.pos()
            self.rotator.turn(delta * ROTATE_SPEED)
            event.accept()
            return
        if self._rotate_from is not None:
            delta = event.pos() - self._rotate_from
            self._rotate_from = event.pos()
            self.rotator.rotate(delta.x() * ROTATE_SPEED, delta.y() * ROTATE_SPEED)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._turn_from is not None and event.button() == Qt.RightButton:
            self._turn_from = None
            self._turned = True
            self.viewport().unsetCursor()
            self.rotator.turn_done()
            event.accept()
            return
        if self._rotate_from is not None:
            self._rotate_from = None
            self.viewport().unsetCursor()
            self.rotator.rotation_done()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        # The right button of a turn also sends a context menu event (Windows: on release, Linux: on press).
        if self._turn_from is not None or self._turned:
            self._turned = False
            event.accept()
            return
        super().contextMenuEvent(event)

    def wheelEvent(self, event):
        factor = 1.2 ** (event.angleDelta().y() / 120)
        self.scale(factor, factor)
        if self.rotator is not None:
            self.rotator._layout_boxes()  # dots moved closer or apart; the boxes keep their pixel size

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.rotator is not None:
            self.rotator._layout_boxes()  # the visible area changed

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
    groups_changed = pyqtSignal()                      # self.groups was recomputed or cleared
    detach_requested = pyqtSignal(bool)                # True: show the map in its own window, False: back in its tab
    details_shown_changed = pyqtSignal(bool)           # the details panel was switched on or off (View menu follows)
    details_dialog_requested = pyqtSignal()            # "Choose track details..." in the right-click menu

    def __init__(self, store, settings, parent=None):
        super().__init__(parent)
        self.store, self.settings = store, settings
        self.data = None
        self.listed = {}          # path_key -> {column: text} of the rows the list shows
        self.fields = {}          # listed rows plus the reference track, if any
        # A track dropped on the map that the list does not show (e.g. a playlist track):
        # shown and selected anyway, so its closest matches can be explored. (key, fields)
        self.reference = None
        # Tracks selected in the Playlist: {path_key: {column: text}}, ringed amber. Those the List does not show
        # (markers) are shown anyway, dimmed with a dashed ring, but take no part in closest matches and edges.
        self.highlighted = {}
        self._markers = set()
        self.covers = None        # ui.covers.CoverProvider, set by the main window (set_covers)
        # key -> {column: text} for any library or playlist track; set by the main window.
        self.fields_provider = lambda key: None
        # path_keys of the playlist tracks (set by the main window): italic in the closest matches.
        self.playlist_keys = lambda: set()
        self.dots = {}
        self.selected_key = None
        self.preview_key = None   # a closest match clicked in the list, or a Ctrl+clicked dot: glows,
                                  # gets a card and a line to the selected track; the selection stays
        self.hover_key = None
        self.view_3d = bool(settings.get('Map 3D', False))
        self.angles = tuple(settings.get('Map 3D angles', DEFAULT_ANGLES))  # yaw, pitch
        try:  # the 2D map turned clockwise by this many radians (Shift+right-drag)
            self.turn_angle = float(settings.get('Map 2D turn', 0.0)) % (2 * math.pi)
        except (TypeError, ValueError):
            self.turn_angle = 0.0
        self._projected_turn = self.turn_angle  # the turn the 2D dots are drawn at now
        self._projected = {}      # path_key -> QPointF on the scene (2D map or rotated 3D view)
        self._depth = {}          # path_key -> 0 (far) .. 1 (near) in the 3D view
        self._edge_layers = []    # [(edges, alpha)] last computed; redrawn when the 3D view turns
        self._place_timer = None
        self.groups = {}          # path_key -> group (0 = largest, -1 = none) while grouping is on
        self._group_request = 0   # only the latest grouping result is used
        self._grouper = _Loader()
        self._grouper.done.connect(self._grouped)
        self.match_keys = []      # closest matches of the selected track, ringed on the map
        self._base_status = ''
        self.search_note = ''     # set by the main window while the map window's own search decides the tracks
        self._loading = False
        self.only = None          # frozenset of path_keys while the map shows just those tracks, else None
        # While "Map the List only" is on, a changed List re-maps after a short pause (a burst of changes,
        # e.g. Top N scrolled or typed, gives one new map).
        self._follow_timer = None
        self._again = False       # the mode changed during a load: load once more when it ends
        self._fit_next = False    # fit the view to the dots when the next load arrives
        self._stop = threading.Event()
        self._loader = _Loader()
        self._loader.done.connect(self._loaded)

        self.scene = QGraphicsScene(self)
        self.view = MapView(self.scene)
        # Esc anywhere in the map (view, matches list): nothing selected
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.deselect, context=Qt.WidgetWithChildrenShortcut)
        self.view.rotator = self
        self.view.dropped.connect(self.drop_paths)
        self.edge_items = []
        self.label = MapLabel()
        self.label_text = self.label.text
        self.scene.addItem(self.label)
        # Glows behind the selected track (white) and a clicked closest match (magenta).
        self.selected_glow = Halo(SELECTED_RING, 3.9, self)
        self.preview_glow = Halo(PREVIEW_RING, 3.4, self)
        for halo in (self.selected_glow, self.preview_glow):
            self.scene.addItem(halo)
        # Details of the hovered dot and of the compared track (replaces plain tooltips).
        self.hover_card = Card(CARD_BORDER, 12)
        self.preview_card = Card(PREVIEW_RING, 11)
        for card in (self.hover_card, self.preview_card):
            self.scene.addItem(card)

        self.status = QLabel('')
        self.spinner = BusySpinner()  # turns while the map is arranged or grouped
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
        self.edges_button.setToolTip('Which relations the map draws as lines, to how many partners, and how')
        self.lines_per_track = QSpinBox()
        self.lines_per_track.setRange(1, 500)
        self.lines_per_track.setPrefix('Lines to the ')
        self.lines_per_track.setSuffix(' most similar')
        self.lines_per_track.setToolTip('Edges from a track go only to this many partners: those that sound most\n'
                                        'similar to it among the tracks on the map (relative, per track, so every\n'
                                        'track keeps its N closest partners). The more similar, the more opaque the line.')
        self.lines_per_track.setValue(settings.get('Map lines per track', LINES_PER_TRACK))
        self.lines_per_track.setKeyboardTracking(False)
        self.lines_per_track.valueChanged.connect(self._edges_changed)
        # All edge settings live in the Edges menu: set once, rarely changed, so they need no toolbar space.
        edges_menu.addSeparator()
        edges_menu.setToolTipsVisible(True)
        holder = QWidget()
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(24, 2, 8, 2)
        holder_layout.addWidget(self.lines_per_track)
        lines_action = QWidgetAction(edges_menu)
        lines_action.setDefaultWidget(holder)
        edges_menu.addAction(lines_action)
        self.all_edges = edges_menu.addAction('Edges between all visible tracks')
        self.all_edges.setCheckable(True)
        self.all_edges.setToolTip('Every visible track draws edges to its N most similar partners (the number '
                                  'above). Otherwise edges start at the selected track only.')
        self.all_edges.setChecked(settings.get('Map edges between all', False))
        self.all_edges.toggled.connect(self._edges_changed)
        self.curved_action = edges_menu.addAction('Curved lines')
        self.curved_action.setCheckable(True)
        self.curved_action.setChecked(settings.get('Map curved edges', True))
        self.curved_action.toggled.connect(self._edges_changed)
        self.match_filter = QComboBox()
        for name, label in MATCH_FILTERS.items():
            self.match_filter.addItem(label, name)
        self.match_filter.setToolTip(
            'Which tracks the closest matches list:\n'
            'all: every track, most similar first;\n'
            'harmonic only: tracks that mix harmonically with the selected track (any mix type);\n'
            'Edges selection: only tracks with a relation checked under Edges (mix types, same colour, same rating).\n'
            'Tracks without a key in Traktor stay in the list (Mix: "no key"): their sound can still match.')
        # Up to 1.1.x a checkbox, "harmonic only": its setting carries over.
        saved = settings.get('Map match filter') or (MATCHES_HARMONIC if settings.get('Map harmonic only') else MATCHES_ALL)
        self.match_filter.setCurrentIndex(max(self.match_filter.findData(saved), 0))
        self.match_filter.currentIndexChanged.connect(self._update_suggestions)
        fit = QPushButton('Fit')
        fit.clicked.connect(self.fit)
        self.view_3d_button = QPushButton('3D')
        self.view_3d_button.setCheckable(True)
        self.view_3d_button.setChecked(self.view_3d)
        self.view_3d_button.setToolTip('3D view: Shift+drag rotates, scroll zooms, drag moves.\n'
                                       'The first 3D arrangement takes about as long as Re-arrange map.')
        self.view_3d_button.toggled.connect(self.set_3d)
        self.rearrange_button = QPushButton('Re-arrange map')
        self.rearrange_button.clicked.connect(self._rearrange)
        # How the tracks are laid out (asked 2026-11-24): each gives another view of the same similarities.
        self.projection = QComboBox()
        for name, (label, _layout_function) in PROJECTIONS.items():
            self.projection.addItem(label, name)
        self.projection.setCurrentIndex(max(self.projection.findData(settings.get('Map projection')), 0))
        self.projection.setToolTip(
            'How the tracks are laid out on the map (the closest matches list does not change):\n'
            't-SNE: tight, well separated clumps; keeps the most of each track\'s nearest neighbours,\n'
            '  but the distance between two clumps means little. Slowest (minutes for 3,000 tracks).\n'
            'UMAP: as good as t-SNE on a short List, fewer neighbours kept on a big map; similar clumps\n'
            '  sit a bit closer together. Seconds for 3,000 tracks.\n'
            'PCA: the two main directions in which the tracks differ. Instant, and distances across\n'
            '  the whole map mean the most, but neighbours mix and clumps blur together.\n'
            'The library map of t-SNE and UMAP is kept, so switching back is instant.')
        self.projection.currentIndexChanged.connect(self._projection_changed)
        # Not on the toolbar since 2026-11-20 (user's decision: the map's own window made no sense in use); kept, as
        # MainWindow.set_map_detached keeps its state on it, in case the feature comes back.
        self.detach_button = QPushButton('Own window')
        self.detach_button.setCheckable(True)
        self.detach_button.setToolTip('Show the map in a window of its own (move it to another screen, resize it\n'
                                      'freely); it keeps following the List. Close that window to get it back here.')
        self.detach_button.toggled.connect(self.detach_requested.emit)
        self.only_button = QPushButton(ONLY_LIST_TEXT)
        self.only_button.setCheckable(True)
        self.only_button.toggled.connect(self.set_only_listed)
        self._describe_buttons()

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
        self.grouping.addItem('Off (track colours)', None)
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

        # One toolbar, ordered by task (UI review 2026-11-20): what is mapped -> how it is coloured -> the view.
        # Before: two rows mixing all of these. A QToolBar folds what does not fit into its >> menu, so the map never
        # has to be wider than the screen allows. The model is chosen in the main window's Model box (next to
        # "Describe a sound"); the map had a Model box of its own here for a few hours on 2026-11-20.
        # It sits below the map (user's request, 2026-11-20), so the map starts right under the tabs.
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.addWidget(self.only_button)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel('Groups '))
        toolbar.addWidget(self.grouping)
        toolbar.addWidget(self.grouping_parameter)
        toolbar.addSeparator()
        toolbar.addWidget(self.edges_button)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addWidget(QLabel('Layout '))
        toolbar.addWidget(self.projection)
        for widget in (self.view_3d_button, fit, self.rearrange_button):
            toolbar.addWidget(widget)
        self.toolbar = toolbar
        side = QWidget()
        side.setMinimumWidth(SIDE_MIN_WIDTH)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(self.details)
        if not self.details_shown():
            self.details.hide()
        # Right-click anywhere beside the map (the details, the caption, the closest matches' rows: they pass the
        # event on to this panel) shows or hides the details; the details' own menu keeps Copy.
        side.setContextMenuPolicy(Qt.CustomContextMenu)
        side.customContextMenuRequested.connect(lambda pos: self._side_menu(side, pos))
        self.details.setContextMenuPolicy(Qt.CustomContextMenu)
        self.details.customContextMenuRequested.connect(lambda pos: self._side_menu(self.details, pos))
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
        count_row = QHBoxLayout()  # "List the 35 closest | of all tracks": the filter sits with the list it filters
        count_row.addWidget(self.match_count)
        count_row.addWidget(self.match_filter, 1)
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
        layout.addWidget(self.splitter, 1)  # the map gets all spare space
        # Status line: what the map shows and the groups' sizes; how to use the map is behind "?" (read once).
        self.help_button = QToolButton()
        self.help_button.setText('?')
        self.help_button.setAutoRaise(True)
        self.help_button.setToolTip(MAP_HELP)
        self.help_button.clicked.connect(
            lambda: QToolTip.showText(self.help_button.mapToGlobal(self.help_button.rect().bottomLeft()), MAP_HELP))
        status_bar = QHBoxLayout()
        status_bar.addWidget(self.spinner, 0, Qt.AlignTop)
        status_bar.addWidget(self.status, 1)
        status_bar.addWidget(self.grouping_summary, 1)
        status_bar.addWidget(self.help_button, 0, Qt.AlignTop)
        layout.addLayout(status_bar)
        layout.addWidget(toolbar)

    # -- details panel ------------------------------------------------------

    def details_shown(self):
        """The selected track's details above the closest matches are on (setting `Map details panel`)."""
        return bool(self.settings.get('Map details panel', True))

    def set_details_shown(self, shown):
        """Show or hide the selected track's details above the closest matches (asked 2026-11-20: right-click beside
        the map, or View -> Selected track details). The list of matches gets the room."""
        shown = bool(shown)
        changed = shown != self.details_shown()
        self.settings['Map details panel'] = shown
        self.details.setVisible(shown)
        if changed:
            self.details_shown_changed.emit(shown)

    def _side_menu(self, widget, pos):
        menu = QMenu(self)
        toggle = menu.addAction('Show selected track details')
        toggle.setCheckable(True)
        toggle.setChecked(self.details_shown())
        toggle.toggled.connect(self.set_details_shown)
        menu.addAction('Choose track details...').triggered.connect(self.details_dialog_requested.emit)
        if widget is self.details and self.details.hasSelectedText():  # the label's own menu offered Copy
            menu.addSeparator()
            menu.addAction('Copy').triggered.connect(
                lambda: QApplication.clipboard().setText(self.details.selectedText()))
        menu.exec_(widget.mapToGlobal(pos))

    # -- data ---------------------------------------------------------------

    def _describe_buttons(self):
        if self.only is None:
            self.rearrange_button.setToolTip('Compute the map again from all analysed tracks (takes a few minutes).')
        else:
            self.rearrange_button.setToolTip('Arrange the tracks the List shows again, from scratch (seconds).')
        self.only_button.setToolTip(
            'Map and group only the tracks the List shows (a genre, a playlist, a description search...):\n'
            'the arrangement and the groups then fit just these tracks, which separates them better than\n'
            'the whole library does. Takes seconds, and follows the List: a new search or filter maps the\n'
            'new List. Switch this off to get the library map back.')

    def set_only_listed(self, on):
        """Map just the tracks the List shows (and keep following it), or the whole library again."""
        if self._follow_timer is not None:
            self._follow_timer.stop()
        self.only = frozenset(self.listed) if on else None
        self._describe_buttons()
        self._remap()

    def _remap(self):
        """Load the map again for the current mode. A running load is for an outdated mode: stop it and load once
        more when it has ended (reported 2026-11-24: a new List waited for the old 3,000-track map to finish)."""
        self._fit_next = True
        if self.data is None:
            return
        if self._loading:
            self._again = True
            self._stop.set()
        else:
            self.load()

    def _projection_changed(self, _index=0):
        self.settings['Map projection'] = self.projection.currentData()
        self._remap()

    def _follow_list(self):
        """'Map the List only': map the List as it is now, unless the map already shows exactly these tracks."""
        if self.only is None or self.only == frozenset(self.listed):
            return
        self.only = frozenset(self.listed)
        self._remap()

    def _rearrange(self):
        if self.only is not None:
            self.only = frozenset(self.listed)  # the list as it is now
        self.load(rearrange=True)

    def load(self, rearrange=False):
        """(Re)compute map data in the background; the view keeps working meanwhile."""
        if self._loading:
            return
        self._loading = True
        self.spinner.set_busy(ARRANGING)
        self.rearrange_button.setEnabled(False)
        first_3d = self.view_3d and (self.data is None or not self.data.positions3d)
        self.status.setText('Arranging the map... (similar tracks are being placed close together)'
                            + (' The first 3D view takes a few minutes.' if first_3d and self.only is None else '')
                            if rearrange or self.data is None or first_3d or self.only is not None
                            else 'Updating the map...')
        self._stop.clear()
        with_3d, only, projection = self.view_3d, self.only, self.projection.currentData()

        def work():
            try:
                result = build_map_data(self.store, rearrange, self._stop.is_set, with_3d, only, projection)
            except Exception as error:  # e.g. database busy: report, keep the old map
                result = error
            self._loader.done.emit(result)
        threading.Thread(target=work, name='similarity-map', daemon=True).start()

    def stop(self):
        self._stop.set()

    def set_store(self, store):
        """Use another model's embeddings (the main window's Model box). Layout, closest matches and groups follow
        it; each model's cache keeps its own layout. Call load() afterwards if the map or the groups are needed."""
        if store is self.store:
            return
        self.store = store
        self._fit_next = True
        if self._loading:
            self._again = True  # the running load is for the old model: load again when it ends
            self._stop.set()

    def _loaded(self, result):
        self._loading = False
        self.spinner.set_busy(ARRANGING, False)  # load() below turns it on again
        self.rearrange_button.setEnabled(True)
        if self._again:  # the mode changed while this was computed: this result is for the other one
            self._again = False
            self.load()
            return
        if isinstance(result, Exception):
            self.status.setText(f'Could not build the map: {result}')
            return
        if result is None:
            return
        first = self.data is None or self._fit_next
        self._fit_next = False
        self.data = result
        self._place_highlighted()  # Playlist tracks the new map does not contain
        self._rebuild_dots()
        if first:
            self.fit()
        self._update_groups()
        if self.view_3d and not self.data.positions3d:
            self.load()  # 3D was switched on while this load ran without it

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
            self.spinner.set_busy(GROUPING, False)
            if self.groups:
                self.groups = {}
                self._refresh()
                self.groups_changed.emit()
            return
        parameter = self.grouping_parameter.value()
        self.settings.setdefault('Map grouping parameters', {})[method] = parameter
        request, data = self._group_request, self.data
        self.grouping_summary.setText('Grouping...')
        self.spinner.set_busy(GROUPING)

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
        self.spinner.set_busy(GROUPING, False)
        if isinstance(result, Exception):
            self.grouping_summary.setText(f'Could not group: {result}')
            return
        self.groups = result
        labels = np.array(list(result.values()))
        sizes = np.bincount(labels[labels >= 0]) if (labels >= 0).any() else np.zeros(0, int)
        summary = f'{len(sizes)} groups of ' + (f'all {len(labels)} analysed tracks' if self.only is None
                                                else f'the {len(labels)} mapped tracks')
        if len(sizes):
            summary += f'; largest {sizes.max() / len(labels):.0%}; numbered along the map'
        if (labels < 0).any():
            summary += f'; {np.mean(labels < 0):.0%} in no group (dark grey)'
        self.grouping_summary.setText(summary)
        self._refresh()
        self.groups_changed.emit()

    def ensure_grouping(self, default='communities'):
        """Make sure groups get computed: choose `default` if grouping is off, and load the map
        data (in the background) if the map was not opened yet. True if data is being loaded."""
        if self.grouping.currentData() is None:
            self.grouping.setCurrentIndex(self.grouping.findData(default))  # regroups if data is there
        if self.data is None:
            self.load()
            return True
        return False

    def _dot_colour(self, key, fields):
        if not self.groups:
            colour = QColor(track_qcolor(display_color(fields)) or NO_COLOR)
        else:
            colour = QColor(group_colour(self.groups.get(key, -1)))
        if key in self._markers:
            colour.setAlpha(MARKER_ALPHA)
        return colour

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
        if self.only is not None and self.only != frozenset(fields):
            if self._follow_timer is None:
                self._follow_timer = QTimer(self)
                self._follow_timer.setSingleShot(True)
                self._follow_timer.timeout.connect(self._follow_list)
            self._follow_timer.start(FOLLOW_DELAY_MS)  # restarts: the last change of a burst counts

    def _merge_reference(self):
        self.fields = dict(self.listed)
        if self.reference is not None:
            self.fields.setdefault(*self.reference)
        self._markers = {key for key in self.highlighted if key not in self.fields}
        for key in self._markers:
            self.fields[key] = self.highlighted[key]

    def set_highlighted(self, fields):
        """Show these tracks (the Playlist's selection, {path_key: {column: text}}) on the map, also if the List does
        not show them. On a "Map the List only" map, tracks it does not contain are placed next to their most similar
        tracks first."""
        if fields == self.highlighted:
            return
        self.highlighted = dict(fields)
        placed = self._place_highlighted()
        self._merge_reference()
        if self.data is None:
            return
        if placed:
            self._rebuild_dots()  # also refreshes
        else:
            self._refresh()

    def _place_highlighted(self):
        """Add highlighted tracks that are analysed but not on the map yet; True if any were added."""
        if self.data is None:
            return False
        matrices = {}
        for key in self.highlighted:
            if key not in self.data.row:
                try:
                    matrix = self.store.load(key)
                except sqlite3.Error:
                    matrix = None
                if matrix is not None:
                    matrices[key] = matrix
        return bool(self.data.place(matrices))

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
        try:
            failure = self.store.failure(canonical_path(paths[0])) if paths else None
        except sqlite3.Error:
            failure = None
        if failure:  # tried and failed: waiting would not help
            self.status.setText(f'{name} cannot be on the map: its audio could not be analysed ({failure}).')
        else:
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
        return self._projected[key]

    def showing_3d(self):
        """3D view on and its layout there for every track (else the 2D map is shown)."""
        return (self.view_3d and self.data is not None and bool(self.data.positions3d)
                and all(key in self.data.positions3d for key in self.data.positions))

    def _project(self):
        """Scene positions of all tracks: the 2D map scaled to SCENE_SIZE and turned (Shift+right-drag), or the 3D
        cloud turned by yaw and pitch, with a little perspective. Fills _projected and _depth."""
        keys = list(self.data.positions)
        self._depth = {}
        if not keys:
            self._projected = {}
            return
        if not self.showing_3d():
            points = np.array([self.data.positions[key] for key in keys], dtype=np.float64)
            spread = float(np.ptp(points, axis=0).max()) or 1.0
            points = turned(points * (SCENE_SIZE / spread), self.turn_angle)
            self._projected_turn = self.turn_angle
            self._projected = {key: QPointF(x, y) for key, (x, y) in zip(keys, points)}
            return
        points = np.array([self.data.positions3d[key] for key in keys], dtype=np.float64)
        points -= points.mean(0)
        radius = float(np.linalg.norm(points, axis=1).max()) or 1.0
        yaw, pitch = self.angles
        turn = np.array([[np.cos(yaw), 0, np.sin(yaw)], [0, 1, 0], [-np.sin(yaw), 0, np.cos(yaw)]])
        tilt = np.array([[1, 0, 0], [0, np.cos(pitch), -np.sin(pitch)], [0, np.sin(pitch), np.cos(pitch)]])
        rotated = points @ (tilt @ turn).T / radius            # inside the unit sphere
        near = rotated[:, 2]                                   # towards the viewer: +z
        scale = PERSPECTIVE / (PERSPECTIVE - near) * (SCENE_SIZE / 2)
        self._projected = {key: QPointF(x, y) for key, x, y in
                           zip(keys, rotated[:, 0] * scale, rotated[:, 1] * scale)}
        self._depth = dict(zip(keys, (near + 1) / 2))

    def _place_dots(self):
        """Move the dots to the projected positions (after switching 2D/3D, rotating the 3D view or turning the 2D
        map). A 2D turn keeps what is in the middle of the view there: the map turns about it."""
        middle = self.view.mapToScene(self.view.viewport().rect().center())
        turn = self.turn_angle - self._projected_turn
        self._project()
        for key, dot in self.dots.items():
            dot.setPos(self._projected[key])
            self._apply_depth(key, dot)
            self._outline(key)
        self._set_scene_rect()
        self._paint_edges()
        if turn and not self.showing_3d():
            self.view.centerOn(QPointF(*turned([(middle.x(), middle.y())], turn)[0]))
        self._follow_dots()

    def _apply_depth(self, key, dot):
        """3D view: near dots bigger and opaque, far dots smaller and faded; 2D: plain."""
        depth = self._depth.get(key)
        if depth is None:
            dot.setOpacity(1.0)
            dot.setScale(1.0)
        else:
            dot.setOpacity(FAR_OPACITY + (1 - FAR_OPACITY) * depth)
            dot.setScale(FAR_SIZE + (NEAR_SIZE - FAR_SIZE) * depth)

    def _dots_rect(self):
        xs = [point.x() for point in self._projected.values()] or [0]
        ys = [point.y() for point in self._projected.values()] or [0]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def _set_scene_rect(self):
        """The area the view can be dragged over: the map plus PAN_ROOM times its size on every side. A view only
        scrolls within its scene rect; until 2026-11-20 that was the dots plus 5 %, so the map could hardly be moved
        (not at all once zoomed out), and a hover card at the edge stayed cut off (user's report). Fit brings the
        dots back."""
        rect = QRectF(-SCENE_SIZE / 2, -SCENE_SIZE / 2, SCENE_SIZE, SCENE_SIZE) if self.showing_3d() else \
            self._dots_rect()
        room = max(rect.width(), rect.height(), SCENE_SIZE * 0.05) * PAN_ROOM
        self.scene.setSceneRect(rect.adjusted(-room, -room, room, room))

    def _follow_dots(self):
        """Label, glows and cards stay on their dots after the dots moved."""
        if self.label.isVisible() and self.selected_key in self.dots:
            self.label.setPos(self.dots[self.selected_key].pos())
        self.hover_card.hide()
        self._show_halos()  # also lays the boxes out again: the dots moved relative to each other

    def info_width(self):
        """Pixels the info boxes wrap their text at (setting `Map info width`, kept within its limits)."""
        try:
            width = int(self.settings.get('Map info width', INFO_WIDTH))
        except (TypeError, ValueError):
            width = INFO_WIDTH
        return max(MIN_INFO_WIDTH, min(MAX_INFO_WIDTH, width))

    def _layout_boxes(self):
        """The selected track's label, then the compare card, then the hover card, each at the first corner of its
        dot where it covers neither the boxes placed before it nor their dots, and stays in view if it can. The
        boxes have a fixed pixel size, so this runs again when the zoom or the 3D view's angle changes."""
        viewport = self.view.viewport().rect()
        bounds = (0, 0, viewport.width(), viewport.height())
        shown = [(box, corners, self.view.mapFromScene(box.pos()))
                 for box, corners in ((self.label, LABEL_CORNERS), (self.preview_card, CORNERS),
                                      (self.hover_card, CORNERS))
                 if box.isVisible()]
        half = DOT_SIZE / 2 + 2
        taken = [(point.x() - half, point.y() - half, 2 * half, 2 * half) for _box, _corners, point in shown]
        for box, corners, point in shown:
            corner, rect = place_box((point.x(), point.y()), box.box_size(), taken, bounds, DOT_SIZE, corners)
            box.set_corner(corner)
            taken.append(rect)

    def set_3d(self, on):
        """Switch between the 2D map and the 3D view (computed in the background the first time)."""
        self.view_3d = bool(on)
        self.settings['Map 3D'] = self.view_3d
        if self.data is None:
            return
        if self.view_3d and not self.showing_3d():
            self.load()  # keeps the 2D map until the 3D layout is there
            return
        self._place_dots()
        self.fit()

    def rotate(self, yaw, pitch):
        """Turn the 3D view (Shift+drag). Several mouse moves are drawn as one."""
        self.angles = (self.angles[0] + yaw, max(-1.5, min(1.5, self.angles[1] + pitch)))
        self._place_soon()

    def rotation_done(self):
        self.settings['Map 3D angles'] = list(self.angles)

    def turn(self, angle):
        """Turn the 2D map clockwise by angle (radians; negative: anticlockwise) about the middle of the view
        (Shift+right-drag). Several mouse moves are drawn as one."""
        self.turn_angle = (self.turn_angle + angle) % (2 * math.pi)
        self._place_soon()

    def turn_done(self):
        self.settings['Map 2D turn'] = self.turn_angle

    def _place_soon(self):
        if self._place_timer is None:
            self._place_timer = QTimer(self)
            self._place_timer.setSingleShot(True)
            self._place_timer.timeout.connect(self._place_dots)
        if not self._place_timer.isActive():
            self._place_timer.start(0)

    def _rebuild_dots(self):
        for dot in self.dots.values():
            self.scene.removeItem(dot)
        self.dots = {}
        self._project()
        for key in self.data.positions:
            dot = DotItem(key, self)
            dot.setPos(self._projected[key])
            self._apply_depth(key, dot)
            self.scene.addItem(dot)
            self.dots[key] = dot
        self._set_scene_rect()
        self._refresh()

    def _refresh(self):
        shown = 0
        for key, dot in self.dots.items():
            fields = self.fields.get(key)
            dot.setVisible(fields is not None)
            if fields is None:
                continue
            shown += 1
            dot.setBrush(QBrush(self._dot_colour(key, fields)))
            self._outline(key)
        missing = len(self.fields) - shown - len([key for key in self._markers if key not in self.dots])
        if self.only is None:
            note = f'; {missing} listed tracks are not analysed yet' if missing > 0 else ''
        else:
            note = ' (only the tracks the List shows)' + \
                (f'; {missing} listed tracks are not analysed yet' if missing > 0 else '')
        if self.highlighted:
            on_map = sum(1 for key in self.highlighted if key in self.dots)
            note += (f'; {on_map} of {len(self.highlighted)} selected Playlist tracks shown (amber'
                     + (', dashed: not in the List' if self._markers else '') + ')')
        self._base_status = f'{shown} tracks on the map' + note + self.search_note  # how to use it: the ? button
        if self.selected_key not in self.fields:
            self.selected_key = None
        self._draw_edges()
        self._update_suggestions()
        self._show_selected_details()
        self.hover(self.hover_key)

    def fit(self):
        visible = [dot for dot in self.dots.values() if dot.isVisible()] or list(self.dots.values())
        if visible:
            xs = [dot.pos().x() for dot in visible]
            ys = [dot.pos().y() for dot in visible]
            rect = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            margin = max(rect.width(), rect.height(), 1) * 0.05
            self.view.fitInView(rect.adjusted(-margin, -margin, margin, margin), Qt.KeepAspectRatio)
            self._layout_boxes()

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

    def deselect(self):
        """Esc, in two steps: first the compared track (Ctrl+click, or a clicked closest match) goes and the selected
        track stays; then the selection: rings, edges, closest matches and the card go away."""
        if self.selected_key is None and self.preview_key is None and self.reference is None:
            return
        if self.preview_key is not None and self.selected_key is not None:
            self.end_compare()
            return
        previous, self.selected_key = self.selected_key, None
        self._clear_preview()
        if self.reference is not None:
            self.reference = None  # a dropped track that the list does not show goes away too
            self._merge_reference()
            self._refresh()
        self._outline(previous)
        self._draw_edges()
        self._update_suggestions()
        self._show_selected_details()

    def preview(self, key):
        """Highlight a track next to the selected one: magenta glow and ring, its edges pale, a
        line to the selected track and a card with its details, mix and similarity. The selection stays."""
        previous, self.preview_key = self.preview_key, key
        for changed in (previous, key):
            self._outline(changed)
        self._show_halos()
        self._draw_edges()
        self.hover(self.hover_key)
        if key in self.dots:
            self.view.ensureVisible(QRectF(self.dots[key].pos(), self.dots[key].pos()).adjusted(-40, -40, 40, 40))

    def compare(self, key):
        """Ctrl+click on a dot: preview it, and mark its row if it is among the closest matches.
        Ctrl+click on the compared dot again ends the comparison."""
        if key == self.preview_key:
            self.end_compare()
            return
        self.preview(key)
        for index in range(self.suggestions.topLevelItemCount()):
            item = self.suggestions.topLevelItem(index)
            if item.data(0, Qt.UserRole) == key:
                self.suggestions.setCurrentItem(item)
                self.suggestions.scrollToItem(item)
                break
        else:
            self.suggestions.clearSelection()

    def end_compare(self):
        """The compared track goes (glow, card, dashed line, its row's mark); the selected track stays."""
        if self.preview_key is None:
            return
        self._clear_preview()
        self._draw_edges()
        self.suggestions.clearSelection()

    def _clear_preview(self):
        previous, self.preview_key = self.preview_key, None
        self._outline(previous)
        self._show_halos()

    def _show_halos(self):
        self.selected_glow.follow(self.dots.get(self.selected_key) if self.selected_key in self.fields else None)
        self.preview_glow.follow(self.dots.get(self.preview_key))
        dot = self.dots.get(self.preview_key)
        html = self.card_html(self.preview_key) if dot is not None and self.preview_key in self.fields else ''
        if dot is not None and dot.isVisible() and html:
            self.preview_card.show_at(dot, html, self.info_width())
        else:
            self.preview_card.hide()  # also when nothing is chosen for the cards
        self._layout_boxes()

    def hover(self, key):
        """Card for the dot under the mouse (None: hide it). The compared track has its own card."""
        self.hover_key = key
        dot = self.dots.get(key)
        html = self.card_html(key) if dot is not None and key in self.fields else ''
        if dot is None or not dot.isVisible() or not html or key == self.preview_key:
            self.hover_card.hide()
        else:
            self.hover_card.show_at(dot, html, self.info_width())
            self._layout_boxes()

    def relation(self, key):
        """(mix type or None, similarity or None) of a track to the selected track."""
        if self.data is None or self.selected_key is None or key == self.selected_key:
            return None, None
        rows = self.data.row
        similarity = (float(self.data.vectors[rows[key]] @ self.data.vectors[rows[self.selected_key]])
                      if key in rows and self.selected_key in rows else None)
        source, target = self.fields.get(self.selected_key, {}), self.fields.get(key, {})
        return mix_type(source.get('Camelot Key New'), target.get('Camelot Key New')), similarity

    def _relation_html(self, key):
        """'Perfect mix · 72 % similar' to the selected track, in the mix's edge colour."""
        if self.selected_key not in self.fields or key == self.selected_key:
            return ''
        mix, similarity = self.relation(key)
        if mix is not None:
            text = f'<span style="color:{EDGE_COLORS[mix.name]}">{escape(mix.label)}</span>'
        else:
            known = all(parse_camelot(self.fields.get(k, {}).get('Camelot Key New')) is not None
                        for k in (key, self.selected_key))
            text = f'<span style="color:{NO_COLOR.name()}">{"No harmonic mix" if known else "No key"}</span>'
        if similarity is not None:
            text += f' &middot; <b>{similarity * 100:.0f} %</b> similar'
        return f'{text}<br><span style="color:#9aa0a6">to {escape(self.fields[self.selected_key].get("Title", ""))}</span>'

    def details_html(self, key, place):
        """A track's details for a place (CARD, LABEL or PANEL): the map's items chosen there (cover, artist - title,
        key and BPM, mix and similarity, group; always in this order), then the chosen columns. '' if nothing is."""
        fields = self.fields.get(key, {})
        chosen = detail_items(self.settings, place)
        items = set(chosen) - NOT_APPLICABLE.get(place, set())
        lines = []
        if COVER_ITEM in items:
            lines.append(self._cover_html(fields, DETAILS_COVER if place == PANEL else CARD_COVER))
        if NAME_ITEM in items:
            lines.append(f'<b>{escape(track_name(fields))}</b>')
        if KEY_ITEM in items and key_line(fields, place):
            text = escape(key_line(fields, place))
            lines.append(f'<span style="color:#9aa0a6">{text}</span>' if place == CARD else text)
        if RELATION_ITEM in items:
            lines.append(self._relation_html(key))
        if GROUP_ITEM in items and self.groups:
            lines.append(self._group_text(key))
        table = fields_table(fields, [item for item in chosen if item not in MAP_ITEMS], panel=place == PANEL)
        return '<br>'.join(line for line in lines if line) + table

    def card_html(self, key):
        """The hover card's (and the compared track's card's) text."""
        return self.details_html(key, CARD)

    def _cover_html(self, fields, size):
        """<img> of the track's cached cover thumbnail; '' without one. A cover that is not loaded yet is
        requested: the card is drawn again when it arrives (_cover_ready)."""
        path = fields.get('Path')
        if self.covers is None or not path:
            return ''
        file = self.covers.cached_file(path)
        if file is None:
            self.covers.pixmap(path)  # request it
            return ''
        return f'<img src="{escape(QUrl.fromLocalFile(str(file)).toString())}" width="{size}">'

    def _cover_ready(self, key):
        """A cover arrived: the cards, the details and the closest matches that show this track get it."""
        if key == self.hover_key:
            self.hover(key)
        if key == self.preview_key:
            self._show_halos()
        if key == self.selected_key:
            self._show_selected_details()
        self.suggestions.viewport().update()  # the Cover column paints what it now has

    def set_covers(self, provider):
        """Show cover thumbnails (ui.covers.CoverProvider) in the cards, the details and the closest matches."""
        self.covers = provider
        provider.ready.connect(self._cover_ready)
        self.cover_delegate = CoverDelegate(provider, style=SQUARE, size=MATCH_COVER, parent=self.suggestions,
                                            path_of=lambda index: index.sibling(index.row(), 0).data(PATH_ROLE))
        self.suggestions.setItemDelegateForColumn(MATCH_COVER_COLUMN, self.cover_delegate)
        self.suggestions.resizeColumnToContents(MATCH_COVER_COLUMN)

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
        label = self.details_html(self.selected_key, LABEL)
        if label:
            self.label.set_html(label, self.info_width())
            self.label.set_corner(ABOVE_RIGHT)
            self.label.setPos(self.dots[self.selected_key].pos())
            self.label.show()
        else:
            self.label.hide()  # nothing chosen for it: the white ring and glow still mark the track
        self._layout_boxes()
        note = ('<i>Not in the list view (e.g. a playlist track); its matches come from the list.</i><br>'
                if self.reference is not None and self.reference[0] == self.selected_key else '')
        self.details.setText(note + self.details_html(self.selected_key, PANEL))

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
        depth = DEPTH_Z * self._depth.get(key, 0)  # 3D view: nearer dots on top within a tier
        if key == self.selected_key:
            dot.setPen(QPen(QColor(SELECTED_RING), 3))
            dot.setZValue(4 + depth)
        elif key == self.preview_key:
            dot.setPen(QPen(QColor(PREVIEW_RING), 3.5))
            dot.setZValue(3.5 + depth)
        elif key in self.match_keys:
            dot.setPen(QPen(QColor(MATCH_RING), 2.5))
            dot.setZValue(3 + depth)
        elif key in self.highlighted:
            pen = QPen(QColor(PLAYLIST_RING), 3)
            if key in self._markers:
                pen.setStyle(Qt.DashLine)  # not in the List: shown only because it is selected in the Playlist
            dot.setPen(pen)
            dot.setZValue(2.5 + depth)
        else:
            dot.setPen(QPen(QColor(20, 20, 20, 160), 1))
            dot.setZValue(1 + depth)

    def criteria(self):
        return {name for name, action in self.edge_actions.items() if action.isChecked()}

    def _edges_changed(self, _checked=False):
        self.settings['Map edges'] = sorted(self.criteria())
        self.settings['Map edges between all'] = self.all_edges.isChecked()
        self.settings['Map lines per track'] = self.lines_per_track.value()
        self.settings['Map curved edges'] = self.curved_action.isChecked()
        self._draw_edges()
        if self.match_filter.currentData() == MATCHES_EDGES:
            self._update_suggestions()  # the closest matches follow the Edges choice

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
        visible = [key for key, dot in self.dots.items()
                   if dot.isVisible() and (key not in self._markers or key == self.selected_key)]
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
        """Work out which edges to show, then draw them."""
        criteria = self.criteria()
        self.status.setText(self._base_status)
        self._edge_layers = []
        if criteria and self.data is not None:
            for sources, alpha in self._edge_sources():
                edges = self._edges(criteria, sources)
                if len(edges) >= MAX_EDGES:
                    self.status.setText(f'Showing the first {MAX_EDGES} edges; filter the list to see fewer tracks. '
                                        + self._base_status)
                self._edge_layers.append((edges, alpha))
        self._paint_edges()

    def _paint_edges(self):
        """Draw the last worked-out edges at the dots' current positions (also after a 3D turn)."""
        for item in self.edge_items:
            self.scene.removeItem(item)
        self.edge_items = []
        self._draw_compare_line()
        for edges, alpha in self._edge_layers:
            self._add_edge_items(edges, alpha)

    def _edge_to(self, path, source, target):
        """Add a line from source to target to the path: an arc, or straight (Edges menu)."""
        start, end = self._scaled(source), self._scaled(target)
        path.moveTo(start)
        if not self.curved_action.isChecked():
            path.lineTo(end)
            return
        dx, dy = end.x() - start.x(), end.y() - start.y()
        middle = (start + end) / 2
        path.quadTo(QPointF(middle.x() - dy * CURVE_BEND, middle.y() + dx * CURVE_BEND), end)

    def _draw_compare_line(self):
        """Dashed line from the selected track to the compared one, in the colour of their mix."""
        ends = [self.dots.get(key) for key in (self.selected_key, self.preview_key)]
        if None in ends or not all(dot.isVisible() for dot in ends):
            return
        mix, _similarity = self.relation(self.preview_key)
        pen = QPen(QColor(EDGE_COLORS[mix.name] if mix is not None else PREVIEW_RING), 2.5, Qt.DashLine)
        pen.setCosmetic(True)
        path = QPainterPath()
        self._edge_to(path, self.selected_key, self.preview_key)
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        item.setZValue(0.5)  # above the other edges, below the dots
        self.scene.addItem(item)
        self.edge_items.append(item)

    def _add_edge_items(self, edges, alpha):
        """One path item per reason, colour and opacity step (thousands of single lines would be
        slow). The most similar pair of the layer gets `alpha`, the least similar 15 % of it."""
        paths = {}
        strengths = [similarity for *_, similarity in edges]
        low, high = (min(strengths), max(strengths)) if strengths else (0, 0)
        for source, target, reason, similarity in edges:
            if reason == EDGE_SAME_COLOR:
                colour = (track_qcolor(display_color(self.fields[source])) or QColor(NO_COLOR)).name()
            else:
                colour = EDGE_COLORS[reason]
            level = round((STRENGTH_LEVELS - 1) * (similarity - low) / (high - low)) if high > low \
                else STRENGTH_LEVELS - 1
            path = paths.setdefault((reason, colour, level), QPainterPath())
            self._edge_to(path, source, target)
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
        mode = self.match_filter.currentData()
        self.settings['Map match filter'] = mode
        self.settings.pop('Map harmonic only', None)  # replaced by 'Map match filter'
        self.settings['Map match count'] = self.match_count.value()
        criteria = self.criteria()
        harmonic_criteria = criteria & set(MIX_TYPES_BY_NAME)
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
                   if dot.isVisible() and key in self.data.row and key not in self._markers]
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
            if mode == MATCHES_HARMONIC and mix is None and keys_known:
                continue
            # Edges selection: a checked relation must link the two. Without a key a checked mix type cannot rule
            # the track out (as above); colour and rating can.
            if mode == MATCHES_EDGES and connection(source, target, criteria) is None \
                    and (keys_known or not harmonic_criteria):
                continue
            item = MatchItem([f'{score * 100:.0f} %', mix.label if mix else ('' if keys_known else NO_KEY_TEXT)]
                             + [target.get(name, '') for name in FIELD_LABELS])
            item.setData(0, SORT_ROLE, score)
            item.setData(1, SORT_ROLE, mix.weight if mix else 0)
            for column, name in enumerate(FIELD_LABELS, start=2):
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
