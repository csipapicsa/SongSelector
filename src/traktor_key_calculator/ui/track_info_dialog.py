"""Dialog to edit the Artist / Title / Genre tags of one audio file."""
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from traktor_key_calculator.core.tag_writer import EDITABLE_TAGS


class TrackInfoDialog(QDialog):
    def __init__(self, path, values, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Edit track info')
        self.setMinimumWidth(480)
        self.original = {name: values.get(name, '') for name in EDITABLE_TAGS}
        self.fields = {}

        layout = QVBoxLayout(self)
        location = QLabel(str(path))
        location.setWordWrap(True)
        layout.addWidget(location)
        form = QFormLayout()
        for name in EDITABLE_TAGS:
            self.fields[name] = QLineEdit(self.original[name])
            form.addRow(name + ':', self.fields[name])
        layout.addLayout(form)
        note = QLabel('Saved into the audio file\'s tags. Traktor shows the change after it re-reads the file.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def changed_values(self):
        """Only the fields the user changed, e.g. {'Genre': 'Breaks'}."""
        values = {name: field.text().strip() for name, field in self.fields.items()}
        return {name: value for name, value in values.items() if value != self.original[name].strip()}
