"""
Main window for the Traktor Key Calculator
"""

# ADD:
# When song is selected and it is not available then RED
import os
import json
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QPushButton, QFileDialog, QTreeWidgetItem,
                            QLineEdit, QSlider, QSplitter, QStatusBar, QHeaderView, QDialog, QMessageBox)
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QToolButton, QMenu, QAction

from PyQt5.QtGui import QColor, QBrush, QIcon, QPixmap, QPainter

from traktor_key_calculator.config import DEFAULT_BPM, WINDOW_SIZE, MIN_BPM, MAX_BPM, SETTINGS_FILE, HEADER_LABELS, COLOR_MAPPING_CATEGORY
from traktor_key_calculator.config import COLOR_COLUMN_INDEX, HEADER_INDEX, OPEN_KEY_COLOR_MAPPING
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
from traktor_key_calculator.core.track_import import TrackImporter, ImportedTrackStore, merge_tracks, enrich_ratings
from traktor_key_calculator.core.traktor_collection import canonical_path, discover_collection
from traktor_key_calculator.core.key_formats import parse_key, parse_bpm
from traktor_key_calculator.core.search_filters import matches_condition
from traktor_key_calculator.core.color_search import COLOR_NAMES, parse_color_search, replace_color_filter
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


        
        self.playlist_paths = set()
        self.imported_store = ImportedTrackStore(Path(SETTINGS_FILE).with_name('imported_tracks.json'))
        self.saved_imports = self.imported_store.load()
        collection_path = self.settings.get('Traktor collection') or discover_collection()
        self.settings['Traktor collection'] = collection_path
        self.importer = TrackImporter(collection_path)
        self.setAcceptDrops(True)

        # Initialize UI
        self.init_ui()
        self._init_import_menu()
        
        # Load data
        self.table = self._load_library(self.data_manager.load_default_data())
        
        # Populate the tree
        self.populate_tree()

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
                swatch = QPixmap(18, 18)
                swatch.fill(Qt.transparent)
                painter = QPainter(swatch)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(Qt.NoPen)
                painter.setBrush(COLOR_MAPPING_CATEGORY[number])
                painter.drawEllipse(2, 2, 14, 14)
                painter.end()
                action.setIcon(QIcon(swatch))
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
        self.refresh_button.clicked.connect(self.refresh_data)
        control_layout.addWidget(self.refresh_button)
        
        self.load_csv_button = QPushButton("Load CSV")
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


        # ---------------
        # COLOR CODES
        # ---------------

        # Apply the color dot delegate to the "Color" column (index 9)
        # color_column_index = HEADER_LABELS.index("Color")
        # self.candidate_tree.setItemDelegateForColumn(color_column_index, ColorDotDelegate(self))
        # self.playlist_tree.setItemDelegateForColumn(color_column_index, ColorDotDelegate(self))


        self.color_delegate = ColorDotDelegate(self.candidate_tree)
        self.candidate_tree.setItemDelegateForColumn(COLOR_COLUMN_INDEX, self.color_delegate)

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
        self.filter_items()

    
    def clear_playlist(self):
        self.playlist_tree.clear()
        self.playlist_paths.clear()
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
        search_text = color_query.text.casefold()
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
            matches = path not in playlist_paths and color_query.matches(item.text(COLOR_COLUMN_INDEX))
            if matches and search_text:
                matches = any(search_text in item.text(column).casefold() for column in search_indices)
            if matches and self.current_advanced_search.get('enabled') and self.advanced_filters:
                matches = self.apply_advanced_filters_tree(item)
            item.setHidden(not matches)
        visible = sum(not self.candidate_tree.topLevelItem(i).isHidden()
                      for i in range(self.candidate_tree.topLevelItemCount()))
        self.status_label.setStyleSheet('color: green; font-weight: bold;')
        self.status_label.setText(f'Displaying {visible} of {self.candidate_tree.topLevelItemCount()} tracks')
        if color_query.error:
            self.status_label.setStyleSheet('color: red; font-weight: bold;')
            self.status_label.setText(color_query.error)


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
            if column == HEADER_INDEX.get("Color"):  # Color column (special handling)
                def get_sort_key(item):
                    try:
                        # Extract color value
                        text = item.text(column)
                        if text == 'nan' or not text:
                            return (1, 999)  # Sort 'nan' values at the end
                        return (0, int(float(text.strip())))
                    except:
                        return (1, 999)  # Put errors at the end too
            elif column in (HEADER_INDEX.get("Original BPM"), HEADER_INDEX.get("Rating")):  # Numeric columns
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
        return enrich_ratings(merged, self.importer.collection)

    def refresh_data(self):
        """Reload data and refresh the tree"""
        self.table = self._load_library(self.data_manager.load_default_data())
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
        self.table = merge_tracks(self.table, records.values())
        self.data_manager.table = self.table
        persistence_error = ''
        try:
            self.imported_store.save(self.saved_imports)
        except (OSError, ValueError) as error:
            persistence_error = f'Could not save imported tracks: {error}'
        # A dropped file should be immediately visible even if a previous filter excluded it.
        self.search_bar.clear()
        self.current_advanced_search['enabled'] = False
        self.advanced_filters = []
        self.populate_tree()
        if to_playlist:
            for record in records.values():
                self._add_to_playlist(record)
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
        return {canonical_path(row.get('File_Path')): row for _, row in self.table.iterrows()
                if canonical_path(row.get('File_Path'))}

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
                  'Album': self._text(row.get('Album')), 'Rating': self._rating_text(row.get('Rating'))}
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
