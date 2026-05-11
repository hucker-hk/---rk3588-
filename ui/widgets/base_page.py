"""
页面基类：统一标题栏、报警信号、深色背景。
所有页面继承此类。
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Signal

class BasePage(QWidget):
    title_changed = Signal(str)
    alarm_triggered = Signal(str, str)  # (level, message)

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self._title = title
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 12)
        self._layout.setSpacing(10)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-size:20px;font-weight:bold;color:#ffffff;padding-bottom:4px;")
        self._layout.addWidget(self.title_label)

    def set_title(self, text):
        self._title = text
        self.title_label.setText(text)
        self.title_changed.emit(text)

    @property
    def content_layout(self):
        """子类通过此属性添加自己的控件"""
        return self._layout

    def trigger_alarm(self, level, message):
        self.alarm_triggered.emit(level, message)
