"""Draw Traktor category dots while respecting row backgrounds and selection."""
from PyQt5.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle, QApplication
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush
from traktor_key_calculator.config import COLOR_MAPPING_CATEGORY


class ColorDotDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dot_size = 16

    def sizeHint(self, option, index):
        return QSize(self.dot_size + 12, self.dot_size + 8)

    def paint(self, painter, option, index):
        painter.save()
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        styled.text = ''
        style = styled.widget.style() if styled.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, styled, painter, styled.widget)
        try:
            color = COLOR_MAPPING_CATEGORY.get(int(float(index.data(Qt.DisplayRole))))
        except (TypeError, ValueError, OverflowError):
            color = None
        if color is not None:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(QPen(QColor(60, 60, 60), 1))
            painter.setBrush(QBrush(color))
            center = option.rect.center()
            painter.drawEllipse(center.x() - self.dot_size // 2,
                                center.y() - self.dot_size // 2,
                                self.dot_size, self.dot_size)
        painter.restore()
