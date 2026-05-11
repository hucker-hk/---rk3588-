"""
台达 AS 系列 PLC — Modbus TCP 适配器 (v2)

地址映射：
  X:  Discrete Input     基址 0x0400 (1024)  只读
  Y:  Coil               基址 0x0500 (1280)  只读（监控输出）
  M:  Coil               基址 0x0800 (2048)  读写（M50只读）
  SR: Holding Register   基址 0x0000 (0)     只读（32位整数）
  D:  Holding Register   基址 0x1000 (4096)  读写

命名规范: <区域>_<rw>_<名称>
  rw = 读写, ro = 只读
"""

from dataclasses import dataclass
from typing import Union, Optional
import socket
import struct
import threading
import time

from .request_chain import RequestChain
from pymodbus.client import ModbusTcpClient

# ── 点位表 ─────────────────────────────────────────────────

@dataclass
class Point:
    """PLC 点位定义"""
    name: str           # 变量名
    region: str         # X / Y / M / SR / D
    offset: int         # 区域内偏移
    access: str         # 'ro' 只读 / 'rw' 读写
    desc: str           # 中文描述
    bits: Union[int, str] = 16    # 位宽: 16(默认) / 32 / 'float'
    raw_min: Optional[int] = None      # 工程转换：raw 最小值
    raw_max: Optional[int] = None      # 工程转换：raw 最大值
    eng_scale: Optional[float] = None  # 工程转换：比例因子
    eng_unit: str = ''                 # 工程转换：单位

# X 输入（只读）
X_POINTS = [
    ("x_ro_scraper_home",  0x00, "刮板原点"),
    ("x_ro_rise_limit",    0x01, "上升限位"),
    ("x_ro_fall_limit",    0x02, "下降限位"),
    ("x_ro_oil_home",      0x03, "抹油原点"),
    ("x_ro_oil_fwd_limit", 0x04, "抹油前限"),
]

# Y 输出（只读监控）
Y_POINTS = [
    ("y_ro_stir1",        0x0F, "搅拌1"),       # Y0.15
    ("y_ro_oil_pump_out", 0x14, "油泵外"),       # Y1.4
    ("y_ro_oil_pump_mid", 0x15, "油泵中"),       # Y1.5
    ("y_ro_oil_pump_in",  0x16, "油泵内"),       # Y1.6
    ("y_ro_stir2",        0x17, "搅拌2"),        # Y1.7
]

# M 继电器（读写，标注例外）
M_POINTS = [
    # 手动页 — 读写
    ("m_rw_manual",         0,  "手动"),
    ("m_rw_turntable_ccw",  1,  "手动转盘逆转"),
    ("m_rw_turntable_cw",   2,  "手动转盘顺转"),
    ("m_rw_scraper_ccw",    3,  "手动刮板逆转"),
    ("m_rw_scraper_cw",     4,  "手动刮板顺转"),
    ("m_rw_rise",           5,  "手动上升"),
    ("m_rw_fall",           6,  "手动下降"),
    ("m_rw_oil_fwd",        7,  "手动抹油前进"),
    ("m_rw_oil_back",       8,  "手动抹油后退"),
    ("m_rw_peel_fwd",       9,  "手动揭皮前进"),
    ("m_rw_peel_back",      10, "手动揭皮后退"),
    ("m_rw_feed1",          11, "手动打料1"),
    ("m_rw_back1",          12, "手动回料1"),
    ("m_rw_feed2",          13, "手动打料2"),
    ("m_rw_back2",          14, "手动回料2"),
    # 手动页 — 读写（续）
    ("m_rw_heat_cool",      30, "手动加热冷却"),
    ("m_rw_prod_cool",      31, "手动生产冷却"),
    ("m_rw_stir1_manual",   32, "手动搅拌1"),
    ("m_rw_sterilize",      33, "手动杀菌"),
    ("m_rw_oil_pump_out_m", 34, "手动油泵外"),
    ("m_rw_oil_pump_mid_m", 35, "手动油泵中"),
    ("m_rw_oil_pump_in_m",  36, "手动油泵内"),
    ("m_rw_stir2_manual",   37, "手动搅拌2"),
    # 首页 — 读写
    ("m_rw_reset",          40, "复位"),
    ("m_rw_start",          41, "启动"),
    ("m_rw_heat",           42, "加热"),
    ("m_rw_light",          43, "照明"),
    ("m_rw_power",          44, "开机"),
    ("m_rw_idle",           45, "空转"),
    ("m_rw_feed1_home",     46, "打料1"),
    ("m_rw_back1_home",     47, "回抽1"),
    ("m_rw_feed2_home",     48, "打料2"),
    ("m_rw_back2_home",     49, "回抽2"),
    # 其他 — 读写
    ("m_rw_offline",        51, "脱机"),
    ("m_rw_bake",           52, "烤盘"),
    ("m_rw_motor_reset",    53, "电机复位"),
    ("m_rw_heat_manual",    54, "手动加热"),
]

# M 继电器 — 只读
M_RO_POINTS = [
    ("m_ro_permit",         50, "许可"),
]

# SR 系统寄存器（只读，32位）
SR_POINTS = [
    ("sr_ro_scraper_pos",   480, "刮板电机实际位置", -1000000, 1000000, 0.036, '°'),
    ("sr_ro_rise_pos",      500, "升降电机实际位置", -100000, 100000, 0.0005, 'mm'),
    ("sr_ro_oil_pos",       520, "抹油电机实际位置", -100000, 100000, 0.009, 'mm'),
    ("sr_ro_peel_pos",      540, "揭皮电机实际位置", -10000000, 10000000, 0.01, 'mm'),
    ("sr_ro_feed1_pos",     560, "料泵1电机实际位置", -10000000, 10000000, 0.0000517, 'L'),
    ("sr_ro_feed2_pos",     574, "料泵2电机实际位置", -10000000, 10000000, 0.0000517, 'L'),
]

# ── Modbus 地址 ────────────────────────────────────────────

ADDR = {
    'X':  0x6000,
    'Y':  0xA000,
    'M':  0x0000,
    'D':  0x0000,
    'SR': 0xC000,
}

