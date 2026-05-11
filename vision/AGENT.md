# 视觉 Agent — 全自动煎饼机

## 职责

- 负责相机拍照、图像采集
- 负责视觉推理（RKNN NPU，待照片积累后开发）
- **禁止**导入 PySide6 / PyQt5 / PyQt6
- **禁止**直接操作 Modbus / 串口

## 管辖文件

```
vision/__init__.py     — 包初始化
vision/inference.py    — 推理模块（RKNN，待开发）
core/camera.py         — 海康相机驱动（MVS SDK）
```

## 技术栈

- **相机**：海康 MVS SDK 3.0.1（已安装在 `/opt/MVS`）
- **推理**：RKNN（瑞芯微 NPU 工具链，待开发）
- **图像处理**：OpenCV（按需引入）
- **无 Qt 依赖**

## 相机信息

| 项目 | 值 |
|------|-----|
| 型号 | 海康 MV-CU060-10GC（600万像素） |
| 连接 | 网口直连 |
| IP | 192.168.2.100 |
| SDK 路径 | `/opt/MVS` |
| SDK 版本 | 3.0.1 |

## 接口契约

### 数据上行（给主管/界面）

```python
# 视觉层通过回调推送结果
camera.on('capture_done', callback)     # callback(file_path) — 拍照完成
camera.on('error', callback)            # callback(message)
vision.on('result', callback)           # callback(dict) — 推理结果
```

### 指令下行（界面调用）

```python
camera.capture()                        # 触发拍照，完成后回调
vision.analyze(file_path)               # 对图片推理，完成后回调
```

## 编码规范

- 变量默认值：数值 → 0，布尔 → False，字符串 → ""，列表 → []，字典 → {}，引用 → None
- 文件大小自然增长
- 回调模式：`on('event', callback)` / `off('event')` / `_emit('event', *args)`

## 当前状态

- `camera.py` 已连接海康相机，可实现拍照功能
- `vision/inference.py` 待照片积累后基于 RKNN 开发
- 视觉结果通过回调传给主管/界面，不在 visual 层做 UI 展示

## 禁止事项

- ❌ `from PySide6 import ...`
- ❌ `from PyQt5 import ...`
- ❌ `from PyQt6 import ...`
- ❌ `from pymodbus import ...`
- ❌ `import serial` / `import pyserial`
- ❌ 任何 Qt Signal/Slot/QObject
- ❌ 直接操作 UI 文件
- ❌ 导入 `ui/` 或 `core/plc.py`、`core/hmi.py`、`core/serial_devices.py`
