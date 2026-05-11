#!/usr/bin/env python3
"""
煎饼机工控系统 — 主窗口 + 桥接层
公共框架：顶部标题栏常驻，下方 QStackedWidget 切换页面。
"""

import sys, json
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QMenu, QSizePolicy, QFrame,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QRect, QRectF, QPoint
from PySide6.QtGui import QFont, QAction, QPainter, QPen, QColor

# 通信模块延迟导入 —— 缺少依赖不影响 UI 启动
try:
    from core.plc_worker import PlcWorker
    from core.plc import parse_snapshot, build_read_configs, POINTS, mb_addr
    from core.serial_devices import SerialDeviceController
    from core.hmi import KunlunHMI
except ImportError:
    PlcWorker = None              # type: ignore
    parse_snapshot = None         # type: ignore
    build_read_configs = None     # type: ignore
    POINTS = {}                  # type: ignore
    mb_addr = None               # type: ignore
    SerialDeviceController = None  # type: ignore
    KunlunHMI = None             # type: ignore

from ui.home import HomePage
from ui.settings import SettingsPage
from ui.manual import ManualPage
from ui.vision import VisionPage
from ui.status import StatusPage
from ui.about import AboutPage
from ui.alarms import AlarmsPage
from ui.alarm_active import ActiveAlarmPage
from ui.widgets.alarm_popup import AlarmPopup

CONFIG = Path(__file__).parent / "config.json"
cfg = json.loads(CONFIG.read_text())

STYLE = """
QMainWindow { background-color: #1a1a2e; }
QWidget { font-family: "WenQuanYi Micro Hei", "Noto Sans CJK SC", sans-serif; color: #e0e0e0; }
QPushButton { border: none; border-radius: 4px; padding: 6px 10px; }
"""


# ═══════════════════════════════════════════════════════════
# Header Bar — public frame
# ═══════════════════════════════════════════════════════════
# 按钮可视化风格
BTN_STYLE = (
    "QPushButton{"
    "font-size:18px;font-weight:bold;color:#e0e0e0;"
    "background:#16213e;border:2px solid #0f3460;"
    "border-radius:14px;padding:6px 16px;"
    "}"
    "QPushButton:hover{background:#0f3460;border-color:#e94560;}"
    "QPushButton:pressed{background:#0a0a1e;}"
)
BTN_TOGGLE_ON = (
    "QPushButton:checked{background:#00c853;color:#000;border-color:#00c853;}"
)


# ═══════════════════════════════════════════════════════════
# EmojiToggleButton — 双层自定义控件 (26px emoji + 10px 文字, 60px 高)
# ═══════════════════════════════════════════════════════════

