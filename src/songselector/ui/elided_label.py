"""A one-line label that never makes the window wider than the user wants.

A plain QLabel asks for the width of its whole text as its minimum. In a layout (the status bar, the bar above the
List) a long message - a file name, a typed description - then raises the window's minimum width: the window
stretches and cannot be made narrower again. This label asks for almost nothing, shows as much of the text as fits
with '...' at the end, and shows the whole text as its tooltip.
"""
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import QLabel, QSizePolicy

MIN_WIDTH = 40  # px: room for a few characters and the '...'


class ElidedLabel(QLabel):
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self._full = ''
        self._details = ''  # more lines for the tooltip, under the text
        # Preferred: the text's width when there is room, down to minimumSizeHint when there is not
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setText(text)

    def text(self):
        return self._full

    def setText(self, text):
        self._full = str(text or '')
        self._update_tooltip()
        self._elide()
        self.updateGeometry()

    def set_details(self, details):
        self._details = str(details or '')
        self._update_tooltip()

    def _update_tooltip(self):
        self.setToolTip('\n\n'.join(part for part in (self._full, self._details) if part))

    def _elide(self):
        width = self.contentsRect().width()
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, width) if width > 0 else self._full
        super().setText(shown)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event):  # a style sheet can change the font (bold)
        super().changeEvent(event)
        self._elide()

    def sizeHint(self):
        """The whole text, if there is room for it; the layout gives less when there is not."""
        margins = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance(self._full) + margins.left() + margins.right() + 4
        return QSize(width, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(MIN_WIDTH, super().minimumSizeHint().height())
