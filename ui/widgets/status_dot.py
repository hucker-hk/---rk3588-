"""Status indicator dot widget — green / red / yellow."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPainter, QBrush, QColor
from PySide6.QtWidgets import QWidget, QSizePolicy

COLOR_MAP = {
    "green": QColor("#00ff88"),
    "red": QColor("#ff4444"),
    "yellow": QColor("#ffaa00"),
    "grey": QColor("#555555"),
}


class StatusDot(QWidget):
    """A small circular indicator that reflects a binary / tri-state status."""

    def __init__(self, size: int = 16, parent=None):
        super().__init__(parent)
        self._color = QColor("#555555")
        self._dot_size = size
        self.setMinimumSize(size, size)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self):
        return QSize(self._dot_size, self._dot_size)

    def set_state(self, state: str):
        """Set dot colour by name: 'green', 'red', 'yellow', 'grey'."""
        self._color = COLOR_MAP.get(state, COLOR_MAP["grey"])
        self.update()

    def set_green(self):
        self.set_state("green")

    def set_red(self):
        self.set_state("red")

    def set_yellow(self):
        self.set_state("yellow")

    def set_grey(self):
        self.set_state("grey")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(self._color))
        margin = 2
        p.drawEllipse(margin, margin, self._dot_size - 2 * margin, self._dot_size - 2 * margin)
        p.end()