class EmojiToggleButton(QWidget):
    """双层 toggle 按钮：上层 26px emoji + 下层 10px 文字，60px 高度不裁切。
    替换 QPushButton 以解决单 font-size 无法分别控制 emoji/文字的问题。
    """
    toggled = Signal(bool)

    def __init__(self, emoji: str, label: str, width: int = 80, height: int = 60, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._checked = False
        self._hovered = False
        self._emoji_color = "#e0e0e0"
        self._checked_bg = "#00c853"
        self._use_checked_bg = True  # True=背景变色(power), False=边框变色(light)

        self.setStyleSheet("""
            EmojiToggleButton {
                background: #16213e;
                border: 2px solid #0f3460;
                border-radius: 10px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        self._emoji_label = QLabel(emoji)
        self._emoji_label.setAlignment(Qt.AlignCenter)
        self._emoji_label.setStyleSheet(
            f"font-size:26px;font-weight:bold;color:{self._emoji_color};"
            "background:transparent;border:none;"
        )

        self._text_label = QLabel(label)
        self._text_label.setAlignment(Qt.AlignCenter)
        self._text_label.setStyleSheet(
            "font-size:10px;color:#888;background:transparent;border:none;"
        )

        layout.addWidget(self._emoji_label)
        layout.addWidget(self._text_label)

    # ── Public API ──────────────────────────────────────────

    def setChecked(self, checked: bool):
        """设置 toggle 状态（不触发信号）"""
        self._checked = checked
        self._update_style()

    def isChecked(self) -> bool:
        return self._checked

    def set_emoji_color(self, color: str):
        """设置 emoji 颜色（power: D211 状态色, light: ON/OFF 双态色）"""
        self._emoji_color = color
        self._update_style()

    def set_emoji(self, text: str):
        """切换 emoji 文字（light: 💡/🔅）"""
        self._emoji_label.setText(text)

    def set_label(self, text: str):
        """切换底部标签文字"""
        self._text_label.setText(text)

    def set_use_checked_bg(self, use: bool):
        """True=checked 时背景变色, False=checked 时边框变色"""
        self._use_checked_bg = use
        self._update_style()

    # ── Internal ────────────────────────────────────────────

    def _update_style(self):
        # Determine effective background and border colors
        if self._checked and self._use_checked_bg:
            bg = self._checked_bg
            border = self._checked_bg
            text_color = "#000"
        elif self._checked and not self._use_checked_bg:
            bg = "#16213e"
            border = self._emoji_color
            text_color = self._emoji_color
        else:
            bg = "#16213e"
            border = "#0f3460"
            text_color = self._emoji_color

        # Hover: brighten background + border (matching BTN_STYLE)
        if self._hovered:
            bg = "#0f3460"
            border = "#e94560"

        self.setStyleSheet(
            f"EmojiToggleButton{{background:{bg};"
            f"border:2px solid {border};border-radius:10px;}}"
        )
        self._emoji_label.setStyleSheet(
            f"font-size:26px;font-weight:bold;color:{text_color};"
            "background:transparent;border:none;"
        )
        sub_color = text_color if (self._checked and self._use_checked_bg) else "#888"
        self._text_label.setStyleSheet(
            f"font-size:10px;color:{sub_color};background:transparent;border:none;"
        )

    def enterEvent(self, event):
        self._hovered = True
        self._update_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._update_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self._update_style()
        self.toggled.emit(self._checked)
        super().mousePressEvent(event)


# ═══════════════════════════════════════════════════════════
# WiFi Signal Widget — QPainter hand-drawn arc icon
# ═══════════════════════════════════════════════════════════

class WifiSignalWidget(QWidget):
    """WiFi信号图标，手绘弧形 + 底部圆点，4档信号等级"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self._level = 0  # 0-4 (0=无信号, 4=满格)
        self._auto = True

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(3000)
        self._refresh()

    def set_level(self, level: int):
        """外部设置信号等级 0-4，-1 恢复自动读取"""
        if level == -1:
            self._auto = True
            if not self._timer.isActive():
                self._timer.start(3000)
            self._refresh()
        else:
            self._auto = False
            self._timer.stop()
            self._level = max(0, min(4, level))
            self._update_display()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w // 2
        cy = h // 2

        active_color = QColor("#00c853")
        inactive_color = QColor("#404060")

        # ── Bottom dot ──────────────────────────────
        dot_y = 43
        dot_d = 8
        dot_color = active_color if self._level >= 1 else inactive_color
        painter.setPen(Qt.NoPen)
        painter.setBrush(dot_color)
        painter.drawEllipse(QPoint(cx, dot_y), dot_d // 2, dot_d // 2)

        # ── 3 concentric arcs (fan outward from dot) ──
        # (diameter, min_level, start_angle°, span_angle°)
        # Arcs centered below dot so they fan upward; all spans < 120°
        # Qt angles: 0=3h(right), 90=12h(top), CCW+
        # Arc spans: outer widest, inner narrowest
        arc_center_y = dot_y + 2   # arc center just below dot
        arc_specs = [
            (62, 4, 45,  90),   # outermost (top)
            (46, 3, 45,  90),   # middle
            (30, 2, 45,  90),   # innermost (closest to dot)
        ]

        for diameter, min_level, start_deg, span_deg in arc_specs:
            r = diameter // 2
            x = cx - r
            y = arc_center_y - r
            rect = QRectF(x, y, diameter, diameter)

            color = active_color if self._level >= min_level else inactive_color
            pen = QPen(color, 3)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)

            painter.drawArc(rect, start_deg * 16, span_deg * 16)

        # ── Disconnected overlay (large red ✕, ~50×50) ──
        if self._level == 0:
            font = QFont()
            font.setPixelSize(38)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#e94560"))
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "✕")

        painter.end()

    def _refresh(self):
        if not self._auto:
            return
        level = self._read_signal()
        if level != self._level:
            self._level = level
            self._update_display()

    def _update_display(self):
        self.setToolTip(f"WiFi 信号: {self._level}/4")
        self.update()  # trigger repaint

    def _read_signal(self) -> int:
        import subprocess, re

        # --- /proc/net/wireless and iwconfig are DEPRECATED ---
        # Newer WiFi drivers (iwlwifi etc.) don't support wireless extensions.
        # Both return all-zero or "no wireless extensions" on this device.
        # Replaced by /sys carrier check + nmcli below.
        # ----------------------------------------------------

        # 1. Check carrier — if no link, signal is 0 immediately
        try:
            with open('/sys/class/net/wlan0/carrier', 'r') as f:
                if f.read().strip() != '1':
                    return 0
        except (FileNotFoundError, IOError):
            return 0

        # 2. nmcli: parse the associated (*) AP's SIGNAL percentage (0–100)
        try:
            result = subprocess.run(
                ['nmcli', '-t', '-f', 'IN-USE,SIGNAL', 'device', 'wifi', 'list'],
                capture_output=True, text=True, timeout=3
            )
            for line in result.stdout.strip().split('\n'):
                # Lines look like:  "*:100"  or  ":85" (unassociated)
                if line.startswith('*:'):
                    pct_str = line[2:].strip()
                    pct = float(pct_str)
                    return WifiSignalWidget._pct_to_level(pct)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
            pass

        # 3. Fallback: carrier is up but we can't read signal → assume medium
        return 2

    @staticmethod
    def _quality_to_level(quality: float) -> int:
        pct = min(quality / 70.0 * 100, 100)
        return WifiSignalWidget._pct_to_level(pct)

    @staticmethod
    def _dbm_to_level(dbm: int) -> int:
        if dbm >= -50:
            return 4
        elif dbm >= -60:
            return 3
        elif dbm >= -70:
            return 2
        elif dbm >= -80:
            return 1
        return 0

    @staticmethod
    def _pct_to_level(pct: float) -> int:
        if pct >= 75:
            return 4
        elif pct >= 50:
            return 3
        elif pct >= 25:
            return 2
        elif pct > 0:
            return 1
        return 0


class HeaderBar(QWidget):
    """公共标题栏，所有页面共享。首页/子页左右布局不同。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(68)

        self._outer_layout = QHBoxLayout(self)
        self._outer_layout.setContentsMargins(12, 6, 12, 6)
        self._outer_layout.setSpacing(10)

        # ── Left: Sub-page mode (返回 + 温度) ──────────────
        self.sub_left = QWidget()
        sl = QHBoxLayout(self.sub_left)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)

        self.btn_back = QPushButton("← 返回")
        self.btn_back.setToolTip("返回")
        self.btn_back.setFixedHeight(44)
        self.btn_back.setMinimumWidth(72)
        self.btn_back.setStyleSheet(BTN_STYLE.replace("border-radius:14px", "border-radius:8px") + BTN_TOGGLE_ON)
        sl.addWidget(self.btn_back)

        self.aodian_temp_label = QLabel("--.-°C")
        self.aodian_temp_label.setStyleSheet("font-size:22px;font-weight:bold;color:#ff6b35;")
        sl.addWidget(self.aodian_temp_label)
        sl.addStretch()

        # ── Left: Home mode (电源 照明 相机 下拉) ──────────
        self.home_left = QWidget()
        hl = QHBoxLayout(self.home_left)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)

        self._power_status = 0  # 0=关机, 1=运行, 2=待机 (D211)

        self.power_btn = EmojiToggleButton("⏻", "电源", 80, 60)
        self.power_btn.set_emoji_color("#e94560")
        hl.addWidget(self.power_btn)

        self.light_btn = EmojiToggleButton("🔅", "照明", 80, 60)
        self.light_btn.set_emoji_color("#505060")
        self.light_btn.set_use_checked_bg(False)  # Light uses border color change
        hl.addWidget(self.light_btn)

        self.camera_btn = QPushButton("📷 相机")
        self.camera_btn.setStyleSheet(BTN_STYLE)
        hl.addWidget(self.camera_btn)

        # 下拉菜单
        self.menu_btn = QPushButton("☰ 菜单")
        self.menu_btn.setStyleSheet(BTN_STYLE)
        self._menu = QMenu(self)
        self._menu.setStyleSheet(
            "QMenu{background:#16213e;color:#e0e0e0;border:1px solid #0f3460;padding:4px;font-size:16px;}"
            "QMenu::item{padding:10px 28px;border-radius:4px;}"
            "QMenu::item:selected{background:#0f3460;}")
        self.menu_btn.setMenu(self._menu)
        hl.addWidget(self.menu_btn)
        hl.addStretch()

        self._menu_items = {}  # key -> QAction

        # ── Center: Title + device ID ───────────────────────
        center = QVBoxLayout()
        center.setSpacing(0)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addStretch()

        self.title_label = QLabel(cfg["app"]["title"])
        self.title_label.setStyleSheet("font-size:26px;font-weight:bold;color:#ffffff;")
        title_row.addWidget(self.title_label)

        self.device_label = QLabel(cfg["app"].get("device_id", "Pancake"))
        self.device_label.setStyleSheet("font-size:12px;color:#6080a0;")
        title_row.addWidget(self.device_label, alignment=Qt.AlignBottom)
        title_row.addStretch()
        center.addLayout(title_row)

        # ── Right ─────────────────────────────────────────
        right = QHBoxLayout()
        right.setSpacing(12)
        right.addStretch()

        # 地区（HMI 读取）
        self.region_label = QLabel("--")
        self.region_label.setStyleSheet("font-size:11px;color:#6080a0;")
        right.addWidget(self.region_label, alignment=Qt.AlignVCenter)

        weather_col = QVBoxLayout()
        weather_col.setSpacing(0)
        self.weather_icon = QLabel("☀")
        self.weather_icon.setStyleSheet("font-size:22px;")
        self.weather_temp = QLabel("--°")
        self.weather_temp.setStyleSheet("font-size:20px;color:#a0c0ff;")
        weather_col.addWidget(self.weather_icon, alignment=Qt.AlignCenter)
        weather_col.addWidget(self.weather_temp, alignment=Qt.AlignCenter)
        right.addLayout(weather_col)

        self.wifi_signal = WifiSignalWidget()
        right.addWidget(self.wifi_signal, alignment=Qt.AlignVCenter)

        time_col = QVBoxLayout()
        time_col.setSpacing(0)
        self.time_label = QLabel("00:00:00")
        self.time_label.setStyleSheet("font-size:20px;font-weight:bold;color:#ffffff;")
        self.date_label = QLabel("---")
        self.date_label.setStyleSheet("font-size:14px;color:#a0c0ff;")
        time_col.addWidget(self.time_label, alignment=Qt.AlignRight)
        time_col.addWidget(self.date_label, alignment=Qt.AlignRight)
        right.addLayout(time_col)

        # Assemble outer layout
        self._outer_layout.addWidget(self.home_left, 1)
        self._outer_layout.addWidget(self.sub_left, 1)
        self._outer_layout.addLayout(center, 0)
        self._outer_layout.addLayout(right, 1)

        # Default: home visible
        self.set_home_mode(True)
        self.set_device_visible(True)

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._clock.start(1000)
        self._tick()

    def set_home_mode(self, home: bool):
        """首页模式：显示电源/照明/相机/菜单，隐藏返回/温度"""
        self.home_left.setVisible(home)
        self.sub_left.setVisible(not home)
        self.set_device_visible(home)

    def set_device_visible(self, visible: bool):
        """设备编号仅首页显示"""
        self.device_label.setVisible(visible)

    def set_title(self, text):
        self.title_label.setText(text)

    def set_back_visible(self, visible):
        self.btn_back.setVisible(visible)

    def set_aodian_temp(self, val):
        """更新鏊面温度显示 D100"""
        if val is None:
            self.aodian_temp_label.setText("--.-°C")
        elif isinstance(val, (int, float)):
            self.aodian_temp_label.setText(f"{float(val):.1f}°C")
        else:
            self.aodian_temp_label.setText(f"{val}°C")

    def add_menu_item(self, key: str, label: str):
        """添加下拉菜单项"""
        if key in self._menu_items:
            return
        act = QAction(label, self)
        self._menu.addAction(act)
        self._menu_items[key] = act
        return act

    def menu_triggered(self):
        return self._menu

    def set_power(self, on: bool):
        """仅设置电源按钮 checked 状态（M44 开关机）"""
        self.power_btn.blockSignals(True)
        self.power_btn.setChecked(on)
        self.power_btn.blockSignals(False)

    def set_power_status(self, status: int):
        """D211 电源状态: 0=关机/1=运行/2=待机 → 改变 emoji 颜色"""
        colors = {0: "#e94560", 1: "#00c853", 2: "#ffc107"}
        color = colors.get(status, "#e94560")
        self.power_btn.set_emoji_color(color)
        self._power_status = status

    def set_light(self, on: bool):
        """照明按钮: 设 checked + 切换双态 emoji (💡 置位/🔅 复位)"""
        self.light_btn.blockSignals(True)
        self.light_btn.setChecked(on)
        self.light_btn.blockSignals(False)
        if on:
            self.light_btn.set_emoji("💡")
            self.light_btn.set_emoji_color("#ffcc00")
        else:
            self.light_btn.set_emoji("🔅")
            self.light_btn.set_emoji_color("#505060")

    def _tick(self):
        now = datetime.now()
        self.time_label.setText(now.strftime("%H:%M:%S"))
        WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]
        self.date_label.setText(f"{now.month:02d}/{now.day:02d} {WEEKDAYS[now.weekday()]}")

    def set_weather(self, icon, temp):
        self.weather_icon.setText(icon)
        self.weather_temp.setText(f"{temp}°")

    def set_wifi(self, ok):
        """外部设置WiFi状态: True=满格, False=无信号；或传入 -1 恢复自动读取"""
        if isinstance(ok, bool):
            self.wifi_signal.set_level(4 if ok else 0)
        elif isinstance(ok, int):
            self.wifi_signal.set_level(ok)

    def set_region(self, text: str):
        """设置地区（来自 HMI）"""
        self.region_label.setText(text if text else "--")

    def set_device_name(self, text: str):
        """设置设备名称（来自 HMI，替换默认 Pancake）"""
        self.device_label.setText(text if text else "")


# ═══════════════════════════════════════════════════════════
# Main Window
# ═══════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    # 桥接信号 — 通讯回调 → Qt 信号（线程安全）
    _signal_plc_data = Signal(dict)
    _signal_plc_point = Signal(str, object)
    _signal_hmi_data = Signal(dict)
    _signal_comm_error = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(cfg["app"]["title"])
        self.setStyleSheet(STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header (shared)
        self.header = HeaderBar()
        layout.addWidget(self.header)

        # Separator line — M50 控制颜色: 0=红, 1=绿
        self.separator = QFrame()
        self.separator.setFrameShape(QFrame.HLine)
        self.separator.setFixedHeight(4)
        self._set_separator_color(False)  # 默认红
        layout.addWidget(self.separator)

        # Page stack
        self.stack = QStackedWidget()
        self.pages = {}
        self._create_pages()
        layout.addWidget(self.stack, 1)

        # Navigation
        self.header.btn_back.clicked.connect(self._on_back)
        self._nav_stack = []  # 页面导航栈

        # ── Home header controls ──────────────────────────
        self.header.camera_btn.clicked.connect(lambda: self.go("vision"))
        self.header.power_btn.toggled.connect(self._on_power)
        self.header.light_btn.toggled.connect(self._on_light)

        # 下拉菜单项
        self.header.add_menu_item("help", "帮助")
        self.header.add_menu_item("alarms", "报警")
        self.header.add_menu_item("status", "状态")
        self.header.add_menu_item("about", "关于")
        self.header._menu.triggered.connect(self._on_menu)

        # ── 首页底部按钮 ──────────────────────────────────
        home = self.pages["home"]
        home.navigate.connect(self.go)
        home.plc_write.connect(self._on_home_plc_write)

        # Alarm popup signal
        for page in self.pages.values():
            if hasattr(page, 'alarm_triggered'):
                page.alarm_triggered.connect(self._show_alarm_popup)

        # Communication threads (TODO: wire real data)
        # Temporarily SIMPLIFIED: only PLC, isolate issue
        self._setup_comms_plc_only()

    def _setup_comms_plc_only(self):
        """PLC 通讯：QThread + PlcWorker（Qt 原生多线程）。

        UI 线程零阻塞 — 所有 Modbus IO 在独立 QThread，UI 只通过 Signal 通信。
        RK3588 8 核 — Qt 自动将 QThread 分配到不同核，无需手动设置亲缘性。
        """
        if PlcWorker is None or parse_snapshot is None:
            print("[UI] PLC worker/parse not available", file=sys.stderr)
            return

        try:
            # ── 创建 Worker（注入解析函数，Worker 线程内调用）──
            self._plc_worker = PlcWorker(
                cfg["plc"]["host"], cfg["plc"]["port"],
                parse_fn=parse_snapshot
            )
            self._plc_worker.set_read_config(build_read_configs())

            # ── QThread + moveToThread ──
            self._plc_thread = QThread()
            self._plc_worker.moveToThread(self._plc_thread)

            # ── 数据上行：Worker → UI ──
            # 跨线程信号自动 QueuedConnection，Worker emit → UI event loop
            self._plc_worker.data_updated.connect(self._on_plc_snapshot)
            self._plc_worker.connection_changed.connect(self._on_plc_connection)
            self._plc_worker.error_occurred.connect(
                lambda msg: print(f"[PLC] {msg}", file=sys.stderr))

            # ── 写入下行：UI emit Signal → Worker 槽 ──
            # Qt 检测到跨线程自动 QueuedConnection，槽在 Worker 线程执行
            self._plc_worker.write_coil_request.connect(
                self._plc_worker.write_coil)
            self._plc_worker.write_register_request.connect(
                self._plc_worker.write_register)

            # ── 启动 ──
            self._plc_thread.started.connect(self._plc_worker.start)
            self._plc_thread.start()

        except Exception as e:
            print(f"[UI] PLC init failed: {e}", file=sys.stderr)
            self._plc_worker = None
            self._plc_thread = None

        self.switch("home")
        if cfg["app"].get("fullscreen", True):
            # 嵌入式环境可能没有窗口管理器，showFullScreen 不生效
            # 手动设置窗口几何为屏幕尺寸 + 无边框
            screen = QApplication.primaryScreen()
            if screen:
                self.setGeometry(screen.geometry())
            self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
            self.showFullScreen()

    def _create_pages(self):
        def add(key, page):
            self.stack.addWidget(page)
            self.pages[key] = page
        add("home", HomePage())
        add("settings", SettingsPage())
        add("manual", ManualPage())
        add("vision", VisionPage())
        add("status", StatusPage())
        add("about", AboutPage())
        add("alarms", AlarmsPage())
        add("active_alarms", ActiveAlarmPage())

    def switch(self, key):
        if key not in self.pages:
            return
        # 标题映射
        titles = {
            "home": cfg["app"]["title"],
            "settings": "系统设置",
            "manual": "手动操作",
            "vision": "视觉",
            "status": "设备状态",
            "about": "关于",
            "alarms": "历史报警",
            "active_alarms": "实时报警",
        }
        is_home = (key == "home")
        self.header.set_title(titles.get(key, key))
        self.header.set_home_mode(is_home)
        self.header.set_back_visible(not is_home)
        self.header.aodian_temp_label.setVisible(True)
        self.stack.setCurrentWidget(self.pages[key])

    def go(self, key):
        """导航到页面并记录历史"""
        current = self.stack.currentWidget()
        for k, p in self.pages.items():
            if p is current:
                self._nav_stack.append(k)
                break
        self.switch(key)

    def _on_back(self):
        if self._nav_stack:
            prev = self._nav_stack.pop()
            self.switch(prev)

    def _on_power(self, on: bool):
        """电源开关 — emit 写入信号，Worker 线程执行 Modbus IO"""
        self._plc_write_point("m_rw_power", on)

    def _on_light(self, on: bool):
        """照明开关 — 即时视觉反馈 + emit 写入信号到 Worker 线程"""
        self.header.set_light(on)
        self._plc_write_point("m_rw_light", on)

    def _on_home_plc_write(self, name: str, value: bool):
        """首页按钮 → PLC 写入（通过信号投递到 Worker 线程）"""
        self._plc_write_point(name, value)

    def _plc_write_point(self, name: str, value):
        """桥接：点名称 → Modbus 地址 → emit 写入信号（主线程，微秒级）。

        仅做 dict 查询 + Signal.emit，绝不触碰 socket/pymodbus。
        实际 Modbus IO 由 PlcWorker 在其 QThread 中执行。
        """
        if self._plc_worker is None:
            return
        pt = POINTS.get(name)
        if pt is None:
            return
        if pt.region == 'M':
            self._plc_worker.write_coil_request.emit(
                mb_addr('M', pt.offset), bool(value))
        elif pt.region == 'D':
            self._plc_worker.write_register_request.emit(
                mb_addr('D', pt.offset), int(value))

    def _on_plc_connection(self, connected: bool):
        """PLC 连接状态变化回调"""
        if not connected:
            self.header.set_aodian_temp(None)  # 离线时清空温度显示

    def _on_plc_snapshot(self, snapshot: dict):
        """全局 PLC 快照回调"""
        # M50 许可 → 分线颜色
        permit = snapshot.get("m_ro_permit", False)
        self._set_separator_color(permit)
        # 电源按钮同步 (M44 toggle + D211 status color)
        power_state = snapshot.get("m_rw_power")
        if power_state is not None:
            self.header.set_power(bool(power_state))
        power_status = snapshot.get("d_ro_power_status")
        if power_status is not None:
            self.header.set_power_status(int(power_status))
        # 照明按钮同步
        light_on = snapshot.get("m_rw_light")
        if light_on is not None:
            self.header.set_light(bool(light_on))
        # 鏊面温度 D100 → 标题栏
        aodian_temp = snapshot.get("d_ro_aodian_temp")
        self.header.set_aodian_temp(aodian_temp)
        # 首页数据由 home.on_plc_data 统一处理（已通过 _signal_plc_data 连接）

    def _on_hmi_data(self, data: dict):
        """HMI 数据回调 → 更新标题栏"""
        # 设备名称
        device = data.get("device", "")
        if device:
            self.header.set_device_name(device)
        # 地区
        region = data.get("region", "")
        if region:
            self.header.set_region(region)
        # 天气
        weather = data.get("weather", "")
        temp = data.get("temp")
        if weather or temp is not None:
            icon = self._weather_icon(weather)
            temp_str = str(temp) if temp is not None else "--"
            self.header.set_weather(icon, temp_str)
        # 物联网信息 → 首页
        iot = data.get("iot", "")
        if iot:
            self.pages["home"].set_iot_info(iot)

    @staticmethod
    def _weather_icon(text: str) -> str:
        """天气文字 → emoji 图标"""
        t = (text or "").lower()
        if "晴" in t:
            return "☀"
        if "云" in t or "阴" in t:
            return "☁"
        if "雨" in t:
            return "🌧"
        if "雪" in t:
            return "❄"
        if "雾" in t or "霾" in t:
            return "🌫"
        if "风" in t:
            return "💨"
        return "☀"  # 默认晴天

    def _set_separator_color(self, green: bool):
        """M50=0 红色, M50=1 绿色"""
        color = "#00c853" if green else "#e94560"
        self.separator.setStyleSheet(
            f"QFrame{{color:{color};border:4px solid {color};}}")

    def _on_menu(self, action):
        """下拉菜单导航"""
        for key, act in self.header._menu_items.items():
            if act is action:
                if key == "help":
                    self.go("about")
                else:
                    self.go(key)
                return

    def _show_alarm_popup(self, level, message):
        popup = AlarmPopup(level, message, self)
        popup.exec()
        # Also log to history
        alarms_page = self.pages.get("alarms")
        if alarms_page:
            alarms_page.add_alarm(level, "系统", message)

    def _setup_comms(self):
        """通信层线程 —— 初始化失败不影响 UI 启动
        桥接模式：通讯回调 → Qt 信号 → UI 页面
        """
        import threading
        try:
            from core.plc import DeltaPLC
            from core.serial_devices import SerialDeviceController
            from core.hmi import KunlunHMI
        except ImportError as e:
            print(f"[UI] Comms import failed: {e}", file=sys.stderr)
            return

        try:
            self.plc = DeltaPLC(cfg["plc"]["host"], cfg["plc"]["port"])
        except Exception as e:
            print(f"[UI] PLC init failed: {e}", file=sys.stderr)
            self.plc = None

        try:
            self.hmi = KunlunHMI(cfg["hmi"]["host"], cfg["hmi"]["port"])
        except Exception as e:
            print(f"[UI] HMI init failed: {e}", file=sys.stderr)
            self.hmi = None

        try:
            self.serial1 = SerialDeviceController(cfg["serial"]["port"], 1)
        except Exception as e:
            print(f"[UI] Serial1 init failed: {e}", file=sys.stderr)
            self.serial1 = None

        try:
            self.serial2 = SerialDeviceController(cfg["serial"]["port"], 2)
        except Exception as e:
            print(f"[UI] Serial2 init failed: {e}", file=sys.stderr)
            self.serial2 = None

        # ── 桥接：通讯回调 → Qt 信号 ────────────────────────
        if self.plc:
            self.plc.configure_polling()
            self.plc.start()
            self.plc.on('data_updated', lambda d: self._signal_plc_data.emit(d))
            self.plc.on('point_changed', lambda n, v: self._signal_plc_point.emit(n, v))
            self._signal_plc_data.connect(self.pages["home"].on_plc_data, Qt.QueuedConnection)
            self._signal_plc_data.connect(self._on_plc_snapshot, Qt.QueuedConnection)
            threading.Thread(target=self.plc.run, daemon=True,
                           name="plc-chain").start()

        if self.hmi:
            self.hmi.configure_polling()
            self.hmi.start()
            self.hmi.on('data_updated', lambda d: self._signal_hmi_data.emit(d))
            self._signal_hmi_data.connect(self._on_hmi_data, Qt.QueuedConnection)
            threading.Thread(target=self.hmi.run, daemon=True,
                           name="hmi-chain").start()

        if self.serial1:
            self.serial1.configure_polling()
            self.serial1.start()
            threading.Thread(target=self.serial1.run, daemon=True,
                           name="serial1-chain").start()

        if self.serial2:
            self.serial2.configure_polling()
            self.serial2.start()
            threading.Thread(target=self.serial2.run, daemon=True,
                           name="serial2-chain").start()

    def closeEvent(self, event):
        # 停止 PLC Worker + QThread
        if hasattr(self, '_plc_worker') and self._plc_worker:
            self._plc_worker.stop()
        if hasattr(self, '_plc_thread') and self._plc_thread:
            self._plc_thread.quit()
            self._plc_thread.wait(3000)
        # 停止旧式通讯对象（HMI / 串口）
        for attr in ('hmi', 'serial1', 'serial2'):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    obj.disconnect()
                except Exception:
                    pass
        event.accept()


# ═══════════════════════════════════════════════════════════
def main():
    import os, traceback

    # 全局异常处理 —— 不让任何未捕获异常导致 UI 退出
    def _excepthook(exc_type, exc_value, exc_tb):
        try:
            msg = f"[UI FATAL] {exc_type.__name__}: {exc_value}"
        except Exception:
            msg = "[UI FATAL] <unprintable error>"
        print(msg, file=sys.stderr, flush=True)
    sys.excepthook = _excepthook

    # ── 平台选择：xcb 优先（Xorg + xrandr 旋转 DSI）──
    platform = os.environ.get("QT_QPA_PLATFORM", "xcb")
    print(f"[UI] Using platform: {platform}", file=sys.stderr, flush=True)

    os.environ["QT_QPA_PLATFORM"] = platform

    try:
        app = QApplication(sys.argv)
    except Exception as e:
        print(f"[UI] QApplication failed with {platform}: {e}", file=sys.stderr, flush=True)
        # 回退到 xcb
        if platform != "xcb":
            print("[UI] Falling back to xcb...", file=sys.stderr, flush=True)
            os.environ["QT_QPA_PLATFORM"] = "xcb"
            try:
                app = QApplication(sys.argv)
            except Exception as e2:
                print(f"[UI] xcb fallback also failed: {e2}", file=sys.stderr, flush=True)
                sys.exit(1)
        else:
            sys.exit(1)

    try:
        window = MainWindow()
        window.show()
    except Exception as e:
        print(f"[UI] MainWindow init failed: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
