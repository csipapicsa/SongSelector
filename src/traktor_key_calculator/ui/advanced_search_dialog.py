"""
advanced_search_panel.py
Advanced search panel
"""

from PyQt5.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QComboBox,
    QLineEdit, QPushButton, QCheckBox, QMessageBox, QCompleter
)
from PyQt5.QtCore import Qt
from traktor_key_calculator.core.color_search import COLOR_NAMES, COLOR_HELP, parse_color_values
from traktor_key_calculator.core.search_filters import (NUMERIC_COLUMNS, COLOR_COLUMNS, TEXT_CONDITIONS,
                                                       NUMERIC_COMPARISONS, NO_COLUMN, parse_number,
                                                       active_filters)


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
    def __init__(self, column_names, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Complex Search Panel")
        self.setModal(True)
        self.resize(600, 400)
        self.column_names = column_names

        main_layout = QVBoxLayout()
        self.checkbox_enable = QCheckBox("Enable Complex Search")
        self.checkbox_enable.setChecked(True)
        main_layout.addWidget(self.checkbox_enable)

        self.filter_rows = []
        for _ in range(10):
            row = AdvancedSearchRow(self.column_names)
            self.filter_rows.append(row)
            main_layout.addWidget(row)

        # Buttons
        button_layout = QHBoxLayout()
        self.button_ok = QPushButton("OK")
        self.button_cancel = QPushButton("Cancel")
        button_layout.addStretch()
        button_layout.addWidget(self.button_ok)
        button_layout.addWidget(self.button_cancel)

        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

        self.button_ok.clicked.connect(self.accept_filters)
        self.button_cancel.clicked.connect(self.reject)

    def get_active_filters(self):
        return active_filters(row.get_filter() for row in self.filter_rows)

    def accept_filters(self):
        if self.checkbox_enable.isChecked():
            for row in self.filter_rows:
                value = row.value_edit.text().strip() if row.column_combo.currentText() != NO_COLUMN else ''
                if value and row.column_combo.currentText() in COLOR_COLUMNS and row.condition_combo.currentText() not in NUMERIC_COMPARISONS:
                    _, error = parse_color_values(value)
                    if error:
                        QMessageBox.warning(self, 'Invalid color filter', error)
                        row.value_edit.setFocus()
                        return
                if value and row.condition_combo.currentText() in NUMERIC_COMPARISONS and parse_number(value) is None:
                    QMessageBox.warning(self, 'Invalid numeric filter',
                                        f'Enter a number for {row.column_combo.currentText()}, for example 128.5.')
                    row.value_edit.setFocus()
                    return
        self.accept()
