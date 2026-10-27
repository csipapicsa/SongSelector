"""
music_paths_dialog.py
Dialog for managing music folder paths
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QListWidget, QFileDialog, QMessageBox
)
from PyQt5.QtCore import Qt


class MusicPathsDialog(QDialog):
    """Dialog to add, edit, and remove music folder paths"""
    
    def __init__(self, current_paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Music Paths")
        self.setModal(True)
        self.resize(600, 400)
        
        self.current_paths = current_paths.copy()
        
        self.init_ui()
        self.load_paths()
    
    def init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout()
        
        # List widget to show paths
        self.paths_list = QListWidget()
        layout.addWidget(self.paths_list)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.btn_add = QPushButton("Add Folder...")
        self.btn_add.clicked.connect(self.add_path)
        button_layout.addWidget(self.btn_add)
        
        self.btn_remove = QPushButton("Remove Selected")
        self.btn_remove.clicked.connect(self.remove_path)
        button_layout.addWidget(self.btn_remove)
        
        button_layout.addStretch()
        
        self.btn_ok = QPushButton("OK")
        self.btn_ok.clicked.connect(self.accept)
        button_layout.addWidget(self.btn_ok)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def load_paths(self):
        """Load paths into the list"""
        self.paths_list.clear()
        for path in self.current_paths:
            self.paths_list.addItem(path)
    
    def add_path(self):
        """Add a new folder path"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Music Folder",
            "",
            QFileDialog.ShowDirsOnly
        )
        
        if folder:
            if folder not in self.current_paths:
                self.current_paths.append(folder)
                self.paths_list.addItem(folder)
            else:
                QMessageBox.information(self, "Duplicate", "This path is already in the list.")
    
    def remove_path(self):
        """Remove selected path"""
        current_item = self.paths_list.currentItem()
        if current_item:
            path = current_item.text()
            self.current_paths.remove(path)
            self.paths_list.takeItem(self.paths_list.row(current_item))
    
    def get_paths(self):
        """Return the updated list of paths"""
        return self.current_paths