def mb_addr(region: str, offset: int) -> int:
    """Modbus 绝对地址"""
    return ADDR[region] + offset

# ── 构建点位索引 ───────────────────────────────────────────

def _build_points():
    """构建完整的点位字典"""
    pts = {}
    for name, off, desc in X_POINTS:
        pts[name] = Point(name, 'X', off, 'ro', desc, bits=1)
    for name, off, desc in Y_POINTS:
        pts[name] = Point(name, 'Y', off, 'ro', desc, bits=1)
    for name, off, desc in M_POINTS:
        pts[name] = Point(name, 'M', off, 'rw', desc, bits=1)
    for name, off, desc in M_RO_POINTS:
        pts[name] = Point(name, 'M', off, 'ro', desc, bits=1)
    for name, off, desc, raw_min, raw_max, eng_scale, eng_unit in SR_POINTS:
        pts[name] = Point(name, 'SR', off, 'ro', desc, bits=32,
                          raw_min=raw_min, raw_max=raw_max,
                          eng_scale=eng_scale, eng_unit=eng_unit)
    # D 只读点位
    for name, entry in D_POINTS.items():
        grp_name = entry[0]
        off_in_grp = entry[1]
        desc = entry[2]
        bits = entry[3] if len(entry) > 3 else 16
        pts[name] = Point(name, 'D', off_in_grp, 'ro', desc, bits=bits)
    # D 只写点位
    for name, off, desc, unit in D_WO_POINTS:
        pts[name] = Point(name, 'D', off, 'rw', desc, bits=16, eng_unit=unit)
    # D 读写点位（断电保持）
    for name, off, desc, bits, eng_scale, eng_unit, _default in D_RW_POINTS:
        pts[name] = Point(name, 'D', off, 'rw', desc, bits=bits,
                          eng_scale=eng_scale, eng_unit=eng_unit)
    return pts

# ── 需要轮询的范围 ─────────────────────────────────────────
X_READ_COUNT = 5       # X0.0 - X0.4
Y_READ_COUNT = 24      # Y0.0 - Y1.7 (24 bits)
M_READ_COUNT = 55      # M0 - M54
SR_START     = 480
SR_COUNT     = 96      # SR480 - SR575

# D 寄存器分组轮询（相邻寄存器合并一次读）
D_GROUPS = [
    ('d_grp_0_6',     0,    7),   # D0-D6 状态信息(16位)
    ('d_grp_12',      12,   2),   # D12-D13 鏊电机位置(32位)
    ('d_grp_22',      22,   2),   # D22 浮点(32位=2寄存器)
    ('d_grp_50_58',   50,   10),  # D50-D59 设置参数(32位各2寄存器=实际10个)
    ('d_grp_68_70',   68,   4),   # D68-D71 揭皮参数(32位各2)
    ('d_grp_100_102', 100,  4),   # D100-D103 浮点(各2寄存器)
    ('d_grp_110_112', 110,  3),   # D110-D112 烤盘风扇转速(16位)
    ('d_grp_120_124', 120,  3),   # D120-D122 烤盘温度(16位, 留D124空间)
    ('d_grp_211',     211,  1),   # D211 开机状态(16位)
    ('d_grp_220_238', 220,  20),  # D220-D239 电气浮点(各2寄存器)
    ('d_grp_244_248', 244,  5),   # D244-D248 扭矩报警(16位)
    # 断电保持寄存器组 D20000-D21012
    ('d_grp_20000_20012', 20000, 14),  # D20000-D20013 手动速度(7×32bit)
    ('d_grp_20020_20022', 20020, 4),   # D20020-D20023 设置参数
    ('d_grp_20030_20046', 20030, 18),  # D20030-D20047 工艺参数1a(9×32bit)
    ('d_grp_20048_20054', 20048, 8),   # D20048-D20055 工艺参数1b(4×32bit)
    ('d_grp_20060_20072', 20060, 14),  # D20060-D20073 工艺参数2
    ('d_grp_20080_20087', 20080, 8),   # D20080-D20087 时间参数(8×16bit)
    ('d_grp_20090_20097', 20090, 9),   # D20090-D20098 输出参数(9×16bit)
    ('d_grp_20100_20106', 20100, 8),   # D20100-D20107 温度设定(4×float)
    ('d_grp_20114_20116', 20114, 4),   # D20114-D20117 温度设定续(2×float)
    ('d_grp_prod_timer', 20120, 24),   # D20120-D20143 生产/计时(12×32bit)
    ('d_grp_20150_20162', 20150, 14),  # D20150-D20163 配方2(7×32bit)
    ('d_grp_20220_20222', 20220, 4),   # D20220-D20223 生产目标(2×32bit)
    ('d_grp_21002_21012', 21002, 12),  # D21002-D21013 PID(含gap)
]

