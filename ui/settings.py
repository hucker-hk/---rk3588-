import json
from pathlib import Path
from PySide6.QtWidgets import (QGroupBox, QFormLayout, QLineEdit, QSpinBox,
    QPushButton, QHBoxLayout, QComboBox, QLabel)
from ui.widgets.base_page import BasePage

CONFIG = Path(__file__).parent.parent / "config.json"

class SettingsPage(BasePage):
    def __init__(self):
        super().__init__("系统设置")
        self.cfg = {}
        self.load_config()

    def load_config(self):
        if CONFIG.exists():
            self.cfg = json.loads(CONFIG.read_text())
        self._build_ui()

    def _build_ui(self):
        # 清空旧控件
        while self.content_layout.count() > 1:
            self.content_layout.takeAt(1)
        # 清空除标题外的所有
        for i in reversed(range(self.content_layout.count())):
            w = self.content_layout.itemAt(i).widget()
            if w is not self.title_label:
                self.content_layout.removeWidget(w)
                w.deleteLater()

        def add_group(title, fields):
            g = QGroupBox(title)
            g.setStyleSheet("QGroupBox{color:#e94560;font-weight:bold;font-size:14px;padding-top:12px;}")
            f = QFormLayout(g)
            for label, key, default in fields:
                val = self._get(key, default)
                e = QLineEdit(str(val))
                e.setMinimumHeight(44)
                e.setStyleSheet("background:#16213e;color:#fff;border:1px solid #0f3460;border-radius:4px;padding:4px;")
                setattr(self, f"edit_{key}", e)
                f.addRow(QLabel(label), e)
            self.content_layout.addWidget(g)

        add_group("网络设置", [
            ("PLC IP:端口", "plc.host", "192.35.2.5:502"),
            ("HMI IP:端口", "hmi.host", "192.35.2.10:502"),
        ])
        add_group("串口设置", [
            ("串口设备", "serial.port", "/dev/ttyS0"),
            ("波特率", "serial.baudrate", "9600"),
        ])
        add_group("相机设置", [
            ("RTSP 地址", "camera.rtsp_url", "rtsp://192.35.2.100:554/stream1"),
        ])

        btn = QPushButton("保存设置")
        btn.setStyleSheet("background:#e94560;color:#fff;border-radius:6px;padding:12px;font-size:16px;min-height:48px;")
        btn.clicked.connect(self.save_config)
        self.content_layout.addWidget(btn)
        self.content_layout.addStretch()

    def _get(self, key, default):
        keys = key.split(".")
        v = self.cfg
        for k in keys:
            if isinstance(v, dict):
                v = v.get(k, default)
            else:
                return default
        return v if v is not None else default

    def _set(self, key, value):
        keys = key.split(".")
        d = self.cfg
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    def save_config(self):
        for key in ["plc.host","hmi.host","serial.port","serial.baudrate","camera.rtsp_url"]:
            edit = getattr(self, f"edit_{key}", None)
            if edit:
                v = edit.text()
                self._set(key, int(v) if v.isdigit() else v)
        CONFIG.write_text(json.dumps(self.cfg, indent=2, ensure_ascii=False))
        self.trigger_alarm("info", "设置已保存")