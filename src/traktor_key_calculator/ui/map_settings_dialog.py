"""Choose which track details the similarity map shows when hovering over a dot."""
from PyQt5.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QLabel, QVBoxLayout


class HoverFieldsDialog(QDialog):
    def __init__(self, selected, columns, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Map hover details')
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Details shown when the mouse is over a track on the similarity map:'))
        grid = QGridLayout()
        self.boxes = {}
        for index, column in enumerate(columns):
            box = QCheckBox(column)
            box.setChecked(column in selected)
            grid.addWidget(box, index // 2, index % 2)
            self.boxes[column] = box
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self):
        """Checked columns, in table order."""
        return [column for column, box in self.boxes.items() if box.isChecked()]