# D 点位定义 (name, group_name, offset_in_group, desc, bits=None)
# bits: None=16位默认, 32=32位整数, 'float'=32位浮点
D_POINTS = {
    # D0-D6 状态
    'd_ro_status':        ('d_grp_0_6',   0, '状态信息'),
    'd_ro_bg_color':      ('d_grp_0_6',   3, '背景颜色'),
    'd_ro_fault_x':       ('d_grp_0_6',   4, '故障X'),
    'd_ro_fault_motor':   ('d_grp_0_6',   5, '故障电机'),
    'd_ro_fault_modbus':  ('d_grp_0_6',   6, '故障Modbus'),
    # D12 鏊电机位置(32位)
    'd_ro_aodian_pos':    ('d_grp_12',    0, '鏊电机实际位置', 32),
    # D22 产能(浮点=32位)
    'd_ro_capacity':      ('d_grp_22',    0, '产能', 'float'),
    # D50-D58 设置(32位)
    'd_ro_oil_pos1':      ('d_grp_50_58', 0, '抹油位置1', 32),
    'd_ro_oil_pos2':      ('d_grp_50_58', 2, '抹油位置2', 32),
    'd_ro_oil_speed':     ('d_grp_50_58', 4, '抹油速度', 32),
    'd_ro_oil_idle_pos':  ('d_grp_50_58', 6, '抹油空转位置', 32),
    'd_ro_oil_idle_speed':('d_grp_50_58', 8, '抹油空转速度', 32),
    # D68-D70 揭皮(32位)
    'd_ro_peel_speed':      ('d_grp_68_70', 0, '揭皮速度', 32),
    'd_ro_peel_idle_speed': ('d_grp_68_70', 2, '揭皮空转速度', 32),
    # D100-D102 浮点
    'd_ro_aodian_temp':  ('d_grp_100_102', 0, '鏊面温度', 'float'),
    'd_ro_heat_output':  ('d_grp_100_102', 2, '加热输出', 'float'),
    # D110-D112 烤盘风扇(16位)
    'd_ro_bake_fan_speed1': ('d_grp_110_112', 0, '烤盘风扇实际转速1'),
    'd_ro_bake_fan_speed2': ('d_grp_110_112', 1, '烤盘风扇实际转速2'),
    'd_ro_bake_fan_speed3': ('d_grp_110_112', 2, '烤盘风扇实际转速3'),
    # D120-D124 烤盘温度(16位, 0.1°C)
    'd_ro_bake_temp1': ('d_grp_120_124', 0, '烤盘温度1'),
    'd_ro_bake_temp2': ('d_grp_120_124', 2, '烤盘温度2'),
    'd_ro_bake_temp3': ('d_grp_120_124', 4, '烤盘温度3'),
    # D211
    'd_ro_power_status': ('d_grp_211', 0, '开机状态'),
    # D220-D238 电气(浮点)
    'd_ro_voltage_a':    ('d_grp_220_238', 0,  '电压A', 'float'),
    'd_ro_voltage_b':    ('d_grp_220_238', 2,  '电压B', 'float'),
    'd_ro_voltage_c':    ('d_grp_220_238', 4,  '电压C', 'float'),
    'd_ro_current_a':    ('d_grp_220_238', 6,  '电流A', 'float'),
    'd_ro_current_b':    ('d_grp_220_238', 8,  '电流B', 'float'),
    'd_ro_current_c':    ('d_grp_220_238', 10, '电流C', 'float'),
    'd_ro_power':        ('d_grp_220_238', 12, '功率', 'float'),
    'd_ro_total_energy': ('d_grp_220_238', 14, '累计电能', 'float'),
    'd_ro_today_energy': ('d_grp_220_238', 18, '当天电能', 'float'),
    # D244-D248 扭矩报警(16位)
    'd_ro_aodian_torque': ('d_grp_244_248', 0, '鏊电机扭矩'),
    'd_ro_aodian_alarm':  ('d_grp_244_248', 1, '鏊电机报警'),
    'd_ro_peel_torque':   ('d_grp_244_248', 3, '揭皮电机扭矩'),
    'd_ro_peel_alarm':    ('d_grp_244_248', 4, '揭皮电机报警'),
    # D20120-D20142 生产计时(32位)
    'd_ro_today_prod':      ('d_grp_prod_timer', 0,  '今天生产', 32),
    'd_ro_total_prod':      ('d_grp_prod_timer', 2,  '累计生产', 32),
    'd_ro_heat1_timer':     ('d_grp_prod_timer', 4,  '加热1计时', 32),
    'd_ro_heat2_timer':     ('d_grp_prod_timer', 6,  '加热2计时', 32),
    'd_ro_heat3_timer':     ('d_grp_prod_timer', 8,  '加热3计时', 32),
    'd_ro_bake1_timer':     ('d_grp_prod_timer', 10, '烤盘1计时', 32),
    'd_ro_bake2_timer':     ('d_grp_prod_timer', 12, '烤盘2计时', 32),
    'd_ro_bake3_timer':     ('d_grp_prod_timer', 14, '烤盘3计时', 32),
    'd_ro_sterilize_timer': ('d_grp_prod_timer', 16, '杀菌计时', 32),
    'd_ro_oil_out_timer':   ('d_grp_prod_timer', 18, '加油外计时', 32),
    'd_ro_oil_in_timer':    ('d_grp_prod_timer', 20, '加油中计时', 32),
    'd_ro_oil_mid_timer':   ('d_grp_prod_timer', 22, '加油内计时', 32),
}

# D 只写寄存器（不加入 D_GROUPS 轮询，只提供写入 API）
D_WO_POINTS = [
    ('d_wo_slave_temp',      290, '从屏箱温度', '°C'),
    ('d_wo_peel_fan_speed',  291, '揭皮风扇转速', '转/分'),
    ('d_wo_peel_fan_comm',   292, '揭皮风扇通讯状态', ''),
    ('d_wo_power_temp',      295, '电源箱温度', '°C'),
    ('d_wo_oil_fan_speed',   296, '抹油风扇转速', '转/分'),
    ('d_wo_oil_fan_comm',    297, '抹油风扇通讯状态', ''),
]

