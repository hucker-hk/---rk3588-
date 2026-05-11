# 通讯 Agent — 全自动煎饼机

## 职责

- 负责所有底层设备通讯协议的实现和维护
- 暴露数据给界面层（通过 `on('event', callback)` 回调模式）
- **禁止**导入或使用 PySide6 / PyQt5 / PyQt6，任何 Qt 类

## 管辖文件

```
core/plc.py            — 台达 AS 系列 PLC (Modbus TCP)
core/hmi.py            — 昆仑通态 HMI (Modbus TCP)
core/serial_devices.py — 风扇/步进电机 (串口 RS485)
core/request_chain.py  — 请求链引擎（发送→等回复→下一条）
core/__init__.py        — 包初始化
```

## 技术栈

- **Modbus TCP**：`pymodbus` (v3.x)
- **串口 RS485**：`pyserial`
- **线程**：`threading.Thread`（不用 QThread）
- **无 Qt 依赖**

## 通讯架构

### 请求链模式 (`request_chain.py`)

```
发送请求 → 等待回复 → 超时判故障 → 发送下一条
```

- 配置间隔 `gap_ms`（0 时用 Event 等待）
- 外部调用 `drive_one()` 驱动链路
- 每条请求有 `name` 和 `fn`（返回原始数据的函数）
- 所有请求完成触发 `finished` 事件
- 任一请求失败触发 `failed` 事件

### 数据上行（给界面）

```python
# 通讯层暴露事件
self.on('event_name', callback)    # 注册回调
self.off('event_name')             # 移除回调
self._emit('event_name', *args)   # 内部触发

# 标准事件
'data_updated'   → callback(dict)        # 完整点位快照 {name: value, ...}
'point_changed'  → callback(name, value)  # 单点位变化
'error'          → callback(message)      # 错误消息
```

### 驱动循环

每个通讯模块在自己的线程中运行：

```python
def run(self):
    while self._running:
        self.drive_one()
```

## 变量命名规范

| 前缀/后缀 | 含义 | 示例 |
|-----------|------|------|
| `_ro` | 只读 | `d_ro_voltage`, `x_ro_limit` |
| `_rw` | 读写 | `m_rw_manual`, `d_rw_target` |
| `r_` | 只读 | `r_temperature` |
| `rw_` | 读写 | `rw_mode` |
| `w_` | 只写 | `w_command` |

## PLC 地址基址 (plc.py)

| 区域 | Modbus 基址 | 类型 | 访问 |
|------|------------|------|------|
| X | 0x6000 | Discrete Input | 只读 |
| Y | 0xA000 | Coil | 只读 |
| M | 0x0000 | Coil | 读写（M50 只读） |
| D | 0x0000 | Holding Register | 读写 |
| SR | 0xC000 | Holding Register | 只读（32位） |

## HMI 寄存器 (hmi.py)

| 寄存器 | 说明 | 类型 |
|--------|------|------|
| 0 | 设备名称 (字符串) | 只读 |
| 150 | 地区 (字符串) | 只读 |
| 200 | 天气 (字符串) | 只读 |
| 250 | 温度 (整数) | 只读 |
| 300 | 物联网版本 (字符串) | 只读 |

## 串口设备 (serial_devices.py)

- 端口: `/dev/ttyS3`
- 波特率: 9600
- 数据位: 8, 校验: None, 停止位: 1
- 风扇 1 站号: 1
- 风扇 2 站号: 2
- 未来扩展：步进电机

## Modbus 参数

- pymodbus v3.x 参数名：`device_id=`（不是 `slave=`）
- 字符串字节序：小端 `to_bytes(2, 'little')`
- 32位寄存器：低16位在前 `(high << 16) | low`

## 错误处理

- 每次失败关闭 `ModbusTcpClient` 连接，防止 CLOSE-WAIT 泄露
- 超时后跳过当前请求，继续下一条
- 连接断开自动重连

## 禁止事项

- ❌ `from PySide6 import ...`
- ❌ `from PyQt5 import ...`
- ❌ `from PyQt6 import ...`
- ❌ 任何 Qt Signal/Slot/QObject
- ❌ 直接操作 UI 文件
- ❌ 导入 `ui/` 下任何模块
