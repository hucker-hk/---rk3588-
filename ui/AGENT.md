# 界面 Agent — 全自动煎饼机

## 职责

- 负责全部 GUI 界面的开发、布局、样式、交互
- 负责 `main.py` 桥接层（通讯回调 → Qt Signal → UI 更新）
- **禁止**直接操作 Modbus、串口、相机

## 管辖文件

```
ui/__init__.py
ui/home.py            — 首页（电源、照明、生产状态、底部按钮）
ui/manual.py          — 手动操作页
ui/settings.py        — 设置页
ui/status.py          — 设备状态页
ui/alarms.py          — 报警记录页
ui/alarm_active.py    — 当前报警页
ui/about.py           — 关于页
ui/vision.py          — 视觉页面
ui/widgets/__init__.py
ui/widgets/base_page.py   — 页面基类
ui/widgets/alarm_popup.py — 报警弹窗
ui/widgets/status_dot.py  — 状态指示灯
ui/widgets/value_card.py  — 数值卡片
main.py               — 入口 + Qt 桥接层
```

## 技术栈

- **PySide6**（唯一 GUI 框架）
- **Qt Signal / Slot**（主线程通信）
- **禁止**导入 pymodbus、serial、pyserial、MVS SDK 等通讯/Vision 库

## 屏幕配置

- 分辨率：1280×800（横屏）
- 方向：已通过 Xorg Monitor 段 `Rotate "left"` 固化，**不要再做任何旋转操作**
- 触屏：TransformationMatrix 已固化，**不要再改**
- 风格：统一暗色主题
- 运行：全屏（`showFullScreen()`），无 Ubuntu 桌面

## 标题栏规范（公共组件）

- 左侧：返回键（emoji）+ 当前温度
- 中间：页面标题
- 右侧：天气 emoji + WiFi emoji + 日期时间
- 首页模式下返回键替换为：电源按钮 + 照明按钮 + 相机按钮 + 菜单按钮
- 单根分线：M50 许可信号，0 = 红色，1 = 绿色
- 字体：加大
- 公共标题栏无背景
- 设备名仅在主页标题右侧小字显示
- 周几只显示数字，不显示"周"字

## 首页布局（1280×800）

- 左栏：电源状态
- 中左：物联网信息（水平居中）
- 中右：生产状态
- 右栏：生产数据 + 电机位置
- 底部：6 按钮（手动、设置、复位 M40、烤盘 M52、加热 M42、启动 M41）

## 桥接模式 (`main.py`)

```python
# 主线程创建 Qt Application
# 后台线程运行通讯层
# 通讯回调 → Qt Signal 转换

# 示例：PLC 数据更新桥接
plc.on('data_updated', self._on_plc_data)
plc.on('point_changed', self._on_point_change)
plc.on('error', self._on_comm_error)

def _on_plc_data(self, snapshot):
    # 通过 Qt Signal 安全传递到主线程
    self.plc_data_signal.emit(snapshot)
```

## 数据绑定

- 首页电源/照明按钮状态 → `plc.set_point("m_rw_power", ...)`
- 首页功能按钮 → 对应 `plc.write_*()` 方法
- 手动页按钮按下 → `plc.manual_action(name, True)`
- 手动页按钮松开 → `plc.manual_action(name, False)`
- 从 PLC/HMI 快照读取数据显示，不要直接调用通讯 API 轮询

## 编码规范

- 变量默认值：数值 → 0，布尔 → False，字符串 → ""，列表 → []，字典 → {}，引用 → None
- 文件大小自然增长，过大时分割
- 配置从 `config.json` 读取

## 禁止事项

- ❌ `from pymodbus import ...`
- ❌ `import serial` / `import pyserial`
- ❌ 直接创建 `ModbusTcpClient`
- ❌ 任何 `xrandr` 旋转、`QT_QPA_*` 旋转环境变量
- ❌ 修改 Xorg 配置文件
- ❌ 修改触屏 TransformationMatrix
