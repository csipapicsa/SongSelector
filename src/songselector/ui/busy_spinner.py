"""A small spinning arc next to a status text: something is working right now.

Several things can make one spinner busy at the same time (saving tags while a description search runs): each
caller turns its own reason on and off, and the spinner turns while any reason is on. The tooltip lists them. While
idle the spinner is hidden and its timer is stopped, so it costs nothing.
"""
from PyQt5.QtCore import QRectF, QSize, Qt, QTimer
from PyQt5.QtGui import QPainter, QPen
from PyQt5.QtWidgets import QSizePolicy, QWidget

FRAME_MS = 50          # 20 frames per second: smooth enough for a small arc, cheap
STEP_DEGREES = 30      # turn per frame: one full turn in 0.6 s
ARC_DEGREES = 270


class BusySpinner(QWidget):
    def __init__(self, size=14, parent=None):
        super().__init__(parent)
        self._size = size
        self._angle = 0
        self._reasons = []  # in the order they started
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._turn)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setVisible(False)

    def sizeHint(self):
        return QSize(self._size + 4, self._size + 4)

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_busy(self, reason, on=True):
        """Turn one reason on or off (e.g. 'Saving tags'); the spinner shows while any is on."""
        if on and reason not in self._reasons:
            self._reasons.append(reason)
        elif not on and reason in self._reasons:
            self._reasons.remove(reason)
        self.setToolTip('\n'.join(f'{reason}...' for reason in self._reasons))
        if self._reasons and not self._timer.isActive():
            self._timer.start()
            self.setVisible(True)
        elif not self._reasons and self._timer.isActive():
            self._timer.stop()
            self.setVisible(False)

    def busy(self):
        return bool(self._reasons)

    def reasons(self):
        return list(self._reasons)

    def running(self):
        """The animation timer runs (only while busy)."""
        return self._timer.isActive()

    def _turn(self):
        self._angle = (self._angle + STEP_DEGREES) % 360
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self.palette().highlight().color(), max(2.0, self._size / 7))
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        margin = pen.widthF() / 2 + 2
        side = min(self.width(), self.height()) - 2 * margin
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        # Qt angles are in 1/16 degree, counter-clockwise; a negative start turns the arc clockwise.
        painter.drawArc(rect, -self._angle * 16, ARC_DEGREES * 16)
