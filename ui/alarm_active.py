"""活跃报警页：嵌入侧边栏的当前未确认报警列表"""
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt
from ui.widgets.base_page import BasePage

LEVEL_COLORS = {"info": "#2196F3", "warning": "#FF9800", "error": "#f44336"}

class ActiveAlarmPage(BasePage):
    def __init__(self):
        super().__init__("实时报警")
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget{background:#16213e;color:#e0e0e0;border:1px solid #0f3460;border-radius:4px;}"
            "QListWidget::item{padding:8px;border-bottom:1px solid #0f3460;}")
        self.content_layout.addWidget(self.list_widget)

    def add_alarm(self, level, message):
        """添加一条活跃报警"""
        from PySide6.QtWidgets import QWidget
        color = LEVEL_COLORS.get(level, "#e0e0e0")
        item_widget = QWidget()
        layout = QHBoxLayout(item_widget)
        layout.setContentsMargins(4, 4, 4, 4)

        from PySide6.QtWidgets import QLabel
        dot = QLabel("●"); dot.setStyleSheet(f"color:{color};font-size:14px;")
        layout.addWidget(dot)
        msg = QLabel(message)
        msg.setStyleSheet("color:#e0e0e0;font-size:13px;")
        layout.addWidget(msg, 1)
        confirm = QPushButton("确认")
        confirm.setMinimumHeight(36)
        confirm.setStyleSheet(f"background:{color};color:#fff;border-radius:3px;padding:4px 10px;font-size:12px;")
        idx = self.list_widget.count()
        confirm.clicked.connect(lambda: self._confirm(idx))
        layout.addWidget(confirm)

        list_item = QListWidgetItem()
        list_item.setSizeHint(item_widget.sizeHint())
        self.list_widget.addItem(list_item)
        self.list_widget.setItemWidget(list_item, item_widget)

    def _confirm(self, index):
        if index < self.list_widget.count():
            self.list_widget.takeItem(index)