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
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QToolButton, QMenu, QAction

from PyQt5.QtGui import QColor, QBrush, QIcon, QPixmap, QPainter

from traktor_key_calculator.config import DEFAULT_BPM, WINDOW_SIZE, MIN_BPM, MAX_BPM, SETTINGS_FILE, HEADER_LABELS, COLOR_MAPPING_CATEGORY
from traktor_key_calculator.config import COLOR_COLUMN_INDEX, HEADER_INDEX, OPEN_KEY_COLOR_MAPPING
from traktor_key_calculator.config import SS_RATING_COLUMN, SS_COLOR_COLUMN
from traktor_key_calculator.ui.delegates import ColorDotDelegate
from traktor_key_calculator.ui.tree_widgets import PoolTreeWidget, PlaylistTreeWidget
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
from traktor_key_calculator.core.tag_writer import write_tags
from traktor_key_calculator.core.embeddings import EmbeddingStore, MODEL_FILE_NAME, file_fingerprint
from traktor_key_calculator.ui.embedding_worker import EmbeddingAnalyzer
from traktor_key_calculator.ui.track_info_dialog import TrackInfoDialog
from mutagen import MutagenError
from traktor_key_calculator.core.traktor_collection import canonical_path, discover_collection
from traktor_key_calculator.core.key_formats import parse_key, parse_bpm
from traktor_key_calculator.core.search_filters import matches_condition
from traktor_key_calculator.core.color_search import (COLOR_NAMES, SS_COLOR_TOKEN, parse_color_search,
                                                      replace_color_filter)
from traktor_key_calculator.ui.tree_widgets import audio_paths


