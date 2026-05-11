from PySide6.QtWidgets import (QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QWidget, QScrollArea, QSizePolicy)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPixmap
from ui.widgets.base_page import BasePage

class VisionPage(BasePage):
    snapshot_requested = Signal()

    def __init__(self):
        super().__init__("视觉")
        # 预览区
        self.preview = QLabel("相机未连接")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(350)
        self.preview.setStyleSheet("background:#0a0a1a;border:2px solid #0f3460;border-radius:8px;")
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.content_layout.addWidget(self.preview, 1)

        # 控制栏
        ctrl = QHBoxLayout()
        btn = QPushButton("📷 拍照")
        btn.setStyleSheet("background:#e94560;color:#fff;font-size:16px;border-radius:6px;padding:10px 24px;min-height:48px;")
        btn.clicked.connect(self.snapshot_requested.emit)
        ctrl.addWidget(btn)
        ctrl.addStretch()
        self.info_label = QLabel("FPS: --  分辨率: --")
        self.info_label.setStyleSheet("color:#a0a0c0;font-size:13px;")
        ctrl.addWidget(self.info_label)
        self.content_layout.addLayout(ctrl)

        # 缩略图条
        thumb_label = QLabel("最近拍照:")
        thumb_label.setStyleSheet("color:#a0a0c0;font-size:12px;")
        self.content_layout.addWidget(thumb_label)
        self.thumb_layout = QHBoxLayout()
        self.thumbs = []
        for _ in range(5):
            lbl = QLabel()
            lbl.setFixedSize(100, 80)
            lbl.setStyleSheet("background:#16213e;border:1px solid #0f3460;border-radius:4px;")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setText("...")
            self.thumbs.append(lbl)
            self.thumb_layout.addWidget(lbl)
        self.thumb_layout.addStretch()
        self.content_layout.addLayout(self.thumb_layout)

    def on_camera_frame(self, pixmap: QPixmap):
        scaled = pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(scaled)

    def on_camera_status(self, data: dict):
        fps = data.get("fps", "--")
        res = data.get("resolution", "--")
        self.info_label.setText(f"FPS: {fps}  分辨率: {res}")

    def on_snapshot_saved(self, path: str):
        """新照片添加到缩略图条最前面"""
        pix = QPixmap(path)
        if pix.isNull():
            return
        # 循环右移缩略图
        for i in range(len(self.thumbs)-1, 0, -1):
            prev = self.thumbs[i-1].pixmap()
            self.thumbs[i].setPixmap(prev.scaled(100,80,Qt.KeepAspectRatio,Qt.SmoothTransformation) if prev else None)
        self.thumbs[0].setPixmap(pix.scaled(100, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))