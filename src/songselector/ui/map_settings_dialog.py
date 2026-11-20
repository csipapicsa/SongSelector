"""Choose which track details the similarity map shows where (its cards, the selected track's label, the details
panel), and how wide its info boxes get."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)


class MapDetailsDialog(QDialog):
    """A grid of check boxes: one row per item, one column per place. Until 2026-11-20 only the List's columns could
    be chosen, once for the card and the panel; the cover, the name, the key line and the group were always shown
    (user: "there is no hard coded thing which cannot be changed").

    chosen: {place: [items shown there]}; places: {place: column heading}; sections: [(heading, {item: tooltip})],
    in the order the rows appear; not_applicable: {place: items it cannot show} (no check box there)."""

    def __init__(self, chosen, places, sections, not_applicable=None, width=360, minimum=200, maximum=1200,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle('Map track details')
        not_applicable = not_applicable or {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('What the similarity map shows about a track, and where:'))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        for column, heading in enumerate(places.values(), start=1):
            title = QLabel(f'<b>{heading}</b>')
            title.setAlignment(Qt.AlignCenter)
            grid.addWidget(title, 0, column)
        self.places = list(places)
        self.items = []
        self.boxes = {}   # (place, item) -> QCheckBox
        row = 1
        for heading, items in sections:
            if row > 1:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setFrameShadow(QFrame.Sunken)
                grid.addWidget(line, row, 0, 1, len(places) + 1)
                row += 1
            grid.addWidget(QLabel(f'<i>{heading}</i>'), row, 0, 1, len(places) + 1)
            row += 1
            for item, tip in items.items():
                name = QLabel(item)
                name.setToolTip(tip)
                grid.addWidget(name, row, 0)
                for column, place in enumerate(self.places, start=1):
                    if item in not_applicable.get(place, ()):
                        continue
                    box = QCheckBox()
                    box.setChecked(item in chosen.get(place, ()))
                    box.setToolTip(f'{item}: {places[place]}')
                    grid.addWidget(box, row, column, Qt.AlignCenter)
                    self.boxes[place, item] = box
                self.items.append(item)
                row += 1
        layout.addLayout(grid)
        width_row = QHBoxLayout()
        width_row.addWidget(QLabel('Info boxes at most'))
        self.width_box = QSpinBox()
        self.width_box.setRange(minimum, maximum)
        self.width_box.setSingleStep(20)
        self.width_box.setSuffix(' px wide')
        self.width_box.setValue(max(minimum, min(maximum, width)))
        self.width_box.setToolTip('Longer text (e.g. a long file name) wraps onto more lines, so a card never covers '
                                  'the map. Also the label of the selected track.')
        width_row.addWidget(self.width_box)
        width_row.addStretch(1)
        layout.addLayout(width_row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self):
        """{place: checked items, in the order of the rows}."""
        return {place: [item for item in self.items if (place, item) in self.boxes and self.boxes[place, item].isChecked()]
                for place in self.places}

    def info_width(self):
        return self.width_box.value()
