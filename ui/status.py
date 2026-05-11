from PySide6.QtWidgets import (QTableWidget, QTableWidgetItem, QHeaderView,
    QLabel, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt
from ui.widgets.base_page import BasePage
from ui.widgets.status_dot import StatusDot

class StatusPage(BasePage):
    def __init__(self):
        super().__init__("设备状态")
        self.table = QTableWidget(6, 4)
        self.table.setHorizontalHeaderLabels(["设备", "类型/地址", "状态", "数据"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setStyleSheet(
            "QTableWidget{background:#16213e;color:#e0e0e0;border:1px solid #0f3460;gridline-color:#0f3460;}"
            "QHeaderView::section{background:#0f3460;color:#e94560;font-weight:bold;padding:6px;border:none;}"
        )
        self.table.setMinimumHeight(300)
        self.content_layout.addWidget(self.table)

        self.rows = {
            "PLC":    0, "HMI": 1, "风扇1": 2, "风扇2": 3, "相机": 4, "Hermes": 5,
        }
        devices = ["PLC", "HMI", "风扇1", "风扇2", "相机", "Hermes Agent"]
        addrs   = ["192.35.2.5:502", "192.35.2.10:502", "/dev/ttyS0#1", "/dev/ttyS0#2", "RTSP", "DingTalk"]
        for i, (dev, addr) in enumerate(zip(devices, addrs)):
            self.table.setItem(i, 0, QTableWidgetItem(dev))
            self.table.setItem(i, 1, QTableWidgetItem(addr))
            dot = StatusDot()
            self.table.setCellWidget(i, 2, dot)

        self.content_layout.addStretch()

    def _update_row(self, name, status, data_text):
        i = self.rows.get(name)
        if i is None:
            return
        dot = self.table.cellWidget(i, 2)
        if dot:
            dot.set_status(status)
        self.table.setItem(i, 3, QTableWidgetItem(data_text))

    def on_plc_data(self, data: dict):
        ok = data.get("D") is not None
        self._update_row("PLC", "on" if ok else "off",
            f"D:{len(data.get('D',[]))} M:{len(data.get('M',[]))} X:{len(data.get('X',[]))} Y:{len(data.get('Y',[]))}")

    def on_fan1_data(self, data: dict):
        self._update_row("风扇1", "on" if data.get("speed",0)>0 else "off",
            f"{data.get('speed',0)}RPM {data.get('temp',0)}°C 目标{data.get('target_pct',0)}%")

    def on_fan2_data(self, data: dict):
        self._update_row("风扇2", "on" if data.get("speed",0)>0 else "off",
            f"{data.get('speed',0)}RPM {data.get('temp',0)}°C 目标{data.get('target_pct',0)}%")

    def on_hmi_data(self, data: dict):
        ok = bool(data.get("device"))
        self._update_row("HMI", "on" if ok else "off",
            f"{data.get('device','')} {data.get('region','')} {data.get('weather','')}")

    def on_camera_status(self, data: dict):
        ok = data.get("connected", False)
        self._update_row("相机", "on" if ok else "off",
            f"{data.get('resolution','')} {data.get('fps','')}FPS" if ok else "未连接")

    def on_hermes_status(self, ok: bool):
        self._update_row("Hermes", "on" if ok else "off", "DingTalk 在线" if ok else "离线")