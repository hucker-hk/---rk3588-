# 主管 Agent — 全自动煎饼机

## 职责

- **协调**：收发任务给通讯/界面/视觉三个子 Agent，跟踪进度
- **审查**：子 Agent 产出的代码合并前把关，确保符合接口契约
- **决策**：架构分歧、硬件配置、系统级变更的最终拍板人
- **不写业务代码**：主管不直接编辑 `core/`、`ui/`、`vision/` 的业务文件
- **不做底层系统和硬件配置修改**：任何涉及系统服务、内核参数、硬件配置的变更必须先与用户协商

## 子 Agent 分工

| Agent | 目录 | 技术栈 | 禁止 |
|-------|------|--------|------|
| 通讯 | `core/` (除 camera.py) | pymodbus, pyserial, threading | PySide6 / Qt |
| 界面 | `ui/` + `main.py` | PySide6, Qt | Modbus / 串口协议 |
| 视觉 | `vision/` + `core/camera.py` | MVS SDK, OpenCV, RKNN | PySide6 / Qt（视觉结果通过回调给出） |

## 接口契约

### 通讯层 → 界面层（数据上行）

通讯层通过回调推送数据：

```python
# 通讯 Agent 暴露
comm.on('data_updated', callback)    # callback(dict) — 完整快照
comm.on('point_changed', callback)   # callback(name, value)
comm.on('error', callback)           # callback(message)
```

界面层在 `main.py` 中桥接这些回调为 Qt Signal，分发到各页面。

### 界面层 → 通讯层（指令下行）

界面层调用通讯层的写入方法：

```python
plc.set_point(name, value)           # 按名称写入点位
plc.set_M(offset, value)             # 按偏移写入 M 继电器
plc.manual_action(action, state)     # 手动动作（按下/松开）
plc.write_power(on)                  # 快捷方法
plc.write_light(on)
plc.write_start()
plc.write_reset()
plc.write_heat(on)
plc.write_bake(on)
plc.write_motor_reset()
```

### 视觉层

```python
camera.capture()                     # 拍照，返回文件路径
vision.on('result', callback)        # callback(dict) — 推理结果
```

## 编码规范（全局）

- **所有新建变量默认值**：数值 → 0，布尔 → False，字符串/列表/字典 → "" / [] / {}，可空引用 → None
- **通讯层变量命名**：必须包含读写方式前缀/后缀
  - `r_` 只读（如 `r_voltage`）
  - `rw_` 读写（如 `rw_manual`）
  - `_ro` 只读后缀（如 `d_ro_aodian`）
- **文件大小**：自然增长，过大时分割，项目索引确保不丢失
- **配置**：`config.json` 存放在项目根目录

## 网络配置

| 设备 | IP | 端口/参数 |
|------|-----|----------|
| PLC（台达AS） | 192.35.2.5 | TCP 502, 站号 1 |
| HMI（昆仑通态） | 192.35.2.10 | TCP 502, 站号 1 |
| 风扇1/2 | `/dev/ttyS3` | 9600 8N1, 站号 1/2 |
| 相机（海康） | 192.168.2.100 | MVS SDK 直连 |

## 派活方式

主管通过 `delegate_task` 派活给子 Agent，每次提供：

1. **goal**：明确的任务目标
2. **context**：相关文件路径、当前状态、约束条件
3. **toolsets**：允许使用的工具集

### 给通讯 Agent 的 tasks 模板

```python
{
    "goal": "修复 PLC D 寄存器地址映射",
    "context": "文件: /opt/pancake_ui/core/plc.py\n当前 D_GROUPS 和 D_POINTS 数据有误……\n正确地址表: [用户提供的完整表]\n命名规范: d_ro_xxx 只读, d_rw_xxx 读写\n禁止导入: PySide6, PyQt5, PyQt6",
    "toolsets": ["terminal", "file"]
}
```

### 给界面 Agent 的 tasks 模板

```python
{
    "goal": "首页按钮接入 PLC 写入",
    "context": "文件: /opt/pancake_ui/ui/home.py, /opt/pancake_ui/main.py\n通讯层通过 main_plc 提供写入方法: set_point, write_power 等\n禁止导入: pymodbus, serial, pyserial\n禁止直接创建 ModbusTcpClient",
    "toolsets": ["terminal", "file"]
}
```

### 给视觉 Agent 的 tasks 模板

```python
{
    "goal": "实现相机拍照并保存",
    "context": "文件: /opt/pancake_ui/core/camera.py\nMVS SDK 路径: /opt/MVS\n相机 IP: 192.168.2.100\n禁止导入: PySide6, PyQt5, PyQt6",
    "toolsets": ["terminal", "file"]
}
```

## 设备信息

- 主板: BD-ARM-3588（RK3588, 8GB RAM, 64GB eMMC）
- 屏幕: MIPI-DSI 800×1280 触摸屏
- 网络: 双千兆网口（eth0 192.35.2.x, enP2p33s0 192.168.2.x）
- 桌面: startx → .xinitrc 死循环启动 main.py
- 屏幕已物理横屏 1280×800（Xorg Monitor 段 Rotate "left" + 触屏 TransformationMatrix 固化）
