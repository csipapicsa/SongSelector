"""
Main window for the Traktor Key Calculator
"""

# ADD:
# When song is selected and it is not available then RED
import os
import json
import sqlite3
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QPushButton, QFileDialog, QTreeWidgetItem,
                            QLineEdit, QSlider, QSplitter, QStatusBar, QHeaderView, QDialog, QMessageBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QToolButton, QMenu, QAction, QTabWidget, QProgressDialog

from PyQt5.QtGui import QColor, QBrush, QIcon, QPixmap, QPainter

from traktor_key_calculator.config import DEFAULT_BPM, WINDOW_SIZE, MIN_BPM, MAX_BPM, SETTINGS_FILE, HEADER_LABELS, COLOR_MAPPING_CATEGORY
from traktor_key_calculator.config import COLOR_COLUMN_INDEX, HEADER_INDEX, OPEN_KEY_COLOR_MAPPING
from traktor_key_calculator.config import SS_RATING_COLUMN, SS_COLOR_COLUMN, DEFAULT_EMBEDDING_MODEL
from traktor_key_calculator.config import FIELD_LABELS, POSITION_COLUMN
from traktor_key_calculator.ui.delegates import ColorDotDelegate
from traktor_key_calculator.ui.tree_widgets import PoolTreeWidget, PlaylistTreeWidget, TrackItem
from traktor_key_calculator.core.data_manager import DataManager
from traktor_key_calculator.core.key_calculator import KeyCalculator

from traktor_key_calculator.ui.advanced_search_dialog import AdvancedSearchDialog
from traktor_key_calculator.ui.menu_bar import AppMenuBar
from traktor_key_calculator.ui.music_paths_dialog import MusicPathsDialog
from traktor_key_calculator.ui.coloring_dialog import ColoringDialog
from pathlib import Path
import pandas as pd
from traktor_key_calculator.core.track_import import (TrackImporter, ImportedTrackStore, merge_tracks,
                                                      enrich_ratings, drop_duplicate_paths)
from traktor_key_calculator.core.library_store import LibraryStore, LIBRARY_LIST, PLAYLIST_LIST
from traktor_key_calculator.core.tag_writer import EDITABLE_TAGS, write_tags
from traktor_key_calculator.core.embeddings import EmbeddingStore, MODEL_FILE_NAME, file_fingerprint
from traktor_key_calculator.ui.embedding_worker import EmbeddingAnalyzer
from traktor_key_calculator.ui.track_info_dialog import TrackInfoDialog
from traktor_key_calculator.ui.similarity_map import DEFAULT_HOVER_FIELDS, SimilarityMapWidget
from traktor_key_calculator.ui.map_settings_dialog import HoverFieldsDialog
from traktor_key_calculator.ui.theme import (DEFAULT_THEME, apply_theme, dim_text_colour, row_tint_alpha,
                                             status_style)
from mutagen import MutagenError
from traktor_key_calculator.core.traktor_collection import canonical_path, discover_collection
from traktor_key_calculator.core.key_formats import parse_key, parse_bpm
from traktor_key_calculator.core.search_filters import matches_condition, active_filters
from traktor_key_calculator.core.color_search import (COLOR_NAMES, SS_COLOR_TOKEN, parse_color_search,
                                                      replace_color_filter)
from traktor_key_calculator.ui.tree_widgets import audio_paths, dropped_paths, find_audio_files
from traktor_key_calculator.ui.traktor_watcher import CollectionWatcher
from traktor_key_calculator.ui.list_browser import ListBrowser, node_label
from traktor_key_calculator.ui.saved_lists import SavedListsMixin
from traktor_key_calculator.core.traktor_sync import apply_changes, collection_changes, seen_values, summary


PROGRESS_THRESHOLD = 25   # imports with more files than this show a progress dialog
IN_PLAYLIST_ROLE = Qt.UserRole + 10   # library row whose track is also on the playlist


