"""
首页 — 横屏 1280×800，3 栏布局 + 底部 6 按钮行。

栏位：
  左栏：纯电源（状态指示灯 + 三相电压/电流/功率/累计电能/当天电能）
  中栏：物联网信息（设备名/地区/天气/温度/版本，居中）
  右栏：产量（产能/本批/目标/今天/累计）+ 电机位置 7 个（eng 工程值）
下栏：手动、设置、复位、烤盘、加热、启动
"""

from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QFrame, QSizePolicy, QScrollArea,
)
from PySide6.QtCore import Qt, Signal
from ui.widgets.base_page import BasePage

# ── 样式 ──────────────────────────────────────────────────

BTN_BOTTOM = (
    "QPushButton{"
    "font-size:18px;font-weight:bold;color:#e0e0e0;"
    "background:#16213e;border:2px solid #0f3460;"
    "border-radius:10px;padding:14px 0;"
    "}"
    "QPushButton:hover{background:#0f3460;border-color:#e94560;}"
    "QPushButton:pressed{background:#0a0a1e;}"
    "QPushButton:checked{background:#00c853;color:#000;border-color:#00c853;}"
)

BTN_NAV = (
    "QPushButton{"
    "font-size:18px;font-weight:bold;color:#e0e0e0;"
    "background:#16213e;border:2px solid #0f3460;"
    "border-radius:10px;padding:14px 0;"
    "}"
    "QPushButton:hover{background:#0f3460;border-color:#e94560;}"
    "QPushButton:pressed{background:#0a0a1e;}"
)

SECTION_TITLE_STYLE = (
    "font-size:16px;font-weight:bold;color:#e94560;"
    "border-bottom:2px solid #0f3460;padding-bottom:4px;margin-bottom:4px;"
)

CARD_STYLE = (
    "QFrame#compactCard{"
    "background:#16213e;border-radius:6px;padding:6px 8px;"
    "border:1px solid #0f3460;"
    "}"
)

MOTOR_ROW_STYLE = (
    "QFrame#motorRow{"
    "background:#16213e;border-radius:4px;padding:2px 8px;"
    "border:1px solid #0f3460;"
    "}"
)


# ── 紧凑卡片 ──────────────────────────────────────────────

