"""Choose which track details the similarity map shows when hovering over a dot, and how wide its info boxes get."""
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)


class HoverFieldsDialog(QDialog):
    def __init__(self, selected, columns, width=360, minimum=200, maximum=1200, parent=None):
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
        row = QHBoxLayout()
        row.addWidget(QLabel('Info boxes at most'))
        self.width_box = QSpinBox()
        self.width_box.setRange(minimum, maximum)
        self.width_box.setSingleStep(20)
        self.width_box.setSuffix(' px wide')
        self.width_box.setValue(max(minimum, min(maximum, width)))
        self.width_box.setToolTip('Longer text (e.g. a long file name) wraps onto more lines, so a card never covers '
                                  'the map. Also the label of the selected track.')
        row.addWidget(self.width_box)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self):
        """Checked columns, in table order."""
        return [column for column, box in self.boxes.items() if box.isChecked()]

    def info_width(self):
        return self.width_box.value()
