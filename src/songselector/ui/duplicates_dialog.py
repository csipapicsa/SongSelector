"""Preview of a duplicate search: each group with the row that stays and the rows to remove (checkable)."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from songselector.core.duplicates import MODES


def _describe(row):
    artist, title = row.get('Artist') or '', row.get('Title') or ''
    name = f'{artist} - {title}' if artist and title else (title or artist or '(no title)')
    return str(name), str(row.get('File_Path') or '')


class DuplicatesDialog(QDialog):
    """groups: [core.duplicates.Group]; rows: {table index: row dict}. removed_indexes() after exec_()."""

    def __init__(self, mode, groups, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Delete duplicates: {MODES[mode]}')
        self.resize(900, 520)
        count = sum(len(group.remove) for group in groups)
        layout = QVBoxLayout(self)
        intro = QLabel(f'{len(groups)} group(s), {count} row(s) to remove. In each group the row in bold stays: its file '
                       'exists, it has the most information filled in, it is in the Traktor / Rekordbox collection, or '
                       'it comes first. Untick a row to keep it as well.\n'
                       'Only rows of the list are removed; the files on disk are not deleted.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Track', 'File', 'Why'])
        self.tree.setRootIsDecorated(True)
        self._checks = []  # (item, table index)
        for group in groups:
            name, path = _describe(rows[group.keep])
            parent_item = QTreeWidgetItem([f'Keep: {name}', path, group.reasons.get(group.keep, '')])
            font = parent_item.font(0)
            font.setBold(True)
            for column in range(3):
                parent_item.setFont(column, font)
            self.tree.addTopLevelItem(parent_item)
            for index in group.remove:
                name, path = _describe(rows[index])
                child = QTreeWidgetItem([f'Remove: {name}', path, group.reasons.get(index, '')])
                child.setCheckState(0, Qt.Checked)
                parent_item.addChild(child)
                self._checks.append((child, index))
            parent_item.setExpanded(True)
        for column in range(3):
            self.tree.resizeColumnToContents(column)
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        self.tree.itemChanged.connect(self._update_button)
        self._update_button()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def removed_indexes(self):
        """Table indexes of the rows still ticked for removal."""
        return [index for item, index in self._checks if item.checkState(0) == Qt.Checked]

    def _update_button(self, *_args):
        count = len(self.removed_indexes())
        self.ok_button.setText(f'Remove {count} row(s)')
        self.ok_button.setEnabled(count > 0)
