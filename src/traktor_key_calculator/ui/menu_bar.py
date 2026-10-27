"""
menu_bar.py
Menu bar for the application
"""

from PyQt5.QtWidgets import QMenuBar, QAction, QMessageBox
from PyQt5.QtCore import pyqtSignal


class AppMenuBar(QMenuBar):
    """Custom menu bar with File and Settings menus"""
    
    # Signals to communicate with main window
    exit_requested = pyqtSignal()
    reset_settings_requested = pyqtSignal()
    music_paths_requested = pyqtSignal()
    coloring_settings_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_menus()
    
    def init_menus(self):
        """Initialize all menus"""
        # File Menu
        file_menu = self.addMenu("File")
        
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.exit_requested.emit)
        file_menu.addAction(exit_action)
        
        reset_action = QAction("Reset Settings", self)
        reset_action.triggered.connect(self.confirm_reset_settings)
        file_menu.addAction(reset_action)
        
        # Settings Menu
        settings_menu = self.addMenu("Settings")
        
        music_paths_action = QAction("Add Music Path...", self)
        music_paths_action.triggered.connect(self.music_paths_requested.emit)
        settings_menu.addAction(music_paths_action)
        
        coloring_action = QAction("Coloring Options...", self)
        coloring_action.triggered.connect(self.coloring_settings_requested.emit)
        settings_menu.addAction(coloring_action)
    
    def confirm_reset_settings(self):
        """Show confirmation dialog before resetting settings"""
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Are you sure you want to reset all settings?\nThe application will close after reset.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.reset_settings_requested.emit()