class CompactCard(QFrame):
    """紧凑数据卡片：标签 + 值 + 单位 单行"""

    def __init__(self, title: str, unit: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("compactCard")
        self.setStyleSheet(CARD_STYLE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(28)

        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(6, 2, 6, 2)
        hbox.setSpacing(4)

        self._title = QLabel(f"{title}:")
        self._title.setStyleSheet("font-size:11px;color:#6080a0;")
        hbox.addWidget(self._title)

        self._value = QLabel("--")
        self._value.setStyleSheet("font-size:13px;font-weight:bold;color:#ffffff;")
        hbox.addWidget(self._value)

        self._unit = QLabel(unit)
        self._unit.setStyleSheet("font-size:10px;color:#6080a0;")
        self._unit.setAlignment(Qt.AlignBottom)
        hbox.addWidget(self._unit)

        hbox.addStretch()

    def set_value(self, value):
        if isinstance(value, float):
            self._value.setText(f"{value:.1f}")
        else:
            self._value.setText(str(value))

    def set_unit(self, unit: str):
        self._unit.setText(unit)


# ── 电机位置行 ────────────────────────────────────────────

class MotorRow(QFrame):
    """电机位置：名称: 工程值 单位 紧凑单行"""

    def __init__(self, name: str, unit: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("motorRow")
        self.setStyleSheet(MOTOR_ROW_STYLE)
        self.setFixedHeight(28)

        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(6, 0, 6, 0)
        hbox.setSpacing(2)

        self._name = QLabel(f"{name}:")
        self._name.setStyleSheet("font-size:11px;color:#6080a0;")
        hbox.addWidget(self._name)

        self._value = QLabel("-")
        self._value.setStyleSheet("font-size:12px;font-weight:bold;color:#ffffff;")
        hbox.addWidget(self._value)

        self._unit = QLabel(unit)
        self._unit.setStyleSheet("font-size:10px;color:#6080a0;")
        self._unit.setAlignment(Qt.AlignBottom)
        self._unit.setMinimumWidth(20)
        hbox.addWidget(self._unit)

        hbox.addStretch()

    def set_value(self, value):
        if value is None:
            self._value.setText("-")
        elif isinstance(value, float):
            self._value.setText(f"{value:.1f}")
        else:
            self._value.setText(str(value))


# ── 栏标题 ────────────────────────────────────────────────

class SectionTitle(QLabel):
    """栏标题：红色下划线"""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(SECTION_TITLE_STYLE)


# ═══════════════════════════════════════════════════════════
# HomePage
# ═══════════════════════════════════════════════════════════

class HomePage(BasePage):
    """首页：3 栏内容区 + 底部 6 按钮"""

    navigate = Signal(str)               # 跳转页面 key
    plc_write = Signal(str, bool)        # (point_name, value)

    def __init__(self):
        super().__init__("")
        self.title_label.hide()

        # 数据卡片引用（PLC 更新）—— 必须在 build 之前初始化
        self._power_status = None   # QLabel: 电源状态指示灯
        self._power_labels = {}     # key -> QLabel (电气参数值)
        self._prod_cards = {}       # name -> CompactCard
        self._motor_rows = {}       # name -> MotorRow
        self._iot_label = None      # QLabel: 物联网信息
        self._status_label = None   # QLabel: 设备状态 D0
        self._aodian_temp_label = None  # QLabel: 鏊面温度 D100

        # ── 3 栏内容区 ────────────────────────────────────
        cols = QHBoxLayout()
        cols.setContentsMargins(4, 4, 4, 4)
        cols.setSpacing(6)

        cols.addLayout(self._build_left_col(), 1)
        cols.addLayout(self._build_center_col(), 2)
        cols.addLayout(self._build_right_col(), 1)

        self.content_layout.addLayout(cols, 1)

        # ── 底部按钮行 ────────────────────────────────────
        self.content_layout.addLayout(self._build_bottom_bar())

        # 按钮引用（PLC 状态同步）
        self._toggles = {
            "m_rw_reset": self.btn_reset,
            "m_rw_bake":  self.btn_bake,
            "m_rw_heat":  self.btn_heat,
            "m_rw_start": self.btn_start,
        }

    # ── 左栏：电源 ────────────────────────────────────────

    def _build_left_col(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        # 标题行：图标 + 电源状态指示灯
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(SectionTitle("🔌 电源"))
        title_row.addStretch()
        self._power_status = QLabel("●")
        self._power_status.setStyleSheet(
            "font-size:18px;color:#e94560;font-weight:bold;"
        )
        self._power_status.setToolTip("电源状态: 0关/1开/2待机")
        title_row.addWidget(self._power_status)
        layout.addLayout(title_row)

        # 三列网格容器
        grid_frame = QFrame()
        grid_frame.setStyleSheet(
            "QFrame#powerGrid{background:#16213e;border-radius:6px;"
            "border:1px solid #0f3460;padding:4px;}"
        )
        grid_frame.setObjectName("powerGrid")
        grid = QVBoxLayout(grid_frame)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setSpacing(2)

        # 电压电流竖排 6 行（每相独占一行）
        def _add_single_row(label_text, var_key, unit_text, label_width=36):
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-size:11px;color:#6080a0;")
            lbl.setFixedWidth(label_width)
            row.addWidget(lbl)
            val_label = QLabel("-")
            val_label.setStyleSheet(
                "font-size:13px;font-weight:bold;color:#ffffff;"
            )
            val_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val_label.setMinimumWidth(70)
            row.addWidget(val_label)
            self._power_labels[var_key] = val_label
            unit_lbl = QLabel(unit_text)
            unit_lbl.setStyleSheet("font-size:10px;color:#506080;")
            unit_lbl.setAlignment(Qt.AlignBottom)
            unit_lbl.setFixedWidth(20)
            row.addWidget(unit_lbl)
            row.addStretch()
            grid.addLayout(row)

        for ph, label in [("a", "电压A"), ("b", "电压B"), ("c", "电压C")]:
            _add_single_row(label, f"voltage_{ph}", "V")
        for ph, label in [("a", "电流A"), ("b", "电流B"), ("c", "电流C")]:
            _add_single_row(label, f"current_{ph}", "A")

        # 功率/电能合计行
        for pfx, label_text, unit_text in [
            ("power", "功率", "W"),
            ("total_energy", "累计电能", "kWh"),
            ("today_energy", "当天电能", "kWh"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-size:11px;color:#6080a0;")
            lbl.setFixedWidth(52)
            row.addWidget(lbl)
            val_label = QLabel("-")
            val_label.setStyleSheet(
                "font-size:13px;font-weight:bold;color:#ffffff;"
            )
            val_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val_label.setMinimumWidth(70)
            row.addWidget(val_label)
            unit_lbl = QLabel(unit_text)
            unit_lbl.setStyleSheet("font-size:10px;color:#506080;")
            unit_lbl.setAlignment(Qt.AlignBottom)
            row.addWidget(unit_lbl)
            row.addStretch()
            grid.addLayout(row)
            self._power_labels[pfx] = val_label

        layout.addWidget(grid_frame)
        layout.addStretch()
        return layout

    # ── 中栏：物联网 + 设备状态 + 鏊面温度（居中） ────────

    def _build_center_col(self):
        """中栏：IoT信息 / 设备状态(D0) / 鏊面温度(D100)"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── a) 物联网信息（来自 HMI） ─────────────────────
        iot_title = SectionTitle("🌐 物联网信息")
        iot_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(iot_title)

        self._iot_label = QLabel("设备: --\n地区: --\n天气: --\n温度: --\n版本: --")
        self._iot_label.setStyleSheet(
            "font-size:13px;color:#a0c0ff;background:#16213e;"
            "border-radius:8px;padding:10px;"
        )
        self._iot_label.setWordWrap(True)
        self._iot_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._iot_label)

        layout.addSpacing(4)

        # ── b) 设备状态 D0（16位枚举） ───────────────────
        status_title = SectionTitle("📋 设备状态")
        status_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(status_title)

        self._status_label = QLabel("--")
        self._status_label.setStyleSheet(
            "font-size:20px;font-weight:bold;color:#ffffff;"
            "background:#16213e;border-radius:8px;padding:12px;"
        )
        self._status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._status_label)

        layout.addSpacing(4)

        # ── c) 鏊面温度 D100（浮点） ─────────────────────
        temp_title = SectionTitle("🌡 鏊面温度")
        temp_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(temp_title)

        self._aodian_temp_label = QLabel("--.-°C")
        self._aodian_temp_label.setStyleSheet(
            "font-size:24px;font-weight:bold;color:#ff6b35;"
            "background:#16213e;border-radius:8px;padding:14px;"
        )
        self._aodian_temp_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._aodian_temp_label)

        layout.addStretch()
        return layout

    # ── 右栏：产量 + 电机位置（合并一列） ──────────────────

    def _build_right_col(self):
        """右栏：上半产量 + 下半电机位置"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        # 产量
        layout.addWidget(SectionTitle("📊 产量"))

        prod_items = [
            ("产能",     "", "capacity"),
            ("本批生产", "", "batch_prod"),
            ("目标生产", "", "target_prod"),
            ("今天生产", "", "today_prod"),
            ("累计生产", "", "total_prod"),
        ]
        for name, unit, key in prod_items:
            card = CompactCard(name, unit)
            self._prod_cards[key] = card
            layout.addWidget(card)

        layout.addSpacing(6)

        # 电机位置
        layout.addWidget(SectionTitle("🔧 电机位置"))
        motors = [
            ("鏊面",  "°",  "aodian"),
            ("刮板",  "°",  "scraper"),
            ("升降",  "mm", "rise"),
            ("抹油",  "mm", "oil"),
            ("揭皮",  "mm", "peel"),
            ("料泵1", "L",  "feed1"),
            ("料泵2", "L",  "feed2"),
        ]
        for name, unit, key in motors:
            row = MotorRow(name, unit)
            self._motor_rows[key] = row
            layout.addWidget(row)

        layout.addStretch()
        return layout

    # ── 底部按钮 ──────────────────────────────────────────

    def _build_bottom_bar(self):
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 4, 0, 4)
        bar.setSpacing(8)

        # 手动
        self.btn_manual = QPushButton("🛠 手动")
        self.btn_manual.setStyleSheet(BTN_NAV)
        self.btn_manual.clicked.connect(lambda: self.navigate.emit("manual"))
        bar.addWidget(self.btn_manual, 1)

        # 设置
        self.btn_settings = QPushButton("⚙ 设置")
        self.btn_settings.setStyleSheet(BTN_NAV)
        self.btn_settings.clicked.connect(lambda: self.navigate.emit("settings"))
        bar.addWidget(self.btn_settings, 1)

        # 复位
        self.btn_reset = QPushButton("↺ 复位")
        self.btn_reset.setCheckable(True)
        self.btn_reset.setStyleSheet(BTN_BOTTOM)
        self.btn_reset.toggled.connect(lambda v: self.plc_write.emit("m_rw_reset", v))
        bar.addWidget(self.btn_reset, 1)

        # 烤盘
        self.btn_bake = QPushButton("🔥 烤盘")
        self.btn_bake.setCheckable(True)
        self.btn_bake.setStyleSheet(BTN_BOTTOM)
        self.btn_bake.toggled.connect(lambda v: self.plc_write.emit("m_rw_bake", v))
        bar.addWidget(self.btn_bake, 1)

        # 加热
        self.btn_heat = QPushButton("🌡 加热")
        self.btn_heat.setCheckable(True)
        self.btn_heat.setStyleSheet(BTN_BOTTOM)
        self.btn_heat.toggled.connect(lambda v: self.plc_write.emit("m_rw_heat", v))
        bar.addWidget(self.btn_heat, 1)

        # 启动
        self.btn_start = QPushButton("▶ 启动")
        self.btn_start.setCheckable(True)
        self.btn_start.setStyleSheet(BTN_BOTTOM)
        self.btn_start.toggled.connect(lambda v: self.plc_write.emit("m_rw_start", v))
        bar.addWidget(self.btn_start, 1)

        return bar

    # ── 数据更新 ──────────────────────────────────────────

    def set_iot_info(self, text: str):
        self._iot_label.setText(text)

    def on_plc_data(self, snapshot: dict):
        """接收 PLC 快照，更新全部首页数据"""
        # ── 按钮状态 ──────────────────────────────────────
        for name, btn in self._toggles.items():
            val = snapshot.get(name)
            if val is not None:
                btn.blockSignals(True)
                btn.setChecked(bool(val))
                btn.blockSignals(False)

        # ── 电源状态指示灯 ────────────────────────────────
        if self._power_status is not None:
            status = snapshot.get("d_ro_power_status")
            if status is not None:
                color_map = {0: "#e94560", 1: "#00c853", 2: "#ffc107"}
                text_map = {0: "● 关机", 1: "● 运行", 2: "● 待机"}
                color = color_map.get(int(status), "#e94560")
                text = text_map.get(int(status), "●")
                self._power_status.setText(text)
                self._power_status.setStyleSheet(
                    f"font-size:18px;color:{color};font-weight:bold;"
                )

        # ── 电气参数 ──────────────────────────────────────
        _fmt1 = lambda v: f"{float(v):.1f}" if v is not None else "-"

        # 三相电压 A/B/C
        for ph in ("a", "b", "c"):
            key = f"d_ro_voltage_{ph}"
            lbl = self._power_labels.get(f"voltage_{ph}")
            if lbl is not None:
                val = snapshot.get(key)
                lbl.setText(_fmt1(val))

        # 三相电流 A/B/C
        for ph in ("a", "b", "c"):
            key = f"d_ro_current_{ph}"
            lbl = self._power_labels.get(f"current_{ph}")
            if lbl is not None:
                val = snapshot.get(key)
                lbl.setText(_fmt1(val))

        # 功率
        lbl = self._power_labels.get("power")
        if lbl is not None:
            lbl.setText(_fmt1(snapshot.get("d_ro_power")))

        # 累计电能
        lbl = self._power_labels.get("total_energy")
        if lbl is not None:
            lbl.setText(_fmt1(snapshot.get("d_ro_total_energy")))

        # 当天电能
        lbl = self._power_labels.get("today_energy")
        if lbl is not None:
            lbl.setText(_fmt1(snapshot.get("d_ro_today_energy")))

        # ── 产量 ──────────────────────────────────────────
        prod_map = {
            "capacity":    "d_ro_capacity",
            "batch_prod":  "d_rw_batch_prod",
            "target_prod": "d_rw_target_prod",
            "today_prod":  "d_ro_today_prod",
            "total_prod":  "d_ro_total_prod",
        }
        for card_key, plc_key in prod_map.items():
            card = self._prod_cards.get(card_key)
            if card is not None:
                val = snapshot.get(plc_key)
                if val is not None:
                    if plc_key in ("d_rw_batch_prod", "d_rw_target_prod",
                                   "d_ro_today_prod", "d_ro_total_prod"):
                        card.set_value(int(val))
                    else:
                        card.set_value(val)

        # ── 电机位置（eng 工程值） ────────────────────────
        motor_map = {
            "scraper": "sr_ro_scraper_pos_eng",
            "rise":    "sr_ro_rise_pos_eng",
            "oil":     "sr_ro_oil_pos_eng",
            "peel":    "sr_ro_peel_pos_eng",
            "feed1":   "sr_ro_feed1_pos_eng",
            "feed2":   "sr_ro_feed2_pos_eng",
            "aodian":  "d_ro_aodian_pos",
        }
        for row_key, plc_key in motor_map.items():
            row = self._motor_rows.get(row_key)
            if row is not None:
                val = snapshot.get(plc_key)
                if val is not None:
                    row.set_value(val)

        # ── 设备状态 D0 ──────────────────────────────────
        if self._status_label is not None:
            status = snapshot.get("d_ro_status")
            if status is not None:
                self._status_label.setText(str(status))

        # ── 鏊面温度 D100 ────────────────────────────────
        if self._aodian_temp_label is not None:
            temp = snapshot.get("d_ro_aodian_temp")
            if temp is None:
                self._aodian_temp_label.setText("--.-°C")
            elif isinstance(temp, (int, float)):
                self._aodian_temp_label.setText(f"{float(temp):.1f}°C")
            else:
                self._aodian_temp_label.setText(f"{temp}°C")
