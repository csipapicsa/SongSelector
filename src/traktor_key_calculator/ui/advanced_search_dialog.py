"""
advanced_search_panel.py
Advanced search panel
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from traktor_key_calculator.core.color_search import COLOR_HELP, COLOR_NAMES, parse_color_values
from traktor_key_calculator.core.search_filters import (
    COLOR_COLUMNS,
    NO_COLUMN,
    NUMERIC_COLUMNS,
    NUMERIC_COMPARISONS,
    TEXT_CONDITIONS,
    active_filters,
    parse_number,
)


class AdvancedSearchRow(QWidget):
    def __init__(self, column_names, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        self.column_combo = QComboBox()
        self.column_combo.addItems([NO_COLUMN] + list(column_names))
        self.column_combo.setCurrentIndex(1 if column_names else 0)
        self.column_combo.setToolTip(f'{NO_COLUMN}: keep this row but leave it out of the search.')

        self.condition_combo = QComboBox()
        self.condition_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)

        self.value_edit = QLineEdit()
        self.color_completer = QCompleter(list(COLOR_NAMES.values()) + ['purple', 'magenta'], self)
        self.color_completer.setCaseSensitivity(Qt.CaseInsensitive)

        layout.addWidget(self.column_combo)
        layout.addWidget(self.condition_combo)
        layout.addWidget(self.value_edit)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        self.column_combo.currentTextChanged.connect(self.update_conditions)
        self.condition_combo.currentTextChanged.connect(self.update_value_hint)
        self.update_conditions()

    def update_conditions(self, _column=None):
        selected = self.condition_combo.currentText()
        conditions = list(TEXT_CONDITIONS)
        # None offers every condition, so a numeric one is kept while the row is switched off.
        if self.column_combo.currentText() in NUMERIC_COLUMNS | {NO_COLUMN}:
            conditions += list(NUMERIC_COMPARISONS)
        self.condition_combo.blockSignals(True)
        self.condition_combo.clear()
        self.condition_combo.addItems(conditions)
        if selected in conditions:
            self.condition_combo.setCurrentText(selected)
        self.condition_combo.blockSignals(False)
        self.update_value_hint()

    def update_value_hint(self, _condition=None):
        numeric = self.condition_combo.currentText() in NUMERIC_COMPARISONS
        color = self.column_combo.currentText() in COLOR_COLUMNS
        self.value_edit.setCompleter(self.color_completer if color and not numeric else None)
        self.value_edit.setPlaceholderText('e.g. 5' if color and numeric else 'e.g. blue or red,orange' if color else 'e.g. 128.5' if numeric else '')
        self.value_edit.setToolTip('Category colors: ' + COLOR_HELP if color else '')

    def get_filter(self):
        return {
            'column': self.column_combo.currentText(),
            'condition': self.condition_combo.currentText(),
            'value': self.value_edit.text().strip()
        }

class AdvancedSearchDialog(QDialog):
    """The Complex Search rows. With `smartlist` (a name) it edits that smartlist's rules
    instead; with `save_smartlist` (a callable taking the rows) it offers Save as Smartlist."""
    def __init__(self, column_names, parent=None, smartlist=None, save_smartlist=None):
        super().__init__(parent)

        self.setWindowTitle(f"Smartlist: {smartlist}" if smartlist else "Complex Search Panel")
        self.setModal(True)
        self.resize(600, 400)
        self.column_names = column_names
        self.save_smartlist = save_smartlist

        main_layout = QVBoxLayout()
        self.checkbox_enable = QCheckBox("Enable Complex Search")
        self.checkbox_enable.setChecked(True)
        self.checkbox_enable.setVisible(not smartlist)  # a smartlist always applies its rules
        main_layout.addWidget(self.checkbox_enable)

        self.filter_rows = []
        for _ in range(10):
            row = AdvancedSearchRow(self.column_names)
            self.filter_rows.append(row)
            main_layout.addWidget(row)

        # Buttons
        button_layout = QHBoxLayout()
        self.button_save_smartlist = QPushButton("Save as Smartlist...")
        self.button_save_smartlist.setToolTip('Save these rows as a smartlist under Playlists in the Browser tab. '
                                              'It always lists the tracks that match them.')
        self.button_save_smartlist.setVisible(save_smartlist is not None)
        self.button_ok = QPushButton("OK")
        self.button_cancel = QPushButton("Cancel")
        button_layout.addWidget(self.button_save_smartlist)
        button_layout.addStretch()
        button_layout.addWidget(self.button_ok)
        button_layout.addWidget(self.button_cancel)

        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

        self.button_ok.clicked.connect(self.accept_filters)
        self.button_cancel.clicked.connect(self.reject)
        self.button_save_smartlist.clicked.connect(self._save_as_smartlist)

    def set_filters(self, filters):
        for row, filter_data in zip(self.filter_rows, filters):
            row.column_combo.setCurrentText(filter_data['column'])
            row.condition_combo.setCurrentText(filter_data['condition'])
            row.value_edit.setText(filter_data['value'])

    def saved_filters(self):
        """Rows with a value, also those set to None, so they come back next time."""
        return [row.get_filter() for row in self.filter_rows if row.get_filter()['value']]

    def get_active_filters(self):
        return active_filters(row.get_filter() for row in self.filter_rows)

    def _valid(self):
        for row in self.filter_rows:
            value = row.value_edit.text().strip() if row.column_combo.currentText() != NO_COLUMN else ''
            if value and row.column_combo.currentText() in COLOR_COLUMNS and row.condition_combo.currentText() not in NUMERIC_COMPARISONS:
                _, error = parse_color_values(value)
                if error:
                    QMessageBox.warning(self, 'Invalid color filter', error)
                    row.value_edit.setFocus()
                    return False
            if value and row.condition_combo.currentText() in NUMERIC_COMPARISONS and parse_number(value) is None:
                QMessageBox.warning(self, 'Invalid numeric filter',
                                    f'Enter a number for {row.column_combo.currentText()}, for example 128.5.')
                row.value_edit.setFocus()
                return False
        return True

    def accept_filters(self):
        if self.checkbox_enable.isChecked() and not self._valid():
            return
        self.accept()

    def _save_as_smartlist(self):
        if self._valid():
            self.save_smartlist(self.saved_filters())