# D 读写寄存器（断电保持，轮询 + 支持 eng 工程值转换）
# 格式: (name, offset, desc, bits, eng_scale, eng_unit, default)
D_RW_POINTS = [
    # 手动速度 (D20000-D20012, 32位)
    ('d_rw_manual_aodian_speed',  20000, '手动鏊转速度', 32, 0.0018, '°', 0),
    ('d_rw_manual_scraper_speed', 20002, '手动刮板速度', 32, 0.036, '°', 0),
    ('d_rw_manual_rise_speed',    20004, '手动升降速度', 32, 0.0005, 'mm/s', 0),
    ('d_rw_manual_oil_speed',     20006, '手动抹油速度', 32, 0.009, 'mm/s', 0),
    ('d_rw_manual_peel_speed',    20008, '手动揭皮速度', 32, 0.01, 'mm/s', 0),
    ('d_rw_manual_feed1_speed',   20010, '手动料泵1速度', 32, 0.0517, 'mL/s', 0),
    ('d_rw_manual_feed2_speed',   20012, '手动料泵2速度', 32, 0.0517, 'mL/s', 0),
    # 设置参数 (D20020-D20022)
    ('d_rw_manual_heat_output',   20020, '手动加热输出', 'float', None, '%', 0.0),
    ('d_rw_turntable_idle',       20022, '转盘空转速度', 32, 0.0018, '°', 0),
    # 工艺参数1 (D20030-D20054, 32位)
    ('d_rw_aodian_angle',       20030, '鏊转角度', 32, 0.0018, '°', 0),
    ('d_rw_aodian_speed',       20032, '鏊转速度', 32, 0.0018, '°', 0),
    ('d_rw_scraper_rounds1',    20034, '刮料圈数1', 32, 0.036, '圈', 0),
    ('d_rw_scraper_speed1',     20036, '刮料速度1', 32, 0.036, '°', 0),
    ('d_rw_scraper_shake_angle',20038, '刮板抖动角度', 32, 0.036, '°', 0),
    ('d_rw_scraper_shake_speed',20040, '刮板抖动速度', 32, 0.036, '°', 0),
    ('d_rw_rise_speed',         20042, '升降速度', 32, 0.0005, 'mm/s', 0),
    ('d_rw_rise_dist',          20044, '上升距离', 32, 0.0005, 'mm', 0),
    ('d_rw_fall_dist1',         20046, '下降距离1', 32, 0.0005, 'mm', 0),
    ('d_rw_lift_dist1',         20048, '提升距离1', 32, 0.0005, 'mm', 0),
    ('d_rw_feed_vol1',          20050, '打料量1', 32, 0.0517, 'mL', 0),
    ('d_rw_back_vol1',          20052, '回抽量1', 32, 0.0517, 'mL', 0),
    ('d_rw_pump_speed1',        20054, '泵速度1', 32, 0.0517, 'mL/s', 0),
    # 工艺参数2 (D20060-D20072, 混合)
    ('d_rw_peel_dist',          20060, '揭皮距离', 32, 0.01, 'mm', 0),
    ('d_rw_peel_ratio',         20062, '揭皮速比', 'float', None, '', 0.0),
    ('d_rw_aodian_shake_angle', 20064, '鏊抖动角度', 32, 0.0018, '°', 0),
    ('d_rw_aodian_delay',       20066, '鏊延时启动', 16, 0.1, '°C', 0),
    ('d_rw_aodian_comp_angle',  20068, '鏊补偿角度', 32, 0.0018, '°', 0),
    ('d_rw_fall_min_dist',      20070, '下降最小距离', 32, 0.0005, 'mm', 0),
    ('d_rw_fall_max_dist',      20072, '下降最大距离', 32, 0.0005, 'mm', 0),
    # 时间参数 (D20080-D20087, 16位)
    ('d_rw_stir_cycle',      20080, '搅拌周期', 16, 0.1, 's', 0),
    ('d_rw_stir_time',       20081, '搅拌时间', 16, 0.1, 's', 0),
    ('d_rw_oil_time_out',    20082, '加油时间外', 16, 0.1, 's', 0),
    ('d_rw_oil_time_mid',    20083, '加油时间中', 16, 0.1, 's', 0),
    ('d_rw_oil_time_in',     20084, '加油时间内', 16, 0.1, 's', 0),
    ('d_rw_idle_oil_out',    20085, '空转加油外', 16, 0.1, 's', 0),
    ('d_rw_idle_oil_mid',    20086, '空转加油中', 16, 0.1, 's', 0),
    ('d_rw_idle_oil_in',     20087, '空转加油内', 16, 0.1, 's', 0),
    # 输出参数 (D20090-D20097, 16位)
    ('d_rw_bake_out1',    20090, '烤盘输出1', 16, None, '', 0),
    ('d_rw_bake_out2',    20092, '烤盘输出2', 16, None, '', 0),
    ('d_rw_bake_out3',    20093, '烤盘输出3', 16, None, '', 0),
    ('d_rw_bake_fan1',    20094, '烤盘风扇1', 16, None, '', 0),
    ('d_rw_bake_fan2',    20095, '烤盘风扇2', 16, None, '', 0),
    ('d_rw_bake_fan3',    20096, '烤盘风扇3', 16, None, '', 0),
    ('d_rw_peel_fan',     20097, '揭皮风扇', 16, None, '', 0),
    ('d_rw_oil_fan',      20098, '抹油风扇', 16, None, '', 0),
    # 温度设定 (D20100-D20116, 浮点)
    ('d_rw_heat_temp',   20100, '加热温度', 'float', None, '°C', 0.0),
    ('d_rw_idle_temp',   20102, '空转温度', 'float', None, '°C', 0.0),
    ('d_rw_min_output',  20104, '最小输出', 'float', None, '%', 0.0),
    ('d_rw_max_output',  20106, '最大输出', 'float', None, '%', 0.0),
    ('d_rw_prod_temp',   20114, '生产温度', 'float', None, '°C', 0.0),
    ('d_rw_safety_temp', 20116, '安全温度', 'float', None, '°C', 0.0),
    # 配方2参数 (D20150-D20162, 32位)
    ('d_rw_scraper_pos2',   20150, '刮料位置2', 32, 0.0001, '圈', 0),
    ('d_rw_scraper_speed2', 20152, '刮料速度2', 32, 0.036, '°', 0),
    ('d_rw_fall_dist2',     20154, '下降位置2', 32, 0.0005, 'mm', 0),
    ('d_rw_lift_dist2',     20156, '提升位置2', 32, 0.0005, 'mm', 0),
    ('d_rw_feed_vol2',      20158, '打料量2', 32, 0.0517, 'mL', 0),
    ('d_rw_back_vol2',      20160, '回抽量2', 32, 0.0517, 'mL', 0),
    ('d_rw_pump_speed2',    20162, '泵速度2', 32, 0.0517, 'mL/s', 0),
    # 生产目标 (D20220-D20222, 32位)
    ('d_rw_target_prod', 20220, '目标生产', 32, None, '', 0),
    ('d_rw_batch_prod',  20222, '本批生产', 32, None, '', 0),
    # PID 参数 (D21002-D21012, 浮点)
    ('d_rw_pid_kp', 21002, 'PID比例', 'float', None, '', 0.0),
    ('d_rw_pid_ki', 21004, 'PID积分', 'float', None, '', 0.0),
    ('d_rw_pid_kd', 21006, 'PID微分', 'float', None, '', 0.0),
    ('d_rw_pid_ff', 21012, 'PID前馈', 'float', None, '', 0.0),
]

