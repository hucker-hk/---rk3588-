"""历史报警页：表格展示、筛选、清除"""
from PySide6.QtWidgets import (QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QHBoxLayout)
from PySide6.QtCore import Qt, QDateTime
from ui.widgets.base_page import BasePage

LEVEL_COLORS = {"info": "#2196F3", "warning": "#FF9800", "error": "#f44336"}

class AlarmsPage(BasePage):
    def __init__(self):
        super().__init__("历史报警")
        # 筛选按钮
        bar = QHBoxLayout()
        for level, label in [("all","全部"),("error","错误"),("warning","警告"),("info","信息")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(level == "all")
            btn.setMinimumHeight(40)
            btn.setStyleSheet(
                "QPushButton{background:#16213e;color:#e0e0e0;border:1px solid #0f3460;border-radius:4px;padding:6px 12px;}"
                "QPushButton:checked{background:#e94560;}")
            btn.clicked.connect(lambda checked, l=level: self._filter(l))
            bar.addWidget(btn)
        bar.addStretch()
        clear_btn = QPushButton("清空")
        clear_btn.setMinimumHeight(40)
        clear_btn.setStyleSheet("background:#f44336;color:#fff;border-radius:4px;padding:6px 16px;")
        clear_btn.clicked.connect(self._clear)
        bar.addWidget(clear_btn)
        self.content_layout.addLayout(bar)

        # 表格
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["时间", "级别", "来源", "消息"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setStyleSheet(
            "QTableWidget{background:#16213e;color:#e0e0e0;border:1px solid #0f3460;gridline-color:#0f3460;}"
            "QHeaderView::section{background:#0f3460;color:#e94560;font-weight:bold;padding:6px;border:none;}")
        self.content_layout.addWidget(self.table)

        self._records = []          # [(time, level, source, msg), ...]
        self._filter_level = "all"

    def add_alarm(self, level, source, message):
        """外部推入报警记录"""
        now = QDateTime.currentDateTime().toString("MM-dd HH:mm:ss")
        self._records.append((now, level, source, message))
        self._refresh()

    def _filter(self, level):
        self._filter_level = level
        self._refresh()

    def _clear(self):
        self._records.clear()
        self._refresh()

    def _refresh(self):
        filtered = self._records if self._filter_level == "all" else                    [r for r in self._records if r[1] == self._filter_level]
        self.table.setRowCount(len(filtered))
        for i, (time, level, source, msg) in enumerate(filtered):
            self.table.setItem(i, 0, QTableWidgetItem(time))
            level_item = QTableWidgetItem(level)
            level_item.setForeground(Qt.GlobalColor.white)
            self.table.setItem(i, 1, level_item)
            self.table.setItem(i, 2, QTableWidgetItem(source))
            self.table.setItem(i, 3, QTableWidgetItem(msg))
            color = LEVEL_COLORS.get(level, "#e0e0e0")
            for col in range(4):
                self.table.item(i, col).setBackground(Qt.GlobalColor.transparent)