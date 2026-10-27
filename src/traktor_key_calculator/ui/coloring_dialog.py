"""
coloring_dialog.py
Dialog for coloring settings
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QRadioButton, QButtonGroup, QLabel
)
from PyQt5.QtCore import Qt


class ColoringDialog(QDialog):
    """Dialog for selecting coloring mode"""
    
    def __init__(self, current_mode, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Coloring Settings")
        self.setModal(True)
        self.resize(500, 300)
        
        self.current_mode = current_mode
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("Select Row Coloring Mode:")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        layout.addSpacing(10)
        
        # Radio buttons
        self.button_group = QButtonGroup()
        
        # Option 1: Color by Key
        self.radio_key = QRadioButton("Color by Key")
        self.button_group.addButton(self.radio_key, 0)
        layout.addWidget(self.radio_key)
        
        desc_key = QLabel("Rows will be colored based on the musical key of the track.")
        desc_key.setStyleSheet("margin-left: 25px; color: gray;")
        layout.addWidget(desc_key)
        
        layout.addSpacing(15)
        
        # Option 2: Color by Song Color
        self.radio_song = QRadioButton("Color by Category")
        self.button_group.addButton(self.radio_song, 1)
        layout.addWidget(self.radio_song)
        
        desc_song = QLabel("Rows will be colored based on the color tag assigned to the song in Traktor.")
        desc_song.setStyleSheet("margin-left: 25px; color: gray;")
        layout.addWidget(desc_song)
        
        layout.addStretch()
        
        # Set current selection
        if self.current_mode == "key":
            self.radio_key.setChecked(True)
        else:
            self.radio_song.setChecked(True)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.btn_ok = QPushButton("OK")
        self.btn_ok.clicked.connect(self.accept)
        button_layout.addWidget(self.btn_ok)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def get_selected_mode(self):
        """Return the selected coloring mode"""
        if self.radio_key.isChecked():
            return "key"
        else:
            return "song"