POINTS = _build_points()


# ═══════════════════════════════════════════════════════════
# 独立解析函数（供 PlcWorker 等调用，纯数据转换，无 IO）
# ═══════════════════════════════════════════════════════════

def parse_snapshot(raw_cache: dict) -> dict:
    """将原始读取结果解析为命名点位快照。

    Args:
        raw_cache: {request_name: raw_data_or_None}
                   其中 raw_data 是 bit 列表(discrete/coil) 或 int 列表(hr)

    Returns:
        {point_name: value, ...}  所有点位默认值 0/False/0.0
    """
    import struct as _struct

    result = {}

    def _safe_len(data):
        return len(data) if isinstance(data, (list, tuple)) else 0

    # X (Discrete Inputs, bit 列表)
    x_data = raw_cache.get('X')
    x_len = _safe_len(x_data)
    for name, off, desc in X_POINTS:
        result[name] = bool(x_data[off]) if off < x_len else False

    # Y (Coils, bit 列表)
    y_data = raw_cache.get('Y')
    y_len = _safe_len(y_data)
    for name, off, desc in Y_POINTS:
        result[name] = bool(y_data[off]) if off < y_len else False

    # M RW (Coils)
    m_data = raw_cache.get('M')
    m_len = _safe_len(m_data)
    for name, off, desc in M_POINTS:
        result[name] = bool(m_data[off]) if off < m_len else False
    for name, off, desc in M_RO_POINTS:
        result[name] = bool(m_data[off]) if off < m_len else False

    # SR (Holding Registers, 32-bit from two 16-bit words)
    sr_data = raw_cache.get('SR')
    sr_len = _safe_len(sr_data)
    for name, off, desc, raw_min, raw_max, eng_scale, eng_unit in SR_POINTS:
        local = off - SR_START
        if local + 1 < sr_len:
            val = (sr_data[local + 1] << 16) | sr_data[local]
            if val >= 0x80000000:
                val -= 0x100000000
            result[name] = val
            result[name + '_eng'] = round(val * eng_scale, 6)
        else:
            result[name] = 0
            result[name + '_eng'] = 0.0

    # D 寄存器 (Holding Registers, 支持 16/32/float)
    for name, entry in D_POINTS.items():
        grp_name = entry[0]
        off_in_grp = entry[1]
        bits = entry[3] if len(entry) > 3 else 16
        d_data = raw_cache.get(grp_name)
        d_len = _safe_len(d_data)
        if off_in_grp < d_len:
            low = d_data[off_in_grp]
            if bits == 32:
                if off_in_grp + 1 < d_len:
                    high = d_data[off_in_grp + 1]
                    result[name] = (high << 16) | low
                else:
                    result[name] = 0
            elif bits == 'float':
                if off_in_grp + 1 < d_len:
                    high = d_data[off_in_grp + 1]
                    try:
                        result[name] = _struct.unpack('>f', _struct.pack('>HH', high, low))[0]
                    except Exception:
                        result[name] = _struct.unpack('<f', _struct.pack('<HH', low, high))[0]
                else:
                    result[name] = 0.0
            else:
                result[name] = low
        else:
            if bits == 'float':
                result[name] = 0.0
            else:
                result[name] = 0

    # D_RW_POINTS 断电保持寄存器 (raw + eng 两版)
    # 构建 offset → group 映射（模块级缓存，避免每次重建）
    global _RW_GRP_MAP
    if '_RW_GRP_MAP' not in globals():
        _rw_grp_map = {}
        for grp_name, start, count in D_GROUPS:
            for off_abs in range(start, start + count):
                _rw_grp_map[off_abs] = (grp_name, start)
        globals()['_RW_GRP_MAP'] = _rw_grp_map
    else:
        _rw_grp_map = globals()['_RW_GRP_MAP']

    for name, off, desc, bits, eng_scale, eng_unit, _default in D_RW_POINTS:
        grp_info = _rw_grp_map.get(off)
        if grp_info is None:
            result[name] = 0 if bits != 'float' else 0.0
            result[name + '_eng'] = 0.0
            continue
        grp_name, grp_start = grp_info
        off_in_grp = off - grp_start
        d_data = raw_cache.get(grp_name)
        d_len = _safe_len(d_data)
        raw_val = None
        if off_in_grp < d_len:
            low = d_data[off_in_grp]
            if bits == 32:
                if off_in_grp + 1 < d_len:
                    high = d_data[off_in_grp + 1]
                    raw_val = (high << 16) | low
                else:
                    raw_val = 0
            elif bits == 'float':
                if off_in_grp + 1 < d_len:
                    high = d_data[off_in_grp + 1]
                    try:
                        raw_val = _struct.unpack('>f', _struct.pack('>HH', high, low))[0]
                    except Exception:
                        raw_val = _struct.unpack('<f', _struct.pack('<HH', low, high))[0]
                else:
                    raw_val = 0.0
            else:
                raw_val = low
        if raw_val is None:
            raw_val = 0 if bits != 'float' else 0.0
        result[name] = raw_val
        if eng_scale is not None and eng_scale != 0 and isinstance(raw_val, (int, float)):
            result[name + '_eng'] = round(raw_val * eng_scale, 6)
        else:
            result[name + '_eng'] = raw_val

    return result


def build_read_configs():
    """构建 PlcWorker 的读请求配置列表。

    Returns:
        [(name, type, start_addr, count), ...]
    """
    configs = [
        ('X',  'discrete', mb_addr('X', 0),  X_READ_COUNT),
        ('Y',  'coils',    mb_addr('Y', 0),  Y_READ_COUNT),
        ('M',  'coils',    mb_addr('M', 0),  M_READ_COUNT),
        ('SR', 'hr',       mb_addr('SR', SR_START), SR_COUNT),
    ]
    for grp_name, start, count in D_GROUPS:
        configs.append((grp_name, 'hr', mb_addr('D', start), count))
    return configs