class TraktorKeyCalculator(SavedListsMixin, QMainWindow):
    """Main application window"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Traktor Key Calculator")
        self.setGeometry(100, 100, WINDOW_SIZE[0], WINDOW_SIZE[1])
        
        # Initialize components
        self.key_calculator = KeyCalculator()
        self.data_manager = DataManager(self.status_message)

                # Load init
        with open(SETTINGS_FILE, "r") as f:
            self.settings = json.load(f)
        
        # Sort state
        self.sort_column = 0
        self.sort_ascending = True
        
        # Store all items for search functionality
        self.all_items = []

        # ---------------------
        # Advanced search state
        # ---------------------
        self.advanced_search_dialog = None
        self.advanced_filters = []

        with open(SETTINGS_FILE, "r") as f:
            self.settings = json.load(f)

            # Load advanced search settings
        self.current_advanced_search = self.settings.get("Advanced search", {
            'enabled': False,
            'filters': []
        })

        # Load music paths and coloring settings
        self.music_paths = self.settings.get("Music paths", [])
        self.coloring_mode = self.settings.get("Coloring mode", "song")
        # Upgrade this independent app's settings once so both panels show category dots.
        if not self.settings.get('Color display version'):
            for side in ('left', 'right'):
                visible = self.settings.setdefault('Visible column ' + side, list(HEADER_LABELS))
                if 'Color' not in visible:
                    visible.append('Color')
                self.settings.setdefault('Column sizes ' + side, {})['Color'] = 45
            self.settings['Color display version'] = 1

        # Enable the new rating column once, retaining subsequent user preferences.
        if not self.settings.get('Rating display version'):
            for side in ('left', 'right'):
                visible = self.settings.setdefault('Visible column ' + side, list(HEADER_LABELS))
                if 'Rating' not in visible:
                    visible.append('Rating')
                sizes = self.settings.setdefault('Column sizes ' + side, {})
                if sizes.get('Rating', 0) <= 0:
                    sizes['Rating'] = 70
            searchable = self.settings.setdefault('Search columns', list(HEADER_LABELS))
            if 'Rating' not in searchable:
                searchable.append('Rating')
            self.settings['Rating display version'] = 1

        # 4.7: show and search the new Song Selector rating/color columns once.
        if not self.settings.get('Song Selector columns version'):
            for side in ('left', 'right'):
                visible = self.settings.setdefault('Visible column ' + side, list(HEADER_LABELS))
                sizes = self.settings.setdefault('Column sizes ' + side, {})
                for column, width in ((SS_RATING_COLUMN, 70), (SS_COLOR_COLUMN, 45)):
                    if column not in visible:
                        visible.append(column)
                    if sizes.get(column, 0) <= 0:
                        sizes[column] = width
            searchable = self.settings.setdefault('Search columns', list(HEADER_LABELS))
            for column in (SS_RATING_COLUMN, SS_COLOR_COLUMN):
                if column not in searchable:
                    searchable.append(column)
            self.settings['Song Selector columns version'] = 1

        # 4.21: the playlist position column (#), shown once in both panels.
        if not self.settings.get('Position column version'):
            for side in ('left', 'right'):
                visible = self.settings.setdefault('Visible column ' + side, list(HEADER_LABELS))
                if POSITION_COLUMN not in visible:
                    visible.append(POSITION_COLUMN)
                sizes = self.settings.setdefault('Column sizes ' + side, {})
                if sizes.get(POSITION_COLUMN, 0) <= 0:
                    sizes[POSITION_COLUMN] = 36
            self.settings['Position column version'] = 1

        
        self.playlist_paths = set()
        collection_path = self.settings.get('Traktor collection') or discover_collection()
        self.settings['Traktor collection'] = collection_path
        self.importer = TrackImporter(collection_path)
        self.setAcceptDrops(True)

        # Initialize UI
        apply_theme(self.settings.get('Theme', DEFAULT_THEME))
        self.init_ui()
        self._init_import_menu()
        self._init_view_menu()

        # Load data: restore both panels as they were last saved
        self.library_store = LibraryStore(Path(SETTINGS_FILE).with_name('library.sqlite'))
        self.saved_imports = {}
        self.table = pd.DataFrame()
        self._restore_lists()
        self.populate_tree()
        self._init_browser()
        # Changes made in Traktor (key, BPM, colour, rating) come in after Traktor saves.
        self.collection_watcher = CollectionWatcher(collection_path, self)
        self.collection_watcher.loaded.connect(self._collection_changed)

        # Embeddings of every library track, analysed in the background
        self.embedding_store = EmbeddingStore(Path(SETTINGS_FILE).with_name('embeddings.sqlite'))
        self.embedding_analyzer = None
        self._init_analysis_menu()
        self.start_embedding_analysis()

        # Similarity map: second tab of the library panel
        self.similarity_map = SimilarityMapWidget(self.embedding_store, self.settings, self)
        self.similarity_map.request_add_to_playlist.connect(self._map_add_to_playlist)
        self.similarity_map.request_context_menu.connect(self._map_context_menu)
        self.similarity_map.selected.connect(self._select_in_list)
        self.similarity_map.fields_provider = self._fields_for_key
        self.similarity_map.playlist_keys = lambda: {canonical_path(path) for path in self.playlist_paths}
        self.library_tabs.addTab(self.similarity_map, 'Similarity map')
        self.library_tabs.currentChanged.connect(lambda _index: self._refresh_map())
        self._map_stale = True

    def apply_row_shading_from_color(self, item):
        color = None
        if self.coloring_mode == 'key':
            color = OPEN_KEY_COLOR_MAPPING.get(item.text(HEADER_INDEX['Open Key New']).lower())
        else:
            try:
                color = COLOR_MAPPING_CATEGORY.get(int(float(item.text(COLOR_COLUMN_INDEX))))
            except (TypeError, ValueError, OverflowError):
                pass
        brush = QBrush()
        if color is not None:
            shaded = QColor(color)
            shaded.setAlpha(row_tint_alpha())
            brush = QBrush(shaded)
        for column in range(len(HEADER_LABELS)):
            item.setBackground(column, brush)


    def status_message(self, message):
        """Display a message in the status bar"""
        self.status_bar.showMessage(message)
        
    def init_ui(self):
        """Initialize the user interface"""
        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        # -----------------
        # MENU BAR
        # -----------------
        self.menu_bar = AppMenuBar(self)
        self.setMenuBar(self.menu_bar)
        
        # Connect menu signals
        self.menu_bar.exit_requested.connect(self.close)
        self.menu_bar.reset_settings_requested.connect(self.reset_settings)
        self.menu_bar.music_paths_requested.connect(self.open_music_paths_dialog)
        self.menu_bar.coloring_settings_requested.connect(self.open_coloring_dialog)
        
        main_layout = QVBoxLayout(main_widget)
        
        # Create a splitter for the two panes
        self.splitter = QSplitter(Qt.Horizontal)
        
        # Left pane: the Playlist (the set, in order) and the Browser (collection, saved
        # playlists and smartlists), as two tabs
        left_pane = QWidget()
        pane_layout = QVBoxLayout(left_pane)
        pane_layout.setContentsMargins(0, 0, 0, 0)
        self.left_tabs = QTabWidget()
        pane_layout.addWidget(self.left_tabs)
        self.playlist_page = QWidget()
        left_layout = QVBoxLayout(self.playlist_page)

        # Playlist label
        playlist_label = QLabel("Playlist (Drag Tracks Here)")
        playlist_label.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(playlist_label)

        # Clear and save buttons
        playlist_buttons = QHBoxLayout()
        clear_playlist_btn = QPushButton("Clear Playlist")
        clear_playlist_btn.clicked.connect(self.clear_playlist)
        playlist_buttons.addWidget(clear_playlist_btn)
        save_playlist_btn = QPushButton("Save as Playlist...")
        save_playlist_btn.setToolTip('Save these tracks, in this order, under Playlists in the Browser tab')
        save_playlist_btn.clicked.connect(lambda: self.save_playlist_as())
        playlist_buttons.addWidget(save_playlist_btn)
        left_layout.addLayout(playlist_buttons)
        
        # Playlist tree
        self.playlist_tree = PlaylistTreeWidget(self)
        self.playlist_tree.setColumnCount(len(HEADER_LABELS))
        self.playlist_tree.setHeaderLabels(HEADER_LABELS)

        # Columns are resized by hand (Stretch mode made that impossible) and the widths are
        # saved on close under the same key. The mode is set before columns are hidden: set
        # after, Qt leaves each hidden column's old width as an empty gap.
        self.playlist_tree.header().setStretchLastSection(False)
        self.playlist_tree.header().setSectionResizeMode(QHeaderView.Interactive)
        visible_columns = self.settings.get("Visible column left", HEADER_LABELS)
        for col, name in enumerate(HEADER_LABELS):
            is_visible = name in visible_columns
            self.playlist_tree.setColumnHidden(col, not is_visible)
        column_sizes = self.settings.get("Column sizes left", {})
        for col, label in enumerate(HEADER_LABELS):
            width = column_sizes.get(label)
            if width is not None and width > 0:
                self.playlist_tree.setColumnWidth(col, width)
        left_layout.addWidget(self.playlist_tree)
        self.playlist_count_label = QLabel('')
        left_layout.addWidget(self.playlist_count_label)
        self.left_tabs.addTab(self.playlist_page, 'Playlist')
        self.list_browser = ListBrowser(self)
        self.list_browser.setToolTip('Click an entry to show its tracks in the List, or drag it there.\n'
                                     'Double-click a playlist or smartlist to load it into the Playlist tab.\n'
                                     'Drag tracks onto a playlist to add them. Right-click for more.')
        self.left_tabs.addTab(self.list_browser, 'Browser')


        # ------------------------------------------------------- # 
        # RIGHT PANEL
        # ------------------------------------------------------- #
        
        # Right pane for track pool
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        
        # -----------------
        # SEARCH BAR
        # -----------------
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search text or color:blue; e.g. tribal color:red,orange")
        self.search_bar.setClearButtonEnabled(True)
        self.search_bar.setToolTip("Filter Traktor category dots: color:blue, color:red,orange, color:none, or -color:blue.\nCombine with text; Colors lets you choose several swatches. Color filters work regardless of Search Columns.")
        self.search_bar.textChanged.connect(self.filter_items)
        search_layout.addWidget(self.search_bar)
        right_layout.addLayout(search_layout)

        # -----------------
        # DROPDOWN FOR SEARCH BAR
        # -----------------

        self.search_columns = self.settings.get("Search columns", HEADER_LABELS)

        # Dropdown for column selection
        self.search_column_button = QToolButton()
        self.search_column_button.setText("🔍 Search Columns")
        self.search_column_menu = QMenu()

        # Store checkbox actions
        self.search_column_actions = {}

        for column in FIELD_LABELS:
            action = QAction(column, self)
            action.setCheckable(True)
            action.setChecked(column in self.search_columns)
            action.toggled.connect(self.update_search_columns_from_menu)
            self.search_column_menu.addAction(action)
            self.search_column_actions[column] = action

        self.search_column_button.setMenu(self.search_column_menu)
        self.search_column_button.setPopupMode(QToolButton.InstantPopup)

        # Add to layout (replace/add to your top layout)
        search_layout.addWidget(self.search_column_button)
        self.color_search_button = QToolButton()
        self.color_search_button.setText('Colors')
        self.color_search_button.setToolTip('Filter Traktor category dots; choose one or more colors.')
        self.color_search_menu = QMenu(self.color_search_button)
        clear_colors = self.color_search_menu.addAction('Clear color selection')
        clear_colors.triggered.connect(lambda: self.search_bar.setText(replace_color_filter(self.search_bar.text(), set())))
        self.color_search_menu.addSeparator()
        self.color_search_actions = {}
        for number, name in COLOR_NAMES.items():
            action = QAction('No color' if number == 0 else name.title(), self)
            if number:
                action.setIcon(self._color_swatch(number))
            action.setCheckable(True)
            action.toggled.connect(self.update_color_search)
            self.color_search_menu.addAction(action)
            self.color_search_actions[number] = action
        self.color_search_button.setMenu(self.color_search_menu)
        self.color_search_button.setPopupMode(QToolButton.InstantPopup)
        search_layout.addWidget(self.color_search_button)


        # -----------------
        # SEARCH BAR ADVACNED
        # -----------------

        self.btn_advanced_search = QPushButton("Advanced Search")
        self.btn_advanced_search.clicked.connect(self.open_advanced_search)
        search_layout.addWidget(self.btn_advanced_search)


        
        # Control section
        control_widget = QWidget()
        control_layout = QHBoxLayout(control_widget)
        
        # BPM slider
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("Master Tempo (BPM):"))
        
        self.bpm_slider = QSlider(Qt.Horizontal)
        self.bpm_slider.setMinimum(MIN_BPM)
        self.bpm_slider.setMaximum(MAX_BPM)
        self.bpm_slider.setValue(int(self.settings.get("Master Tempo", DEFAULT_BPM)))
        self.bpm_slider.setTickInterval(10)
        self.bpm_slider.setTickPosition(QSlider.TicksBelow)
        
        # Changed to update only BPM label during sliding
        self.bpm_slider.valueChanged.connect(self.update_bpm_label)
        # Update tree when slider is released
        self.bpm_slider.sliderReleased.connect(self.update_tree_after_slider)
        
        
        slider_layout.addWidget(self.bpm_slider)
        
        self.bpm_label = QLabel(f"{self.bpm_slider.value():.1f} BPM")
        slider_layout.addWidget(self.bpm_label)
        
        control_layout.addLayout(slider_layout)
        
        # Buttons
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip('Rebuild the library list from the default CSV plus all imported tracks')
        self.refresh_button.clicked.connect(self.refresh_data)
        control_layout.addWidget(self.refresh_button)
        
        self.load_csv_button = QPushButton("Load CSV")
        self.load_csv_button.setToolTip('Replace the library list with a CSV file plus all imported tracks')
        self.load_csv_button.clicked.connect(self.load_csv)
        control_layout.addWidget(self.load_csv_button)
        
        # Add control section to right layout
        right_layout.addWidget(control_widget)
        
        # Add button to add selected item to playlist
        add_to_playlist_btn = QPushButton("Add Selected to Playlist")
        add_to_playlist_btn.clicked.connect(self.add_selected_to_playlist)
        right_layout.addWidget(add_to_playlist_btn)
        
        # Tree widget for track pool
        self.candidate_tree = PoolTreeWidget(self)
        self.candidate_tree.setColumnCount(len(HEADER_LABELS))
        self.candidate_tree.setHeaderLabels(HEADER_LABELS)
        
        # Set column widths
        self.candidate_tree.header().setStretchLastSection(False)

        
        visible_columns = self.settings.get("Visible column right", HEADER_LABELS)
        for col, name in enumerate(HEADER_LABELS):
            is_visible = name in visible_columns
            self.candidate_tree.setColumnHidden(col, not is_visible)

        column_sizes = self.settings.get("Column sizes right", {})
        for col, label in enumerate(HEADER_LABELS):
            width = column_sizes.get(label)
            if width is not None and width > 0:
                self.candidate_tree.setColumnWidth(col, width)

                    # Set up context menus for headers
        self.playlist_tree.header().setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_tree.header().customContextMenuRequested.connect(
            lambda pos: self.show_header_context_menu(pos, self.playlist_tree))
        
        self.candidate_tree.header().setContextMenuPolicy(Qt.CustomContextMenu)
        self.candidate_tree.header().customContextMenuRequested.connect(
            lambda pos: self.show_header_context_menu(pos, self.candidate_tree))
        
        # Disable automatic sorting
        self.candidate_tree.header().setSectionsClickable(True)
        
        # Connect header click event
        self.candidate_tree.header().sectionClicked.connect(self.on_header_clicked)
        
        # Connect double-click
        self.candidate_tree.itemDoubleClicked.connect(self.on_item_double_clicked)

        # Right-click menu on library rows
        self.candidate_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.candidate_tree.customContextMenuRequested.connect(
            lambda pos: self.show_track_context_menu(self.candidate_tree, pos))
        
        # Bar above the List while it shows one Browser entry
        self.source_bar = QWidget()
        source_layout = QHBoxLayout(self.source_bar)
        source_layout.setContentsMargins(0, 0, 0, 0)
        self.source_label = QLabel('')
        self.source_label.setStyleSheet(status_style('warning', bold=True))
        source_layout.addWidget(self.source_label, 1)
        self.source_clear_button = QPushButton('Show all tracks')
        source_layout.addWidget(self.source_clear_button)
        self.source_bar.hide()
        right_layout.addWidget(self.source_bar)

        # Add tree to right layout
        self.library_tabs = QTabWidget()
        self.library_tabs.addTab(self.candidate_tree, 'List')
        self.list_count_label = QLabel('')
        self.list_count_label.setToolTip('Tracks the List view shows (after search and filters) and how many of them are selected')
        self.library_tabs.setCornerWidget(self.list_count_label, Qt.TopRightCorner)
        right_layout.addWidget(self.library_tabs)
        # Hovering a drag over a tab opens it (e.g. a playlist from the Browser to the Playlist tab)
        for tabs in (self.left_tabs, self.library_tabs):
            tabs.tabBar().setChangeCurrentOnDrag(True)
            tabs.tabBar().setAcceptDrops(True)
        # The # column comes first
        for tree in (self.playlist_tree, self.candidate_tree):
            tree.header().moveSection(tree.header().visualIndex(HEADER_INDEX[POSITION_COLUMN]), 0)

        # Track counts under the playlist and next to the tabs. Many changes arrive at once
        # (thousands of rows added on load), so they are counted once afterwards.
        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.timeout.connect(self._update_counts)
        for tree in (self.playlist_tree, self.candidate_tree):
            tree.itemSelectionChanged.connect(self._count_timer.start)
            for signal in (tree.model().rowsInserted, tree.model().rowsRemoved, tree.model().modelReset):
                signal.connect(self._count_timer.start)
        
        # Add panes to splitter
        self.splitter.addWidget(left_pane)
        self.splitter.addWidget(right_pane)
        
        # Set initial sizes (30% for playlist, 70% for pool)
        self.splitter.setSizes([300, 700])
        
        # Add splitter to main layout
        main_layout.addWidget(self.splitter)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.playlist_tree.header().setSectionsMovable(True)
        self.candidate_tree.header().setSectionsMovable(True)
        # self.status_bar.showMessage("Ready")
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(status_style('info'))
        self.status_bar.addPermanentWidget(self.status_label)
        self.embedding_label = QLabel('')
        self.status_bar.addPermanentWidget(self.embedding_label)


        # ---------------
        # COLOR CODES
        # ---------------

        # Apply the color dot delegate to the "Color" column (index 9)
        # color_column_index = HEADER_LABELS.index("Color")
        # self.candidate_tree.setItemDelegateForColumn(color_column_index, ColorDotDelegate(self))
        # self.playlist_tree.setItemDelegateForColumn(color_column_index, ColorDotDelegate(self))


        self.color_delegate = ColorDotDelegate(self.candidate_tree)
        self.candidate_tree.setItemDelegateForColumn(COLOR_COLUMN_INDEX, self.color_delegate)
        self.candidate_tree.setItemDelegateForColumn(HEADER_INDEX[SS_COLOR_COLUMN], self.color_delegate)

        # Right-click menu on playlist rows (the library's is connected above)
        self.playlist_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_tree.customContextMenuRequested.connect(
            lambda pos: self.show_track_context_menu(self.playlist_tree, pos))

    def show_header_context_menu(self, pos, tree_widget):
        """Show context menu for column headers"""
        menu = QMenu(self)
        header = tree_widget.header()

            # Add "Show All" option at the top
        show_all_action = QAction("Show All Columns", self)
        show_all_action.triggered.connect(lambda: self.show_all_columns(tree_widget))
        menu.addAction(show_all_action)
        menu.addSeparator()
        
        # Add menu items for each column
        for i in range(tree_widget.columnCount()):
            column_name = tree_widget.headerItem().text(i)
            action = QAction(column_name, self)
            action.setCheckable(True)
            action.setChecked(not tree_widget.isColumnHidden(i))
            
            # Connect to toggle function
            action.triggered.connect(lambda checked, col=i, tree=tree_widget: 
                                    self.toggle_column_visibility(checked, col, tree))
            menu.addAction(action)
        
        # Show the menu
        menu.exec_(header.mapToGlobal(pos))

    def show_all_columns(self, tree_widget):
        """Show all columns in the tree widget"""
        for i in range(tree_widget.columnCount()):
            tree_widget.setColumnHidden(i, False)

    def toggle_column_visibility(self, checked, column, tree_widget):
        """Toggle visibility of a column"""
        tree_widget.setColumnHidden(column, not checked)

    def add_selected_to_playlist(self):
        items = self.candidate_tree.selectedItems()
        if not items:
            self.status_label.setText('Select a track first')
            return
        rows = self._rows_by_path()
        for item in items:
            row = rows.get(canonical_path(item.text(HEADER_INDEX['Path'])))
            if row is not None:
                self._add_to_playlist(row)
        self._save_playlist()
        self.filter_items()


    def clear_playlist(self):
        self.playlist_tree.clear()
        self.playlist_paths.clear()
        self._save_playlist()
        self.filter_items()
        self.status_label.setText('Playlist cleared')

    
    def update_bpm_label(self):
        """Update only the BPM label when slider moves"""
        bpm = self.bpm_slider.value()
        self.bpm_label.setText(f"{bpm:.1f} BPM")
    
    def update_tree_after_slider(self):
        """Update the tree when slider is released"""
            # Save current sort state
        self.populate_tree()


    def apply_advanced_filters_tree(self, item):
        """Every active text or numeric condition must match."""
        return self._matches_rules(item, self.advanced_filters)

    def _matches_rules(self, item, rules):
        """Every rule ({'column', 'condition', 'value'}) matches this row."""
        columns = {self.candidate_tree.headerItem().text(index): index
                   for index in range(self.candidate_tree.columnCount())}
        for condition in rules:
            column = condition['column']
            index = columns.get(column)
            if index is None:
                continue
            if not matches_condition(item.text(index), condition['condition'], condition['value'], column):
                return False
        return True


    def filter_items(self):
        color_query = parse_color_search(self.search_bar.text())
        ss_color_query = parse_color_search(color_query.text, SS_COLOR_TOKEN)
        search_text = ss_color_query.text.casefold()
        if hasattr(self, 'color_search_actions'):
            for number, action in self.color_search_actions.items():
                action.blockSignals(True)
                action.setChecked(number in color_query.included)
                action.blockSignals(False)
            count = len(color_query.included)
            self.color_search_button.setText(f'Colors ({count})' if count else 'Colors')
        search_indices = [HEADER_INDEX[name] for name in self.search_columns if name in FIELD_LABELS]
        playlist_paths = {canonical_path(path) for path in self.playlist_paths}
        # A saved playlist shown in the List shows all its tracks (those on the Playlist tab dimmed)
        hide_playlist_tracks = (self.settings.get('Hide playlist tracks', False)
                                and not (self.list_source and self.list_source['kind'] == 'playlist'))
        advanced =bool(self.current_advanced_search.get('enabled') and self.advanced_filters)
        in_playlist_matches = 0
        for index in range(self.candidate_tree.topLevelItemCount()):
            item = self.candidate_tree.topLevelItem(index)
            key = canonical_path(item.text(HEADER_INDEX['Path']))
            in_playlist = key in playlist_paths
            if bool(item.data(0, IN_PLAYLIST_ROLE)) != in_playlist:
                item.setData(0, IN_PLAYLIST_ROLE, in_playlist)
                self._apply_text_colours(item)
            matches = (self._in_source(item, key)
                       and color_query.matches(item.text(COLOR_COLUMN_INDEX))
                       and ss_color_query.matches(item.text(HEADER_INDEX[SS_COLOR_COLUMN])))
            if matches and search_text:
                matches = any(search_text in item.text(column).casefold() for column in search_indices)
            if matches and advanced:
                matches = self.apply_advanced_filters_tree(item)
            in_playlist_matches += matches and in_playlist
            item.setHidden(not matches or (in_playlist and hide_playlist_tracks))
        self._show_advanced_search_state()
        visible = sum(not self.candidate_tree.topLevelItem(i).isHidden()
                      for i in range(self.candidate_tree.topLevelItemCount()))
        message = f'Displaying {visible} of {self.candidate_tree.topLevelItemCount()} tracks'
        if in_playlist_matches:
            message += (f'; {in_playlist_matches} more in the playlist (hidden, see View menu)' if hide_playlist_tracks
                        else f'; {in_playlist_matches} in the playlist (dimmed)')
        if advanced:
            message += '; Advanced Search is on'
        if self.list_source is not None:
            message += f'; {node_label(self.list_source)}'
        self.status_label.setStyleSheet(status_style('ok'))
        self.status_label.setText(message)
        self._count_timer.start()
        if color_query.error or ss_color_query.error:
            self.status_label.setStyleSheet(status_style('error'))
            self.status_label.setText(color_query.error or ss_color_query.error)
        self._refresh_map()


    def update_color_search(self, _checked=False):
        selected = {number for number, action in self.color_search_actions.items() if action.isChecked()}
        self.search_bar.setText(replace_color_filter(self.search_bar.text(), selected))

    def apply_advanced_filters(self, row):
        """Apply all advanced filters to a row - ALL must match"""
        for filter_data in self.advanced_filters:
            column = filter_data['column']
            condition = filter_data['condition']
            value = filter_data['value'].lower()
            
            # Find column index
            col_index = None
            for i in range(self.table.columnCount()):
                if self.table.horizontalHeaderItem(i).text() == column:
                    col_index = i
                    break
            
            if col_index is None:
                continue
                
            item = self.table.item(row, col_index)
            if not item:
                return False
                
            cell_value = item.text().lower()
            
            # Apply condition
            match = False
            if condition == 'contains':
                match = value in cell_value
            elif condition == 'does not contain':
                match = value not in cell_value
            elif condition == 'is':
                match = value == cell_value
            elif condition == 'is not':
                match = value != cell_value
            
            if not match:
                return False  # If any filter fails, hide row
        
        return True  # All filters passed

    
    def on_header_clicked(self, column):
        """Qt has sorted the list already (sorting is enabled; TrackItem gives the order)."""
        self.sort_column = column
        self.sort_ascending = self.candidate_tree.header().sortIndicatorOrder() == Qt.AscendingOrder
        direction = 'ascending' if self.sort_ascending else 'descending'
        self.status_label.setStyleSheet(status_style('info'))
        self.status_label.setText(f'Sorted by {self.candidate_tree.headerItem().text(column)} ({direction})')

    def sort_by_column(self, column, ascending=None):
        """Sort the library list; by default the same column again reverses the order."""
        if ascending is None:
            ascending = not self.sort_ascending if column == self.sort_column else True
        self.sort_column, self.sort_ascending = column, ascending
        self.candidate_tree.sortItems(column, Qt.AscendingOrder if ascending else Qt.DescendingOrder)

    def on_item_double_clicked(self, item, column):
        """Handle double-click on tree item"""
        file_path = item.text(HEADER_INDEX.get("Path"))
        if file_path and os.path.exists(file_path):
            os.startfile(file_path)
            self.status_bar.showMessage(f"Opened file: {os.path.basename(file_path)}")
            message = f"Opened file: {os.path.basename(file_path)}"
            self.status_label.setStyleSheet(status_style('info'))
            self.status_label.setText(message)
        else:
            self.status_bar.showMessage(f"🔴 File not found: {file_path}")
            message = f"🔴 File not found: {file_path}"
            self.status_label.setStyleSheet(status_style('error'))
            self.status_label.setText(message)
    
    def _load_library(self, table):
        merged = merge_tracks(table, self.saved_imports.values())
        return self._with_user_fields(enrich_ratings(merged, self.importer.collection))

    def _collection_changed(self, collection):
        """Traktor saved its collection: take the values changed in Traktor into the library,
        all at once (see core/traktor_sync.py)."""
        self.importer.collection = collection  # imports use the fresh copy, no second read
        try:
            seen = self.library_store.traktor_seen()
        except sqlite3.Error as error:
            self.status_bar.showMessage(f'Traktor sync skipped: {error}')
            return
        changes = collection_changes(self.table, collection.by_path, seen)
        now = {key: seen_values(record) for key, record in collection.by_path.items()}
        try:
            self.library_store.save_traktor_seen({key: values for key, values in now.items() if seen.get(key) != values})
        except sqlite3.Error as error:
            self.status_bar.showMessage(f'Could not save the Traktor sync state: {error}')
        if not changes:
            return
        self.table = apply_changes(self.table, changes)
        self.data_manager.table = self.table
        rows = {}
        for index, changed in changes.items():
            key = canonical_path(self.table.at[index, 'File_Path'])
            rows[key] = self.table.loc[index]
            if key in self.saved_imports:  # Refresh rebuilds the list from these
                self.saved_imports[key].update(changed)
        error = self._save_library()
        for tree in (self.candidate_tree, self.playlist_tree):
            for item_index in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(item_index)
                row = rows.get(canonical_path(item.text(HEADER_INDEX['Path'])))
                if row is not None:
                    self._track_item(row, item)
        error = self._save_playlist() or error
        self.filter_items()  # changed values may (no longer) match the search
        message = f'Updated from Traktor: {summary(changes)}'
        self.status_label.setStyleSheet(status_style('error') if error else status_style('ok'))
        self.status_label.setText(error or message)
        self.status_bar.showMessage(message)

    def _restore_lists(self):
        """Load the library and playlist saved at the last change.

        On the first start (no saved library list yet) the library is built from the
        default CSV plus imports saved by versions up to 4.5.0 in imported_tracks.json.
        That file is only read, and is kept as a backup.
        """
        try:
            if self.library_store.track_count() == 0:
                legacy = ImportedTrackStore(Path(SETTINGS_FILE).with_name('imported_tracks.json')).load()
                self.library_store.upsert_tracks(legacy.values())
            self.saved_imports = self.library_store.imported_tracks()
            saved_library = self.library_store.load_list(LIBRARY_LIST)
            saved_playlist = self.library_store.load_list(PLAYLIST_LIST) or []
        except sqlite3.Error as error:
            # Never overwrite the saved lists after a failed read; run without them.
            self.status_bar.showMessage(f'Could not read {self.library_store.path}: {error}')
            self.table = self._load_library(self.data_manager.load_default_data())
            return
        if saved_library is None:
            self.table = self._load_library(self.data_manager.load_default_data())
            self._save_library()
        else:
            self.table = enrich_ratings(pd.DataFrame(saved_library), self.importer.collection)
        self.data_manager.table = self.table
        for record in saved_playlist:
            self._add_to_playlist(record)
        self._renumber_playlist()

    def _save_list(self, name, records):
        """Persist one list; returns an error message, or '' on success."""
        try:
            self.library_store.save_list(name, records)
            return ''
        except (sqlite3.Error, OSError) as error:
            message = f'Could not save the {name.lower()} list: {error}'
            self.status_bar.showMessage(message)
            return message

    def _save_library(self):
        return self._save_list(LIBRARY_LIST, self.table.to_dict('records') if self.table is not None else [])

    def _renumber_playlist(self):
        for index in range(self.playlist_tree.topLevelItemCount()):
            self.playlist_tree.topLevelItem(index).setText(HEADER_INDEX[POSITION_COLUMN], str(index + 1))

    def _playlist_records(self):
        """Records of the Playlist tab's tracks, in order: library rows, else the collection's."""
        keys = [canonical_path(self.playlist_tree.topLevelItem(i).text(HEADER_INDEX['Path']))
                for i in range(self.playlist_tree.topLevelItemCount())]
        records = {}
        if self.table is not None and 'File_Path' in self.table:
            subset = self.table[self.table['File_Path'].map(canonical_path).isin(keys)]
            for row in subset.to_dict('records'):
                records.setdefault(canonical_path(row['File_Path']), row)
        missing = [key for key in keys if key not in records]
        if missing:
            try:
                records.update(self.library_store.tracks(missing))
            except sqlite3.Error:
                pass
        return [records[key] for key in keys if key in records]

    def _save_playlist(self):
        self._renumber_playlist()
        return self._save_list(PLAYLIST_LIST, self._playlist_records())

    def delete_duplicate_tracks(self):
        """Remove library rows whose path repeats an earlier row. Files on disk are untouched."""
        self.table, removed = drop_duplicate_paths(self.table)
        error = ''
        if removed:
            self.data_manager.table = self.table
            error = self._save_library()
            self.populate_tree()
        message = (f'Removed {removed} duplicate row(s) from the list; files on disk were not changed'
                   if removed else 'No duplicate paths in the list')
        self.status_label.setStyleSheet(status_style('error') if error else status_style('ok'))
        self.status_label.setText(error or message)
        return removed

    def track_context_menu(self, tree):
        """Right-click menu for the selected rows of the library or playlist panel."""
        menu = QMenu(self)
        paths = tree.selected_paths()
        item = tree.currentItem()
        current = item.text(HEADER_INDEX['Path']) if item is not None and item.isSelected() else ''
        edit = menu.addAction('Edit track info (Artist, Title, Genre, Comment)...')
        edit.setToolTip('Edits one track; with several rows selected, the one clicked last.')
        edit.setEnabled(bool(current))
        edit.triggered.connect(lambda: self.open_track_info_dialog(current))

        count = f' ({len(paths)} tracks)' if len(paths) > 1 else ''
        rating_menu = menu.addMenu('Rating - Song Selector' + count)
        for stars in range(5, 0, -1):
            action = rating_menu.addAction('★' * stars + '☆' * (5 - stars) + f'  ({stars})')
            action.triggered.connect(lambda _checked, value=stars: self.set_song_selector_fields(paths, SS_Rating=value))
        rating_menu.addSeparator()
        rating_menu.addAction('Clear rating').triggered.connect(
            lambda: self.set_song_selector_fields(paths, SS_Rating=None))

        color_menu = menu.addMenu('Color - Song Selector' + count)
        for number, name in COLOR_NAMES.items():
            if number:
                action = color_menu.addAction(self._color_swatch(number), name.title())
                action.triggered.connect(lambda _checked, value=number: self.set_song_selector_fields(paths, SS_Color=value))
        color_menu.addSeparator()
        color_menu.addAction('Clear color').triggered.connect(
            lambda: self.set_song_selector_fields(paths, SS_Color=None))
        rating_menu.setEnabled(bool(paths))
        color_menu.setEnabled(bool(paths))

        menu.addSeparator()
        remove = menu.addAction(f'Remove from {"library" if tree is self.candidate_tree else "playlist"}{count}\tDel')
        remove.setToolTip('Removes the rows from this list only. Files on disk are not deleted.')
        remove.setEnabled(bool(paths))
        remove.triggered.connect(lambda: self.remove_selected_tracks(tree))
        remove_missing = menu.addAction('Remove missing files from the list')
        remove_missing.setToolTip('Removes every row whose file no longer exists on disk.')
        remove_missing.triggered.connect(lambda: self.remove_missing_tracks(tree))
        if tree is self.candidate_tree:
            delete_duplicates = menu.addAction('Delete duplicates from the list')
            delete_duplicates.setToolTip('Remove rows with the same file path. Files on disk are not deleted.')
            delete_duplicates.triggered.connect(self.delete_duplicate_tracks)
        return menu

    def remove_selected_tracks(self, tree, confirm=True):
        """Remove the selected rows from the library or playlist list (Delete key)."""
        return self._remove_tracks(tree, tree.selected_paths(), confirm, 'track(s)')

    def remove_missing_tracks(self, tree, confirm=True):
        """Remove every row of this panel's list whose file no longer exists, including
        rows hidden by the current search."""
        if tree is self.playlist_tree:
            paths = [tree.topLevelItem(i).text(HEADER_INDEX['Path']) for i in range(tree.topLevelItemCount())]
        else:
            paths = [path for path in self.table['File_Path'] if isinstance(path, str)] \
                if self.table is not None and 'File_Path' in self.table else []
        missing = [path for path in paths if path and not os.path.isfile(path)]
        if not missing:
            self.status_label.setStyleSheet(status_style('ok'))
            self.status_label.setText('No missing files in the list')
            return 0
        return self._remove_tracks(tree, missing, confirm, 'missing file(s)')

    def _remove_tracks(self, tree, paths, confirm, what):
        """Remove rows with these paths from the library or playlist list.

        Only the list changes: the tracks stay in the collection (library.sqlite) with
        their ratings and embeddings, and files on disk are untouched.
        """
        if not paths:
            return 0
        keys = {canonical_path(path) for path in paths}
        if tree is self.playlist_tree:
            for index in reversed(range(tree.topLevelItemCount())):
                if canonical_path(tree.topLevelItem(index).text(HEADER_INDEX['Path'])) in keys:
                    tree.takeTopLevelItem(index)
            self.playlist_paths = {path for path in self.playlist_paths if canonical_path(path) not in keys}
            error = self._save_playlist()
            self.filter_items()  # removed playlist tracks show up in the library again
            where = 'playlist'
        else:
            if confirm and QMessageBox.question(
                    self, 'Remove from library',
                    f'Remove {len(keys)} {what} from the library list?\n\n'
                    'The files on disk are not deleted. Refresh rebuilds the full list.',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return 0
            mask = self._rows_mask(paths)
            self.table = self.table.loc[~mask].reset_index(drop=True)
            self.data_manager.table = self.table
            error = self._save_library()
            self.populate_tree()
            where = 'library'
        self.status_label.setStyleSheet(status_style('error') if error else status_style('ok'))
        self.status_label.setText(error or f'Removed {len(keys)} {what} from the {where}; files on disk were not changed')
        return len(keys)

    def library_context_menu(self):
        return self.track_context_menu(self.candidate_tree)

    def show_track_context_menu(self, tree, pos):
        item = tree.itemAt(pos)
        if item is not None and not item.isSelected():
            tree.setCurrentItem(item)  # right-click outside the selection selects just that row
        self.track_context_menu(tree).exec_(tree.viewport().mapToGlobal(pos))

    @staticmethod
    def _color_swatch(number):
        swatch = QPixmap(18, 18)
        swatch.fill(Qt.transparent)
        painter = QPainter(swatch)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(COLOR_MAPPING_CATEGORY[number])
        painter.drawEllipse(2, 2, 14, 14)
        painter.end()
        return QIcon(swatch)

    def _rows_mask(self, paths):
        keys = {canonical_path(path) for path in paths}
        if self.table is None or 'File_Path' not in self.table:
            return None
        return self.table['File_Path'].map(canonical_path).isin(keys)

    def _rerender(self, paths):
        """Redraw the rows of these paths in both panels after their data changed."""
        mask = self._rows_mask(paths)
        if mask is None or not mask.any():
            return
        rows = {}
        for row in self.table.loc[mask].to_dict('records'):
            rows.setdefault(canonical_path(row['File_Path']), row)
        for tree in (self.candidate_tree, self.playlist_tree):
            for index in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(index)
                row = rows.get(canonical_path(item.text(HEADER_INDEX['Path'])))
                if row is not None:
                    self._track_item(row, item)
        self.list_browser.set_collection(self.table)  # e.g. an edited artist
        self.filter_items()

    def set_song_selector_fields(self, paths, **fields):
        """Set the app's own rating/color (SS_Rating, SS_Color; None clears) for tracks."""
        mask = self._rows_mask(paths)
        if mask is None or not mask.any():
            return False
        updated = self.table.copy()
        for name, value in fields.items():
            if name not in updated:
                updated[name] = None
            updated[name] = updated[name].astype(object)
            updated.loc[mask, name] = value
        try:
            self.library_store.set_user_fields(updated.loc[mask].to_dict('records'), **fields)
        except (sqlite3.Error, OSError, ValueError) as error:
            self.status_label.setStyleSheet(status_style('error'))
            self.status_label.setText(f'Could not save: {error}')
            return False
        self.table = updated
        self.data_manager.table = self.table
        self._rerender(paths)
        return True

    def _with_user_fields(self, table):
        """Overlay the stored Song Selector fields on a table built from CSV or tags."""
        try:
            stored = self.library_store.user_fields()
        except sqlite3.Error:
            return table
        if table is None or table.empty or 'File_Path' not in table:
            return table
        result = table.copy()
        keys = result['File_Path'].map(canonical_path)
        for name in ('SS_Rating', 'SS_Color'):
            result[name] = keys.map(lambda key: stored.get(key, {}).get(name)).astype(object)
        return result

    def open_track_info_dialog(self, path):
        mask = self._rows_mask([path])
        if mask is None or not mask.any():
            return
        row = self.table.loc[mask].iloc[0]
        dialog = TrackInfoDialog(path, {name: self._text(row.get(name)) for name in EDITABLE_TAGS}, self)
        if dialog.exec_() == QDialog.Accepted:
            self.edit_track_tags(path, **dialog.changed_values())

    def edit_track_tags(self, path, **values):
        """Write Artist/Title/Genre/Comment into the audio file, then update the library to match."""
        if not values:
            return True
        key = canonical_path(path)
        try:
            before = file_fingerprint(path)
            embedding_current = self.embedding_store.fingerprints().get(key) == before
        except (OSError, sqlite3.Error):
            embedding_current = False
        try:
            write_tags(path, **values)
        except (ValueError, OSError, MutagenError) as error:
            QMessageBox.warning(self, 'Cannot write tags', f'{path}\n\n{error}')
            return False
        # Re-read the file like a fresh import (so the edit also survives Refresh / Load CSV),
        # keeping exactly the values the user entered.
        mask = self._rows_mask([path])
        existing = self.table.loc[mask].iloc[0] if mask is not None and mask.any() else None
        record = self.importer.read(path, existing=existing)
        record.update(values)
        self.saved_imports[canonical_path(record['File_Path'])] = record
        self.table = merge_tracks(self.table, [record])
        self.data_manager.table = self.table
        error = self._save_library()
        if embedding_current:  # only tags changed, the audio did not
            try:
                self.embedding_store.update_fingerprint(key, file_fingerprint(path))
            except (OSError, sqlite3.Error):
                pass
        self._rerender([path])
        self.status_label.setStyleSheet(status_style('error') if error else status_style('ok'))
        self.status_label.setText(error or f'Saved {", ".join(values)} to {Path(path).name}')
        return not error

    # -- embeddings ---------------------------------------------------------

    def _init_view_menu(self):
        menu = self.menuBar().addMenu('View')
        self.dark_theme_action = menu.addAction('Dark theme')
        self.dark_theme_action.setCheckable(True)
        self.dark_theme_action.setChecked(self.settings.get('Theme', DEFAULT_THEME) == 'dark')
        self.dark_theme_action.toggled.connect(lambda dark: self.set_theme('dark' if dark else 'light'))
        self.hide_playlist_action = menu.addAction('Hide playlist tracks in the library')
        self.hide_playlist_action.setCheckable(True)
        self.hide_playlist_action.setChecked(self.settings.get('Hide playlist tracks', False))
        self.hide_playlist_action.setToolTip('Off: tracks on the playlist stay in the library list, dimmed.')
        self.hide_playlist_action.toggled.connect(self.set_hide_playlist_tracks)
        menu.addSeparator()
        list_view = menu.addAction('Library list')
        list_view.setShortcut('Ctrl+1')
        list_view.triggered.connect(lambda: self.library_tabs.setCurrentIndex(0))
        map_view = menu.addAction('Similarity map')
        map_view.setShortcut('Ctrl+2')
        map_view.triggered.connect(lambda: self.library_tabs.setCurrentIndex(1))
        menu.addAction('Map hover details...').triggered.connect(self.choose_hover_fields)

    # -- similarity map -----------------------------------------------------

    def _update_counts(self):
        """'1,234 of 3,489 tracks, 3 selected' for the List view; '28 tracks, 2 selected' for
        the playlist. Selected rows hidden by a search are not counted."""
        def counts(tree):
            items = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
            shown = [item for item in items if not item.isHidden()]
            return len(items), len(shown), sum(item.isSelected() for item in shown)

        total, shown, selected = counts(self.candidate_tree)
        text = f'{shown:,} of {total:,} tracks' if shown != total else f'{total:,} tracks'
        self.list_count_label.setText(f'{text}, {selected:,} selected  ' if selected else f'{text}  ')
        total, _shown, selected = counts(self.playlist_tree)
        text = f'{total:,} track' + ('' if total == 1 else 's')
        self.playlist_count_label.setText(f'{text}, {selected:,} selected' if selected else text)

    def map_visible(self):
        return hasattr(self, 'similarity_map') and self.library_tabs.currentWidget() is self.similarity_map

    def _refresh_map(self):
        """Show the rows the list shows; (re)load map data when it is opened and stale."""
        if not self.map_visible():
            return
        if self._map_stale:
            self._map_stale = False
            self.similarity_map.load()
        columns = [self.candidate_tree.headerItem().text(i) for i in range(self.candidate_tree.columnCount())]
        fields = {}
        for index in range(self.candidate_tree.topLevelItemCount()):
            item = self.candidate_tree.topLevelItem(index)
            if not item.isHidden():
                fields[canonical_path(item.text(HEADER_INDEX['Path']))] = \
                    {name: item.text(column) for column, name in enumerate(columns)}
        self.similarity_map.set_tracks(fields)

    def _fields_for_key(self, key):
        """Table texts of a track in the library list (also hidden rows) or the playlist."""
        columns = [self.candidate_tree.headerItem().text(i) for i in range(self.candidate_tree.columnCount())]
        for tree in (self.candidate_tree, self.playlist_tree):
            for index in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(index)
                if canonical_path(item.text(HEADER_INDEX['Path'])) == key:
                    return {name: item.text(column) for column, name in enumerate(columns)}
        return None

    def _embedding_added(self, _key):
        self._map_stale = True  # placed on the map the next time it is opened

    def _list_item(self, key):
        for index in range(self.candidate_tree.topLevelItemCount()):
            item = self.candidate_tree.topLevelItem(index)
            if canonical_path(item.text(HEADER_INDEX['Path'])) == key:
                return item
        return None

    def _select_in_list(self, key):
        item = self._list_item(key)
        if item is not None:
            self.candidate_tree.setCurrentItem(item)

    def _map_add_to_playlist(self, key):
        self._select_in_list(key)
        self.add_selected_to_playlist()

    def _map_context_menu(self, key, position):
        self._select_in_list(key)
        self.track_context_menu(self.candidate_tree).exec_(position)

    def choose_hover_fields(self):
        dialog = HoverFieldsDialog(self.settings.get('Map hover fields', DEFAULT_HOVER_FIELDS), FIELD_LABELS, self)
        if dialog.exec_() == QDialog.Accepted:
            self.settings['Map hover fields'] = dialog.selected()
            self._refresh_map()

    def set_theme(self, name):
        self.settings['Theme'] = apply_theme(name)
        self.populate_tree()  # re-tint rows for the new background

    def set_hide_playlist_tracks(self, hide):
        self.settings['Hide playlist tracks'] = hide
        self.filter_items()

    def _show_advanced_search_state(self):
        """'Advanced Search (2 active)', highlighted, with the filters in the tooltip."""
        filters = self.advanced_filters if self.current_advanced_search.get('enabled') else []
        if filters:
            self.btn_advanced_search.setText(f'Advanced Search ({len(filters)} active)')
            self.btn_advanced_search.setStyleSheet(status_style('warning', bold=True))
            self.btn_advanced_search.setToolTip('Active filters:\n' + '\n'.join(
                f"{f['column']} {f['condition']} {f['value']}" for f in filters))
        else:
            self.btn_advanced_search.setText('Advanced Search')
            self.btn_advanced_search.setStyleSheet('')
            self.btn_advanced_search.setToolTip('Filter by column conditions, e.g. BPM between 120 and 130.')

    def _init_analysis_menu(self):
        menu = self.menuBar().addMenu('Analysis')
        self.embedding_toggle = menu.addAction('Analyse embeddings in background')
        self.embedding_toggle.setCheckable(True)
        self.embedding_toggle.setChecked(self.settings.get('Embedding analysis', True))
        self.embedding_toggle.toggled.connect(self.set_embedding_analysis_enabled)
        menu.addAction('Choose embedding model (cnn14.onnx)...').triggered.connect(self.choose_embedding_model)

    def embedding_model_path(self):
        """Chosen model, else <data folder>/models/cnn14.onnx, else the default; None if none exists."""
        for candidate in (self.settings.get('Embedding model'),
                          Path(SETTINGS_FILE).with_name('models') / MODEL_FILE_NAME,
                          DEFAULT_EMBEDDING_MODEL):
            if candidate and Path(candidate).is_file():
                return Path(candidate)
        return None

    def start_embedding_analysis(self):
        if not self.settings.get('Embedding analysis', True):
            self.embedding_label.setText('Embeddings: paused')
            return
        model = self.embedding_model_path()
        if model is None:
            self.embedding_label.setText('Embeddings: no model (Analysis menu)')
            return
        if self.embedding_analyzer is not None and self.embedding_analyzer.model_path != model:
            self.embedding_analyzer.stop()
            self.embedding_analyzer = None
        if self.embedding_analyzer is None:
            self.embedding_analyzer = EmbeddingAnalyzer(self.embedding_store, model, parent=self)
            self.embedding_analyzer.progress.connect(self._show_embedding_progress)
            self.embedding_analyzer.track_analyzed.connect(self._embedding_added)
            self.embedding_analyzer.failed.connect(self.embedding_label.setText)
        self._queue_embeddings()
        self.embedding_analyzer.start()

    def _queue_embeddings(self):
        if self.embedding_analyzer is not None and self.table is not None and 'File_Path' in self.table:
            paths = [str(path) for path in self.table['File_Path'] if isinstance(path, str) and path]
            self.embedding_analyzer.submit((canonical_path(path), path) for path in paths)

    def _show_embedding_progress(self, done, total, missing, current):
        device = self.embedding_analyzer.device if self.embedding_analyzer is not None else ''
        text = f'Embeddings{f" ({device})" if device else ""}: {done}/{total}'
        if missing:
            text += f' ({missing} files missing)'
        text += f' - {current}' if current else (' - up to date' if done == total else '')
        self.embedding_label.setText(text)

    def set_embedding_analysis_enabled(self, enabled):
        self.settings['Embedding analysis'] = enabled
        if enabled:
            self.start_embedding_analysis()
        else:
            if self.embedding_analyzer is not None:
                self.embedding_analyzer.stop(timeout=0)
            self.embedding_label.setText('Embeddings: paused')

    def choose_embedding_model(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose the CNN14 embedding model',
                                              str(self.embedding_model_path() or ''), 'ONNX models (*.onnx)')
        if path:
            self.settings['Embedding model'] = path
            self.start_embedding_analysis()

    def refresh_data(self):
        """Rebuild the library list from the default CSV plus all imported tracks"""
        self.table = self._load_library(self.data_manager.load_default_data())
        self._save_library()
        self._queue_embeddings()
        self.populate_tree()  # keeps the current sort

    def load_csv(self):
        """Load a custom CSV file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV file", "", "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            result = self.data_manager.load_csv(file_path)
            if result is not None:
                self.table = self._load_library(result)
                self._save_library()
                self._queue_embeddings()
                self.populate_tree()  # keeps the current sort
    
    def get_full_path(self, row):
        """Generate full path to the track file"""
        return row["File_Path"]

    def update_search_columns_from_menu(self):
        self.search_columns = [
            col for col, act in self.search_column_actions.items() if act.isChecked()
        ]

    def open_advanced_search(self):
        """Open advanced search dialog"""
        self.advanced_search_dialog = AdvancedSearchDialog(FIELD_LABELS, self,
                                                           save_smartlist=self.save_smartlist_from_search)

        # Restore previous settings
        self.advanced_search_dialog.checkbox_enable.setChecked(
            self.current_advanced_search['enabled']
        )
        self.advanced_search_dialog.set_filters(self.current_advanced_search['filters'])
        
        if self.advanced_search_dialog.exec_() == QDialog.Accepted:
            # Save current state
            self.current_advanced_search['enabled'] = self.advanced_search_dialog.checkbox_enable.isChecked()
            self.current_advanced_search['filters'] = self.get_filters_from_dialog()
            
            # Apply filters
            if self.current_advanced_search['enabled']:
                self.advanced_filters = active_filters(self.current_advanced_search['filters'])
            else:
                self.advanced_filters = []
            self.filter_items()


    def get_filters_from_dialog(self):
        """Extract filters from dialog; rows set to None are kept so they come back next time"""
        return self.advanced_search_dialog.saved_filters()
    
    def populate_tree(self):
        sort_column = self.candidate_tree.sort_column
        sort_order = Qt.AscendingOrder if self.candidate_tree.sort_order else Qt.DescendingOrder
        self.candidate_tree.setSortingEnabled(False)
        self.candidate_tree.clear()
        self.all_items = []
        if self.table is not None:
            for _, row in self.table.iterrows():
                item = self._track_item(row)
                self.candidate_tree.addTopLevelItem(item)
                self.all_items.append(item)
        self.candidate_tree.setSortingEnabled(True)
        self.candidate_tree.sortItems(sort_column, sort_order)
        self.advanced_filters = active_filters(self.current_advanced_search.get('filters', []))
        self._refresh_playlist()
        self.list_browser.set_collection(self.table)
        self._apply_source_positions()
        self.filter_items()
        self.status_bar.showMessage(f'{len(self.all_items)} tracks at {self.bpm_slider.value()} BPM')


    def reset_settings(self):
        """Reset all settings to default"""
        import os
        try:
            if os.path.exists(SETTINGS_FILE):
                os.remove(SETTINGS_FILE)
            QMessageBox.information(self, "Settings Reset", "Settings have been reset. The application will now close.")
            self.close()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not reset settings: {str(e)}")

    def open_music_paths_dialog(self):
        """Open dialog to manage music paths"""
        dialog = MusicPathsDialog(self.music_paths, self)
        
        if dialog.exec_() == QDialog.Accepted:
            self.music_paths = dialog.get_paths()
            message = f"Music paths updated: {len(self.music_paths)} folder(s)"
            self.status_label.setStyleSheet(status_style('ok'))
            self.status_label.setText(message)

    def open_coloring_dialog(self):
        """Open dialog for coloring settings"""
        dialog = ColoringDialog(self.coloring_mode, self)
        
        if dialog.exec_() == QDialog.Accepted:
            self.coloring_mode = dialog.get_selected_mode()
            self.populate_tree()
            message = f"Coloring mode set to: {self.coloring_mode}"
            self.status_label.setStyleSheet(status_style('ok'))
            self.status_label.setText(message)

    # def open_coloring_dialog(self):
    #     """Open dialog for coloring settings"""
    #     # Placeholder - we'll implement this next
    #     QMessageBox.information(self, "Coloring Settings", "Coloring settings dialog - Coming soon!")

    def closeEvent(self, event):
        """Save settings before closing the app"""
        self.collection_watcher.stop()
        if self.embedding_analyzer is not None:
            self.embedding_analyzer.stop(timeout=2)
        if hasattr(self, 'similarity_map'):
            self.similarity_map.stop()
        self._save_playlist()
        HEADER_LABELS = [self.candidate_tree.headerItem().text(i) for i in range(self.candidate_tree.columnCount())]

        # Save visible columns
        visible_columns_left = [
            HEADER_LABELS[i]
            for i in range(self.playlist_tree.columnCount())
            if not self.playlist_tree.isColumnHidden(i)
        ]
        self.settings["Visible column left"] = visible_columns_left

        visible_columns_right = [
            HEADER_LABELS[i]
            for i in range(self.candidate_tree.columnCount())
            if not self.candidate_tree.isColumnHidden(i)
        ]
        self.settings["Visible column right"] = visible_columns_right

        # Save column widths
        column_sizes_left = {
            HEADER_LABELS[i]: self.playlist_tree.columnWidth(i)
            for i in range(self.playlist_tree.columnCount())
        }
        self.settings["Column sizes left"] = column_sizes_left

        column_sizes_right = {
            HEADER_LABELS[i]: self.candidate_tree.columnWidth(i)
            for i in range(self.candidate_tree.columnCount())
        }
        self.settings["Column sizes right"] = column_sizes_right

        # Save BPM slider value
        self.settings["Master Tempo"] = self.bpm_slider.value()

        self.settings["Search columns"] = self.search_columns

        # Save advanced search settings
        self.settings["Advanced search"] = self.current_advanced_search

        # Save music paths and coloring settings
        self.settings["Music paths"] = self.music_paths
        self.settings["Coloring mode"] = self.coloring_mode

        # Write back to JSON
        with open(SETTINGS_FILE, "w") as f:
            json.dump(self.settings, f, indent=4)

        # Accept the close event so the app exits
        event.accept()
    def _init_import_menu(self):
        menu = self.menuBar().addMenu('Import')
        add_files = menu.addAction('Add audio files...')
        add_files.triggered.connect(self.choose_audio_files)
        add_folder = menu.addAction('Add folder (with subfolders)...')
        add_folder.triggered.connect(self.choose_audio_folder)
        collection = menu.addAction('Link Traktor collection...')
        collection.triggered.connect(self.choose_traktor_collection)

    def choose_audio_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add audio files', '',
                                               'Audio files (*.mp3 *.MP3 *.flac *.wav);;All files (*)')
        if paths:
            self.import_audio_files(paths)

    def choose_audio_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Add all audio files of a folder and its subfolders')
        if folder:
            paths = find_audio_files([folder])
            if paths:
                self.import_audio_files(paths)
            else:
                self.status_label.setStyleSheet(status_style('warning'))
                self.status_label.setText(f'No MP3, WAV or FLAC files in {folder}')

    def choose_traktor_collection(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Link Traktor collection',
                                              self.settings.get('Traktor collection', ''),
                                              'Traktor collections (*.nml)')
        if not path:
            return
        importer = TrackImporter(path)
        importer.collection._load()
        if importer.collection.error:
            QMessageBox.warning(self, 'Cannot read collection', importer.collection.error)
            return
        self.importer = importer
        self.settings['Traktor collection'] = path
        self.collection_watcher.set_path(path)  # its changed values come in with the next sync
        self.table = enrich_ratings(self.table, importer.collection)
        self._save_library()
        self.populate_tree()
        self.status_label.setText(f'Linked {len(importer.collection.by_path)} Traktor tracks')
        self.status_bar.showMessage(path)

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
        if paths:
            self.import_audio_files(paths)
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def import_audio_files(self, paths, to_playlist=False):
        records, failures = {}, []
        previous_rows = self._rows_by_path()
        # Reading tags takes a few ms per file: show progress (with Cancel) for big imports,
        # e.g. a dropped folder with thousands of tracks.
        progress = None
        if len(paths) > PROGRESS_THRESHOLD:
            progress = QProgressDialog('Reading audio files...', 'Cancel', 0, len(paths), self)
            progress.setWindowTitle('Import')
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(400)
        cancelled = False
        for index, path in enumerate(paths):
            if progress is not None:
                progress.setValue(index)
                if progress.wasCanceled():
                    cancelled = True
                    break
            key = canonical_path(path)
            if key in records:
                continue
            try:
                record = self.importer.read(path, existing=previous_rows.get(key))
                records[canonical_path(record['File_Path'])] = record
            except (OSError, ValueError) as error:
                failures.append(str(error))
        if progress is not None:
            progress.close()
        if not records:
            self.status_label.setText(failures[0] if failures else 'No audio files to import')
            return []
        self.saved_imports.update(records)
        self.table = self._with_user_fields(merge_tracks(self.table, records.values()))
        self.data_manager.table = self.table
        persistence_error = self._save_library()
        self._queue_embeddings()
        # A dropped file should be immediately visible even if a previous filter excluded it.
        self.search_bar.clear()
        self.current_advanced_search['enabled'] = False
        self.advanced_filters = []
        if not to_playlist:
            self.list_source = None
            self._resolve_source()
        self.populate_tree()
        if to_playlist:
            for record in records.values():
                self._add_to_playlist(record)
            persistence_error = self._save_playlist() or persistence_error
            self.filter_items()
        else:
            first_path = next(iter(records))
            for index in range(self.candidate_tree.topLevelItemCount()):
                item = self.candidate_tree.topLevelItem(index)
                if canonical_path(item.text(HEADER_INDEX['Path'])) == first_path:
                    self.candidate_tree.setCurrentItem(item)
                    self.candidate_tree.scrollToItem(item)
                    break
        missing = sum(not row['Musical_Key_Base'] or row['BPM'] is None for row in records.values())
        message = f'Imported {len(records)} track(s)'
        if cancelled:
            message += f' (cancelled; {len(paths) - len(records) - len(failures)} not imported)'
        if missing:
            message += f'; {missing} need key/BPM analysis in Traktor'
        if failures:
            message += f'; {len(failures)} file(s) skipped'
        self.status_label.setStyleSheet(status_style('warning') if missing or failures else status_style('ok'))
        self.status_label.setText(message)
        self.status_bar.showMessage(persistence_error or self.importer.collection.error or message)
        return list(records.values())

    @staticmethod
    def _text(value):
        if value is None or pd.isna(value):
            return ''
        return str(value)

    @staticmethod
    def _rating_text(value):
        if value is None or pd.isna(value):
            return ''
        try:
            return str(int(float(value)))
        except (ValueError, TypeError):
            return str(value)

    def _rows_by_path(self):
        """Rows by canonical path; for a duplicated path the first row wins."""
        rows = {}
        for _, row in self.table.iterrows():
            key = canonical_path(row.get('File_Path'))
            if key:
                rows.setdefault(key, row)
        return rows

    def _track_item(self, row, item=None):
        item = item if item is not None else TrackItem()
        base, scale = self._text(row.get('Musical_Key_Base')), self._text(row.get('BaseMinorOrMajor'))
        key = parse_key(f'{base} {scale}') or parse_key(base)
        bpm = parse_bpm(row.get('BPM'))
        original_key, new_key, camelot, open_key = 'Unknown', 'Unknown', 'Unknown', 'Unknown'
        if key:
            base, scale = key
            original_key = f'{base} {scale}'
            if bpm is not None:
                shift = self.key_calculator.calculate_semitone_shift(bpm, self.bpm_slider.value())
                shifted = self.key_calculator.key_shifter(base, shift)
                new_key = f'{shifted} {scale}'
                camelot = self.key_calculator.get_harmonic_key(shifted, scale)
                open_key = self.key_calculator.camelot_to_open_key(camelot)
        values = {'Artist': self._text(row.get('Artist')), 'Title': self._text(row.get('Title')),
                  'Original BPM': f'{bpm:.2f}'.rstrip('0').rstrip('.') if bpm is not None else 'Unknown',
                  'Original Key': original_key, 'New Key': new_key,
                  'Camelot Key New': camelot, 'Open Key New': open_key,
                  'Path': self._text(row.get('File_Path')), 'Comment': self._text(row.get('Comment')),
                  'Genre': self._text(row.get('Genre')), 'Color': self._rating_text(row.get('Color')) or '0',
                  'Album': self._text(row.get('Album')), 'Rating': self._rating_text(row.get('Rating')),
                  SS_RATING_COLUMN: self._rating_text(row.get('SS_Rating')),
                  SS_COLOR_COLUMN: self._rating_text(row.get('SS_Color'))}
        key_source = self._text(row.get('Key_Source')) or ('Loaded CSV' if key else 'Not available')
        bpm_source = self._text(row.get('BPM_Source')) or ('Loaded CSV' if bpm else 'Not available')
        color_source = self._text(row.get('Color_Source')) or ('Saved import' if self._text(row.get('Imported')) else 'Loaded CSV')
        color_detail = color_source if values['Color'] != '0' else 'No category color assigned'
        tooltip = f'Key: {key_source}\nBPM: {bpm_source}\nColor: {color_detail}'
        if row.get('Metadata_Error') and self._text(row.get('Metadata_Error')):
            tooltip += '\n' + self._text(row.get('Metadata_Error'))
        for column, value in values.items():
            item.setText(HEADER_INDEX[column], value)
            item.setToolTip(HEADER_INDEX[column], tooltip)
        self.apply_row_shading_from_color(item)
        self._apply_text_colours(item)
        return item

    @staticmethod
    def _apply_text_colours(item):
        """Library rows of playlist tracks are dimmed and italic; otherwise a missing key or
        BPM is shown in orange (the one that is missing; key first)."""
        dimmed = bool(item.data(0, IN_PLAYLIST_ROLE))
        font = item.font(0)
        font.setItalic(dimmed)
        for column in range(len(HEADER_LABELS)):
            item.setForeground(column, QBrush(dim_text_colour()) if dimmed else QBrush())
            item.setFont(column, font)
        if dimmed:
            return
        missing_key = item.text(HEADER_INDEX['Original Key']) == 'Unknown'
        if missing_key or item.text(HEADER_INDEX['Original BPM']) == 'Unknown':
            item.setForeground(HEADER_INDEX['Original Key'] if missing_key else HEADER_INDEX['Original BPM'],
                               QBrush(QColor('darkorange')))

    def _add_to_playlist(self, row, index=None):
        """Append (or insert at row `index`) a track; one already on the playlist is updated in place."""
        path = canonical_path(row.get('File_Path'))
        for row_index in range(self.playlist_tree.topLevelItemCount()):
            item = self.playlist_tree.topLevelItem(row_index)
            if canonical_path(item.text(HEADER_INDEX['Path'])) == path:
                self._track_item(row, item)
                return
        item = self._track_item(row)
        if index is None:
            self.playlist_tree.addTopLevelItem(item)
        else:
            self.playlist_tree.insertTopLevelItem(index, item)
        self.playlist_paths.add(self._text(row.get('File_Path')))

    def _refresh_playlist(self):
        rows = self._rows_by_path()
        for index in range(self.playlist_tree.topLevelItemCount()):
            item = self.playlist_tree.topLevelItem(index)
            row = rows.get(canonical_path(item.text(HEADER_INDEX['Path'])))
            if row is not None:
                self._track_item(row, item)