class TraktorKeyCalculator(QMainWindow):
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


        
        self.playlist_paths = set()
        collection_path = self.settings.get('Traktor collection') or discover_collection()
        self.settings['Traktor collection'] = collection_path
        self.importer = TrackImporter(collection_path)
        self.setAcceptDrops(True)

        # Initialize UI
        self.init_ui()
        self._init_import_menu()

        # Load data: restore both panels as they were last saved
        self.library_store = LibraryStore(Path(SETTINGS_FILE).with_name('library.sqlite'))
        self.saved_imports = {}
        self.table = pd.DataFrame()
        self._restore_lists()
        self.populate_tree()

        # Embeddings of every library track, analysed in the background
        self.embedding_store = EmbeddingStore(Path(SETTINGS_FILE).with_name('embeddings.sqlite'))
        self.embedding_analyzer = None
        self._init_analysis_menu()
        self.start_embedding_analysis()

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
            shaded.setAlpha(40)
            brush = QBrush(shaded)
        for column in range(item.columnCount()):
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
        
        # Left pane for playlist (initially empty)
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        
        # Playlist label
        playlist_label = QLabel("Playlist (Drag Tracks Here)")
        playlist_label.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(playlist_label)
        
        # Clear playlist button
        clear_playlist_btn = QPushButton("Clear Playlist")
        clear_playlist_btn.clicked.connect(self.clear_playlist)
        left_layout.addWidget(clear_playlist_btn)
        
        # Playlist tree
        self.playlist_tree = PlaylistTreeWidget(self)
        self.playlist_tree.setColumnCount(len(HEADER_LABELS))
        self.playlist_tree.setHeaderLabels(HEADER_LABELS)

        visible_columns = self.settings.get("Visible column left", HEADER_LABELS)
        for col, name in enumerate(HEADER_LABELS):
            is_visible = name in visible_columns
            self.playlist_tree.setColumnHidden(col, not is_visible)

        column_sizes = self.settings.get("Column Sizes left", {})
        for col, label in enumerate(HEADER_LABELS):
            width = column_sizes.get(label)
            if width is not None and width > 0:
                self.playlist_tree.setColumnWidth(col, width)

        # Set column widths for playlist tree
        self.playlist_tree.header().setStretchLastSection(False)
        self.playlist_tree.header().setSectionResizeMode(HEADER_INDEX["Artist"], QHeaderView.Stretch)
        self.playlist_tree.header().setSectionResizeMode(HEADER_INDEX["Title"], QHeaderView.Stretch)
        self.playlist_tree.header().setSectionResizeMode(HEADER_INDEX["Original BPM"], QHeaderView.Stretch)
        self.playlist_tree.header().setSectionResizeMode(HEADER_INDEX["Original Key"], QHeaderView.Stretch)
        self.playlist_tree.header().setSectionResizeMode(HEADER_INDEX["New Key"], QHeaderView.Stretch)
        self.playlist_tree.header().setSectionResizeMode(HEADER_INDEX["Camelot Key New"], QHeaderView.Stretch)
        self.playlist_tree.header().setSectionResizeMode(HEADER_INDEX["Open Key New"], QHeaderView.Stretch)
        self.playlist_tree.header().setSectionResizeMode(HEADER_INDEX["Path"], QHeaderView.Stretch)
        self.playlist_tree.header().setSectionResizeMode(HEADER_INDEX["Comment"], QHeaderView.Stretch)
        self.playlist_tree.header().setSectionResizeMode(HEADER_INDEX["Genre"], QHeaderView.Stretch)
        self.playlist_tree.header().setSectionResizeMode(HEADER_INDEX["Color"], QHeaderView.Stretch)
        left_layout.addWidget(self.playlist_tree)


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

        for column in HEADER_LABELS:
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
        
        # Add tree to right layout
        right_layout.addWidget(self.candidate_tree)
        
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
        self.status_label.setStyleSheet("color: black; font-weight: normal;")
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
        columns = {self.candidate_tree.headerItem().text(index): index
                   for index in range(self.candidate_tree.columnCount())}
        for condition in self.advanced_filters:
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
        search_indices = [HEADER_INDEX[name] for name in self.search_columns if name in HEADER_INDEX]
        playlist_paths = {canonical_path(path) for path in self.playlist_paths}
        for index in range(self.candidate_tree.topLevelItemCount()):
            item = self.candidate_tree.topLevelItem(index)
            path = canonical_path(item.text(HEADER_INDEX['Path']))
            matches = (path not in playlist_paths and color_query.matches(item.text(COLOR_COLUMN_INDEX))
                       and ss_color_query.matches(item.text(HEADER_INDEX[SS_COLOR_COLUMN])))
            if matches and search_text:
                matches = any(search_text in item.text(column).casefold() for column in search_indices)
            if matches and self.current_advanced_search.get('enabled') and self.advanced_filters:
                matches = self.apply_advanced_filters_tree(item)
            item.setHidden(not matches)
        visible = sum(not self.candidate_tree.topLevelItem(i).isHidden()
                      for i in range(self.candidate_tree.topLevelItemCount()))
        self.status_label.setStyleSheet('color: green; font-weight: bold;')
        self.status_label.setText(f'Displaying {visible} of {self.candidate_tree.topLevelItemCount()} tracks')
        if color_query.error or ss_color_query.error:
            self.status_label.setStyleSheet('color: red; font-weight: bold;')
            self.status_label.setText(color_query.error or ss_color_query.error)


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
        """Handle header click to sort the tree"""
        self.sort_by_column(column)
    
    def sort_by_column(self, column):
        """Sort the tree by the given column"""
        try:
            # Toggle sort order if same column
            if self.sort_column == column:
                self.sort_ascending = not self.sort_ascending
            else:
                self.sort_column = column
                self.sort_ascending = True
            
            # Update status
            column_name = self.candidate_tree.headerItem().text(column)
            direction = "ascending" if self.sort_ascending else "descending"
            
            # self.status_bar.showMessage(f"Sorting by {column_name} ({direction})...")
            message = f"Sorting by {column_name} ({direction})..."
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.status_label.setText(message)
            
            
            # Get all items
            items = []
            for i in range(self.candidate_tree.topLevelItemCount()):
                items.append(self.candidate_tree.takeTopLevelItem(0))
            
            # Define sort key function based on column
            if column in (HEADER_INDEX.get("Color"), HEADER_INDEX.get(SS_COLOR_COLUMN)):  # color numbers
                def get_sort_key(item):
                    try:
                        # Extract color value
                        text = item.text(column)
                        if text == 'nan' or not text:
                            return (1, 999)  # Sort 'nan' values at the end
                        return (0, int(float(text.strip())))
                    except:
                        return (1, 999)  # Put errors at the end too
            elif column in (HEADER_INDEX.get("Original BPM"), HEADER_INDEX.get("Rating"),
                            HEADER_INDEX.get(SS_RATING_COLUMN)):  # Numeric columns
                def get_sort_key(item):
                    try:
                        # Extract numeric value
                        text = item.text(column)
                        if text == 'nan' or not text:
                            return 999  # Sort 'nan' values at the end
                        return float(text.strip())
                    except:
                        return 999
            elif column == HEADER_INDEX.get("Camelot Key New"):  # Harmonic Key column
                def get_sort_key(item):
                    try:
                        # Extract camelot key format (e.g., "1A", "12B")
                        key_text = item.text(column)
                        # Handle "Unknown" or empty values
                        if key_text == "Unknown" or not key_text or key_text == 'nan':
                            return (999, "Z")  # Sort at the end
                        
                        # Extract the number and letter parts
                        number_part = ''.join(c for c in key_text if c.isdigit())
                        letter_part = ''.join(c for c in key_text if c.isalpha())
                        
                        # Ensure number part is valid
                        if number_part:
                            # Return a tuple for sorting (number, letter)
                            return (int(number_part), letter_part)
                        return (999, "Z")
                    except:
                        return (999, "Z")
            else:
                # Text columns
                def get_sort_key(item):
                    text = item.text(column)
                    return text if text != 'nan' else "zzzzz"  # Sort 'nan' values at the end
            
            # Sort the items
            items.sort(key=get_sort_key, reverse=not self.sort_ascending)
            
            # Add them back to the tree
            for item in items:
                self.candidate_tree.addTopLevelItem(item)
            
            # Update status
            visible_count = sum(1 for i in range(self.candidate_tree.topLevelItemCount()) if not self.candidate_tree.topLevelItem(i).isHidden())
            total_count = self.candidate_tree.topLevelItemCount()
            
            # self.status_bar.showMessage(f"Sorted by {column_name} ({direction}). Displaying {visible_count} of {total_count} tracks")
            message = f"Sorted by {column_name} ({direction}). Displaying {visible_count} of {total_count} tracks"
            self.status_label.setStyleSheet("color: black; font-weight: bold;")
            self.status_label.setText(message)
            
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Sort Error", f"Error sorting: {str(e)}")
            self.status_bar.showMessage(f"Error sorting: {str(e)}")
    
    def on_item_double_clicked(self, item, column):
        """Handle double-click on tree item"""
        file_path = item.text(HEADER_INDEX.get("Path"))
        if file_path and os.path.exists(file_path):
            os.startfile(file_path)
            self.status_bar.showMessage(f"Opened file: {os.path.basename(file_path)}")
            message = f"Opened file: {os.path.basename(file_path)}"
            self.status_label.setStyleSheet("color: black;")
            self.status_label.setText(message)
        else:
            self.status_bar.showMessage(f"🔴 File not found: {file_path}")
            message = f"🔴 File not found: {file_path}"
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.status_label.setText(message)
    
    def _load_library(self, table):
        merged = merge_tracks(table, self.saved_imports.values())
        return self._with_user_fields(enrich_ratings(merged, self.importer.collection))

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

    def _save_playlist(self):
        keys = [canonical_path(self.playlist_tree.topLevelItem(i).text(HEADER_INDEX['Path']))
                for i in range(self.playlist_tree.topLevelItemCount())]
        records = {}
        if self.table is not None and 'File_Path' in self.table:
            subset = self.table[self.table['File_Path'].map(canonical_path).isin(keys)]
            for row in subset.to_dict('records'):
                records.setdefault(canonical_path(row['File_Path']), row)
        return self._save_list(PLAYLIST_LIST, [records[key] for key in keys if key in records])

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
        self.status_label.setStyleSheet('color: red; font-weight: bold;' if error else 'color: green; font-weight: bold;')
        self.status_label.setText(error or message)
        return removed

    def track_context_menu(self, tree):
        """Right-click menu for the selected row of the library or playlist panel."""
        menu = QMenu(self)
        item = tree.currentItem()
        path = item.text(HEADER_INDEX['Path']) if item is not None else ''
        edit = menu.addAction('Edit Artist / Title / Genre...')
        edit.setEnabled(bool(path))
        edit.triggered.connect(lambda: self.open_track_info_dialog(path))

        rating_menu = menu.addMenu('Rating - Song Selector')
        for stars in range(5, 0, -1):
            action = rating_menu.addAction('★' * stars + '☆' * (5 - stars) + f'  ({stars})')
            action.triggered.connect(lambda _checked, value=stars: self.set_song_selector_fields([path], SS_Rating=value))
        rating_menu.addSeparator()
        rating_menu.addAction('Clear rating').triggered.connect(
            lambda: self.set_song_selector_fields([path], SS_Rating=None))

        color_menu = menu.addMenu('Color - Song Selector')
        for number, name in COLOR_NAMES.items():
            if number:
                action = color_menu.addAction(self._color_swatch(number), name.title())
                action.triggered.connect(lambda _checked, value=number: self.set_song_selector_fields([path], SS_Color=value))
        color_menu.addSeparator()
        color_menu.addAction('Clear color').triggered.connect(
            lambda: self.set_song_selector_fields([path], SS_Color=None))
        rating_menu.setEnabled(bool(path))
        color_menu.setEnabled(bool(path))

        if tree is self.candidate_tree:
            menu.addSeparator()
            delete_duplicates = menu.addAction('Delete duplicates from the list')
            delete_duplicates.setToolTip('Remove rows with the same file path. Files on disk are not deleted.')
            delete_duplicates.triggered.connect(self.delete_duplicate_tracks)
        return menu

    def library_context_menu(self):
        return self.track_context_menu(self.candidate_tree)

    def show_track_context_menu(self, tree, pos):
        item = tree.itemAt(pos)
        if item is not None:
            tree.setCurrentItem(item)
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
            self.status_label.setStyleSheet('color: red; font-weight: bold;')
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
        dialog = TrackInfoDialog(path, {name: self._text(row.get(name)) for name in ('Artist', 'Title', 'Genre')}, self)
        if dialog.exec_() == QDialog.Accepted:
            self.edit_track_tags(path, **dialog.changed_values())

    def edit_track_tags(self, path, **values):
        """Write Artist/Title/Genre into the audio file, then update the library to match."""
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
        self.status_label.setStyleSheet('color: red; font-weight: bold;' if error else 'color: green; font-weight: bold;')
        self.status_label.setText(error or f'Saved {", ".join(values)} to {Path(path).name}')
        return not error

    # -- embeddings ---------------------------------------------------------

    def _init_analysis_menu(self):
        menu = self.menuBar().addMenu('Analysis')
        self.embedding_toggle = menu.addAction('Analyse embeddings in background')
        self.embedding_toggle.setCheckable(True)
        self.embedding_toggle.setChecked(self.settings.get('Embedding analysis', True))
        self.embedding_toggle.toggled.connect(self.set_embedding_analysis_enabled)
        menu.addAction('Choose embedding model (cnn14.onnx)...').triggered.connect(self.choose_embedding_model)

    def embedding_model_path(self):
        """Configured model file, else <data folder>/models/cnn14.onnx; None if neither exists."""
        for candidate in (self.settings.get('Embedding model'),
                          Path(SETTINGS_FILE).with_name('models') / MODEL_FILE_NAME):
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
        self.populate_tree()
        
        # Re-apply current sort
        if hasattr(self, 'sort_column'):
            self.sort_by_column(self.sort_column)
    
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
                self.populate_tree()
                
                # Re-apply current sort
                if hasattr(self, 'sort_column'):
                    self.sort_by_column(self.sort_column)
    
    def get_full_path(self, row):
        """Generate full path to the track file"""
        return row["File_Path"]

    def update_search_columns_from_menu(self):
        self.search_columns = [
            col for col, act in self.search_column_actions.items() if act.isChecked()
        ]

    def open_advanced_search(self):
        """Open advanced search dialog"""
        column_names = [self.candidate_tree.headerItem().text(i) 
                        for i in range(self.candidate_tree.columnCount())]
        
        self.advanced_search_dialog = AdvancedSearchDialog(column_names, self)
        
        # Restore previous settings
        self.advanced_search_dialog.checkbox_enable.setChecked(
            self.current_advanced_search['enabled']
        )
        
        for i, filter_data in enumerate(self.current_advanced_search['filters']):
            if i < len(self.advanced_search_dialog.filter_rows):
                row = self.advanced_search_dialog.filter_rows[i]
                row.column_combo.setCurrentText(filter_data['column'])
                row.condition_combo.setCurrentText(filter_data['condition'])
                row.value_edit.setText(filter_data['value'])
        
        if self.advanced_search_dialog.exec_() == QDialog.Accepted:
            # Save current state
            self.current_advanced_search['enabled'] = self.advanced_search_dialog.checkbox_enable.isChecked()
            self.current_advanced_search['filters'] = self.get_filters_from_dialog()
            
            # Apply filters
            if self.current_advanced_search['enabled']:
                self.advanced_filters = self.current_advanced_search['filters']
            else:
                self.advanced_filters = []
            self.filter_items()


    def get_filters_from_dialog(self):
        """Extract filters from dialog"""
        filters = []
        for row in self.advanced_search_dialog.filter_rows:
            filter_data = row.get_filter()
            if filter_data['value']:  # Only add if value is not empty
                filters.append(filter_data)
        return filters
    
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
        self.advanced_filters = [f for f in self.current_advanced_search.get('filters', []) if f.get('value')]
        self._refresh_playlist()
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
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.status_label.setText(message)

    def open_coloring_dialog(self):
        """Open dialog for coloring settings"""
        dialog = ColoringDialog(self.coloring_mode, self)
        
        if dialog.exec_() == QDialog.Accepted:
            self.coloring_mode = dialog.get_selected_mode()
            self.populate_tree()
            message = f"Coloring mode set to: {self.coloring_mode}"
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.status_label.setText(message)

    # def open_coloring_dialog(self):
    #     """Open dialog for coloring settings"""
    #     # Placeholder - we'll implement this next
    #     QMessageBox.information(self, "Coloring Settings", "Coloring settings dialog - Coming soon!")

    def closeEvent(self, event):
        """Save settings before closing the app"""
        if self.embedding_analyzer is not None:
            self.embedding_analyzer.stop(timeout=2)
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
        collection = menu.addAction('Link Traktor collection...')
        collection.triggered.connect(self.choose_traktor_collection)

    def choose_audio_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add audio files', '',
                                               'Audio files (*.mp3 *.MP3 *.flac *.wav);;All files (*)')
        if paths:
            self.import_audio_files(paths)

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
        self.table = enrich_ratings(self.table, importer.collection)
        self._save_library()
        self.populate_tree()
        self.status_label.setText(f'Linked {len(importer.collection.by_path)} Traktor tracks')
        self.status_bar.showMessage(path)

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
        if paths:
            self.import_audio_files(paths)
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def import_audio_files(self, paths, to_playlist=False):
        records, failures = {}, []
        previous_rows = self._rows_by_path()
        for path in paths:
            key = canonical_path(path)
            if key in records:
                continue
            try:
                record = self.importer.read(path, existing=previous_rows.get(key))
                records[canonical_path(record['File_Path'])] = record
            except (OSError, ValueError) as error:
                failures.append(str(error))
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
        if missing:
            message += f'; {missing} need key/BPM analysis in Traktor'
        if failures:
            message += f'; {len(failures)} file(s) skipped'
        self.status_label.setStyleSheet('color: darkorange;' if missing or failures else 'color: green;')
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
        item = item if item is not None else QTreeWidgetItem()
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
        for column in ('Original Key', 'Original BPM'):
            item.setForeground(HEADER_INDEX[column], QBrush())
        if not key or bpm is None:
            item.setForeground(HEADER_INDEX['Original Key'] if not key else HEADER_INDEX['Original BPM'],
                               QBrush(QColor('darkorange')))
        return item

    def _add_to_playlist(self, row):
        path = canonical_path(row.get('File_Path'))
        for index in range(self.playlist_tree.topLevelItemCount()):
            item = self.playlist_tree.topLevelItem(index)
            if canonical_path(item.text(HEADER_INDEX['Path'])) == path:
                self._track_item(row, item)
                return
        self.playlist_tree.addTopLevelItem(self._track_item(row))
        self.playlist_paths.add(self._text(row.get('File_Path')))

    def _refresh_playlist(self):
        rows = self._rows_by_path()
        for index in range(self.playlist_tree.topLevelItemCount()):
            item = self.playlist_tree.topLevelItem(index)
            row = rows.get(canonical_path(item.text(HEADER_INDEX['Path'])))
            if row is not None:
                self._track_item(row, item)