# ── PLC 通讯类 (DEPRECATED — 请用 core.plc_worker.PlcWorker) ──

class ModbusError(Exception):
    """Modbus 通讯异常"""


class DeltaPLC(RequestChain):
    """台达 AS 系列 PLC 通讯适配器。

    每周期读取 X/Y/M/SR 四组寄存器，
    解析后通过回调推送命名点位快照。

    回调事件:
        'data_updated':  callback(dict)      # 完整快照 {name: value, ...}
        'point_changed': callback(name, val) # 单点位变化
        'error':         callback(msg)       # 错误消息
    """

    def __init__(self, host: str, port: int = 502, slave: int = 1):
        super().__init__(timeout_ms=1000, gap_ms=0)
        self.host  = host
        self.port  = port
        self.slave = slave
        self._client = None
        self._cache  = {}
        self._expected = 0
        self._received  = 0
        self._lock = threading.Lock()
        self._last_values = {}  # 用于检测变化
        self._last_connect_fail = 0.0  # 重连冷却计时
        self._pending_writes = []          # 待写入队列: [(action_type, *args), ...]
        self._writes_lock = threading.Lock()

    # ── 连接管理 ───────────────────────────────────────────

    def _ensure(self) -> bool:
        # 已有有效连接：直接返回
        if self._client is not None and self._client.connected:
            return True

        # 10 秒冷却：上次连接失败后短时间内不再重试，避免阻塞主线程
        if time.monotonic() - self._last_connect_fail < 10.0:
            return False

        # 先关闭旧连接，防止 TCP 连接泄露
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

        # 直接用 pymodbus connect(timeout=1.0) 处理连接
        # 不再使用 socket.create_connection 预检，避免 ARM 上 GIL 未正确释放导致主线程被卡
        try:
            self._client = ModbusTcpClient(
                host=self.host, port=self.port, timeout=1.0)
            if self._client.connect():
                return True
        except Exception:
            pass

        # 连接失败
        self._last_connect_fail = time.monotonic()
        self._client = None
        return False

    def _close_client(self):
        """安全关闭 Modbus 客户端"""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _client_ready(self) -> bool:
        """只检查连接状态，不尝试重连（供写操作使用，保证按钮点击零阻塞）"""
        return self._client is not None and self._client.connected

    # ── Modbus 读原语 ──────────────────────────────────────

    def _read_hr(self, start: int, count: int) -> list:
        if not self._ensure():
            raise ModbusError("PLC 未连接")
        with self._lock:
            try:
                rr = self._client.read_holding_registers(
                    start, count=count, device_id=self.slave)
            except Exception as e:
                self._close_client()
                raise ModbusError(f"PLC 读HR异常: {e}")
            if rr.isError():
                raise ModbusError(str(rr))
            return rr.registers

    def _read_coils(self, start: int, count: int) -> list:
        if not self._ensure():
            raise ModbusError("PLC 未连接")
        with self._lock:
            try:
                rr = self._client.read_coils(
                    start, count=count, device_id=self.slave)
            except Exception as e:
                self._close_client()
                raise ModbusError(f"PLC 读Coil异常: {e}")
            if rr.isError():
                raise ModbusError(str(rr))
            return [bool(b) for b in rr.bits[:count]]

    def _read_discrete(self, start: int, count: int) -> list:
        if not self._ensure():
            raise ModbusError("PLC 未连接")
        with self._lock:
            try:
                rr = self._client.read_discrete_inputs(
                    start, count=count, device_id=self.slave)
            except Exception as e:
                self._close_client()
                raise ModbusError(f"PLC 读DI异常: {e}")
            if rr.isError():
                raise ModbusError(str(rr))
            return [bool(b) for b in rr.bits[:count]]

    # ── Modbus 写原语 ──────────────────────────────────────

    def _write_coil(self, addr: int, value: bool):
        with self._lock:
            if not self._client_ready():
                raise ModbusError("PLC 离线")
            try:
                rr = self._client.write_coil(
                    addr, value, device_id=self.slave)
            except Exception as e:
                self._close_client()
                raise ModbusError(f"PLC 写Coil异常: {e}")
            if rr.isError():
                raise ModbusError(str(rr))

    def _write_register(self, addr: int, value: int):
        """写入单个保持寄存器"""
        with self._lock:
            if not self._client_ready():
                raise ModbusError("PLC 离线")
            try:
                rr = self._client.write_register(
                    addr, value, device_id=self.slave)
            except Exception as e:
                self._close_client()
                raise ModbusError(f"PLC 写寄存器异常: {e}")
            if rr.isError():
                raise ModbusError(str(rr))

    # ── 请求链配置 ─────────────────────────────────────────

    def configure_polling(self):
        """配置轮询：X/Y/M/SR + D寄存器各组"""
        # 用回调替代 Qt signals connect/disconnect
        self.off('finished')
        self.off('failed')

        requests = [
            ('X',  lambda: self._read_discrete(mb_addr('X', 0), X_READ_COUNT)),
            ('Y',  lambda: self._read_coils(mb_addr('Y', 0), Y_READ_COUNT)),
            ('M',  lambda: self._read_coils(mb_addr('M', 0), M_READ_COUNT)),
            ('SR', lambda: self._read_hr(mb_addr('SR', SR_START), SR_COUNT)),
        ]
        for grp_name, start, count in D_GROUPS:
            requests.append((grp_name, lambda s=start, c=count: self._read_hr(mb_addr('D', s), c)))

        self.set_requests(requests)
        self._expected = len(requests)
        self._received  = 0
        self._cache     = {}
        self.on('finished', self._collect)
        self.on('failed', self._on_fail)

    def _collect(self, name: str, data):
        self._cache[name] = data
        self._received += 1
        if self._received >= self._expected:
            snapshot = self._parse_snapshot()
            # 检测变化
            for k, v in snapshot.items():
                if self._last_values.get(k) != v:
                    self._emit('point_changed', k, v)
            self._last_values = snapshot
            self._emit('data_updated', snapshot)
            self._received = 0
            self._cache.clear()

    def _on_fail(self, name: str, error):
        self._cache[name] = None
        self._received += 1
        if self._received >= self._expected:
            # 断网节流：若本轮所有请求均失败（_cache 全为 None），
            # sleep 1.5s 防止 data_updated 洪泛冲击 Qt 主线程事件队列。
            # 每秒最多 ~0.67 次 data_updated，UI 不再卡死。
            all_failed = all(v is None for v in self._cache.values())
            snapshot = self._parse_snapshot()
            self._emit('data_updated', snapshot)
            self._received = 0
            self._cache.clear()
            if all_failed:
                time.sleep(1.5)

    def _parse_snapshot(self) -> dict:
        """将原始字节数组解析为命名点位快照"""
        result = {}

        def _safe_len(data):
            return len(data) if isinstance(data, (list, tuple)) else 0

        # X (Discrete Inputs, bit 列表)
        x_data = self._cache.get('X')
        x_len = _safe_len(x_data)
        for name, off, desc in X_POINTS:
            result[name] = bool(x_data[off]) if off < x_len else False

        # Y (Coils, bit 列表)
        y_data = self._cache.get('Y')
        y_len = _safe_len(y_data)
        for name, off, desc in Y_POINTS:
            result[name] = bool(y_data[off]) if off < y_len else False

        # M RW (Coils)
        m_data = self._cache.get('M')
        m_len = _safe_len(m_data)
        for name, off, desc in M_POINTS:
            result[name] = bool(m_data[off]) if off < m_len else False
        for name, off, desc in M_RO_POINTS:
            result[name] = bool(m_data[off]) if off < m_len else False

        # SR (Holding Registers, 32-bit from two 16-bit words)
        sr_data = self._cache.get('SR')
        sr_len = _safe_len(sr_data)
        for name, off, desc, raw_min, raw_max, eng_scale, eng_unit in SR_POINTS:
            local = off - SR_START
            if local + 1 < sr_len:
                val = (sr_data[local + 1] << 16) | sr_data[local]
                # sign-extend 32-bit
                if val >= 0x80000000:
                    val -= 0x100000000
                result[name] = val
                result[name + '_eng'] = round(val * eng_scale, 6)
            else:
                result[name] = 0
                result[name + '_eng'] = 0.0

        # D 寄存器 (Holding Registers, 支持 16/32/float)
        for name, entry in D_POINTS.items():
            grp_name = entry[0]
            off_in_grp = entry[1]
            bits = entry[3] if len(entry) > 3 else 16
            d_data = self._cache.get(grp_name)
            d_len = _safe_len(d_data)
            if off_in_grp < d_len:
                low = d_data[off_in_grp]
                if bits == 32:
                    # 32位整数: 两个寄存器, high<<16|low
                    if off_in_grp + 1 < d_len:
                        high = d_data[off_in_grp + 1]
                        result[name] = (high << 16) | low
                    else:
                        result[name] = 0
                elif bits == 'float':
                    # 浮点: 两个寄存器, 先试大端再试小端
                    if off_in_grp + 1 < d_len:
                        high = d_data[off_in_grp + 1]
                        try:
                            # 大端: high在前
                            result[name] = struct.unpack('>f', struct.pack('>HH', high, low))[0]
                        except Exception:
                            # 小端: low在前
                            result[name] = struct.unpack('<f', struct.pack('<HH', low, high))[0]
                    else:
                        result[name] = 0.0
                else:
                    # 16位整数
                    result[name] = low
            else:
                # 默认值
                if bits == 'float':
                    result[name] = 0.0
                else:
                    result[name] = 0

        # D_RW_POINTS 断电保持寄存器 (raw + eng 两版)
        # 构建 offset → group 映射
        _rw_grp_map = {}  # offset → (group_name, group_start)
        for grp_name, start, count in D_GROUPS:
            for off in range(start, start + count):
                _rw_grp_map[off] = (grp_name, start)
        for name, off, desc, bits, eng_scale, eng_unit, _default in D_RW_POINTS:
            grp_info = _rw_grp_map.get(off)
            if grp_info is None:
                result[name] = 0 if bits != 'float' else 0.0
                result[name + '_eng'] = 0.0
                continue
            grp_name, grp_start = grp_info
            off_in_grp = off - grp_start
            d_data = self._cache.get(grp_name)
            d_len = _safe_len(d_data)
            raw_val = None
            if off_in_grp < d_len:
                low = d_data[off_in_grp]
                if bits == 32:
                    if off_in_grp + 1 < d_len:
                        high = d_data[off_in_grp + 1]
                        raw_val = (high << 16) | low
                    else:
                        raw_val = 0
                elif bits == 'float':
                    if off_in_grp + 1 < d_len:
                        high = d_data[off_in_grp + 1]
                        try:
                            raw_val = struct.unpack('>f', struct.pack('>HH', high, low))[0]
                        except Exception:
                            raw_val = struct.unpack('<f', struct.pack('<HH', low, high))[0]
                    else:
                        raw_val = 0.0
                else:
                    raw_val = low
            if raw_val is None:
                raw_val = 0 if bits != 'float' else 0.0
            result[name] = raw_val
            # 工程值转换
            if eng_scale is not None and eng_scale != 0 and isinstance(raw_val, (int, float)):
                result[name + '_eng'] = round(raw_val * eng_scale, 6)
            else:
                result[name + '_eng'] = raw_val

        return result

    # ── 写入 API ───────────────────────────────────────────

    def _warn_ro(self, name: str):
        print(f"[PLC] 警告：尝试写入只读点位 {name}", flush=True)

    def set_point(self, name: str, value: Union[bool, int]):
        """按名称写入点位（投递到后台队列，主线程零阻塞）"""
        pt = POINTS.get(name)
        if pt is None:
            raise KeyError(f"未知点位: {name}")
        if pt.access != 'rw':
            self._warn_ro(name)
            return
        with self._writes_lock:
            self._pending_writes.append(('point', name, value))

    def set_d_wo(self, name: str, value: int):
        """写入 D 区只写寄存器（投递到后台队列）"""
        pt = POINTS.get(name)
        if pt is None:
            raise KeyError(f"未知 D 只写点位: {name}")
        if pt.region != 'D':
            raise ValueError(f"点位 {name} 不在 D 区")
        with self._writes_lock:
            self._pending_writes.append(('d_wo', name, value))

    def set_M(self, offset: int, value: bool):
        """按偏移写入 M 继电器（投递到后台队列）"""
        with self._writes_lock:
            self._pending_writes.append(('M', offset, value))

    # ── 后台写入刷新 ───────────────────────────────────────

    def _flush_writes(self):
        """后台线程调用：取出待写入队列并逐个执行实际 Modbus 写入。
        
        PLC 离线时跳过（命令留在队列），单条失败 emit 'error' 并放回队首等待重试。
        """
        if not self._pending_writes:
            return
        if not self._client_ready():
            return   # PLC 离线，命令留在队列等下次
        with self._writes_lock:
            writes = self._pending_writes
            self._pending_writes = []
        failed = []
        for entry in writes:
            try:
                action = entry[0]
                if action == 'point':
                    _, name, value = entry
                    pt = POINTS.get(name)
                    if pt is None or pt.access != 'rw':
                        continue
                    if pt.region == 'M':
                        self._write_coil(mb_addr(pt.region, pt.offset), bool(value))
                    elif pt.region == 'D':
                        self._write_register(mb_addr(pt.region, pt.offset), int(value))
                elif action == 'd_wo':
                    _, name, value = entry
                    pt = POINTS.get(name)
                    if pt is None or pt.region != 'D':
                        continue
                    self._write_register(mb_addr('D', pt.offset), int(value))
                elif action == 'M':
                    _, offset, value = entry
                    self._write_coil(mb_addr('M', offset), bool(value))
            except Exception as e:
                self._emit('error', f"写入失败 ({entry[0]} {entry[1]}): {e}")
                failed.append(entry)
        # 失败的命令放回队首，下次周期优先重试
        if failed:
            with self._writes_lock:
                self._pending_writes = failed + self._pending_writes

    # ── 便捷写入 ───────────────────────────────────────────

    def write_manual(self, on: bool):
        """M0 手动模式"""
        self.set_point("m_rw_manual", on)

    def write_power(self, on: bool):
        """M44 开机"""
        self.set_point("m_rw_power", on)

    def write_light(self, on: bool):
        """M43 照明"""
        self.set_point("m_rw_light", on)

    def write_start(self, on: bool = True):
        """M41 启动（脉冲）"""
        self.set_point("m_rw_start", on)
        if on:
            # 脉冲：延迟复位（由 PLC 侧处理或此处定时复位）
            pass

    def write_reset(self, on: bool = True):
        """M40 复位（脉冲）"""
        self.set_point("m_rw_reset", on)

    def write_heat(self, on: bool):
        """M42 加热"""
        self.set_point("m_rw_heat", on)

    def write_bake(self, on: bool):
        """M52 烤盘"""
        self.set_point("m_rw_bake", on)

    def write_motor_reset(self, on: bool = True):
        """M53 电机复位（脉冲）"""
        self.set_point("m_rw_motor_reset", on)

    def write_heat_manual(self, on: bool):
        """M54 手动加热"""
        self.set_point("m_rw_heat_manual", on)

    def write_offline(self, on: bool):
        """M51 脱机"""
        self.set_point("m_rw_offline", on)

    # ── 手动动作 ──────────────────────────────────────────

    MANUAL_ACTIONS = {
        "turntable_ccw":  "m_rw_turntable_ccw",
        "turntable_cw":   "m_rw_turntable_cw",
        "scraper_ccw":    "m_rw_scraper_ccw",
        "scraper_cw":     "m_rw_scraper_cw",
        "rise":           "m_rw_rise",
        "fall":           "m_rw_fall",
        "oil_fwd":        "m_rw_oil_fwd",
        "oil_back":       "m_rw_oil_back",
        "peel_fwd":       "m_rw_peel_fwd",
        "peel_back":      "m_rw_peel_back",
        "feed1":          "m_rw_feed1",
        "back1":          "m_rw_back1",
        "feed2":          "m_rw_feed2",
        "back2":          "m_rw_back2",
        "heat_cool":      "m_rw_heat_cool",
        "prod_cool":      "m_rw_prod_cool",
        "stir1":          "m_rw_stir1_manual",
        "sterilize":      "m_rw_sterilize",
        "oil_pump_out":   "m_rw_oil_pump_out_m",
        "oil_pump_mid":   "m_rw_oil_pump_mid_m",
        "oil_pump_in":    "m_rw_oil_pump_in_m",
        "stir2":          "m_rw_stir2_manual",
    }

    def manual_action(self, action: str, on: bool):
        """执行手动动作（按下=置位，松开=复位）"""
        name = self.MANUAL_ACTIONS.get(action)
        if name is None:
            raise KeyError(f"未知手动动作: {action}")
        self.set_point(name, on)

    # ── 首页快捷动作 ──────────────────────────────────────

    def home_idle(self, on: bool):
        """M45 空转"""
        self.set_point("m_rw_idle", on)

    def home_feed1(self, on: bool):
        """M46 打料1"""
        self.set_point("m_rw_feed1_home", on)

    def home_back1(self, on: bool):
        """M47 回抽1"""
        self.set_point("m_rw_back1_home", on)

    def home_feed2(self, on: bool):
        """M48 打料2"""
        self.set_point("m_rw_feed2_home", on)

    def home_back2(self, on: bool):
        """M49 回抽2"""
        self.set_point("m_rw_back2_home", on)

    # ── 断开 ───────────────────────────────────────────────

    def disconnect(self):
        self.stop()
        if self._client:
            self._client.close()
            self._client = None

    def run(self):
        """驱动循环：在后台线程中持续执行请求链。
        
        每周期先刷新待写入队列，再执行一轮 Modbus 读取。
        """
        while self._running:
            self._flush_writes()
            self.drive_one()
