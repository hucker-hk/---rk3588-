# 海康威视 MV-CU060-10GC 工业相机

## 基本信息

- **型号**: MV-CU060-10GC
- **类型**: 6MP 面阵 GigE 彩色工业相机
- **传感器**: CMOS, 全局快门
- **接口**: GigE (千兆以太网)
- **IP**: 192.168.2.100
- **本机网口**: enP2p33s0, 192.168.2.1/24 (NetworkManager 固化)
- **SDK**: MVS 3.0.1 (已安装于 /opt/MVS)

## 网络配置

```
enP2p33s0 → 192.168.2.1/24 (静态, 由 NetworkManager "Wired connection 1" 管理)
相机     → 192.168.2.100
```

固化命令：
```bash
nmcli con mod "Wired connection 1" ipv4.method manual ipv4.addresses 192.168.2.1/24
```

## SDK 安装

```bash
dpkg -i MVS-3.0.1_aarch64_20251113.deb
```

环境变量 (在 ~/.bashrc 或启动脚本):
```bash
export MVCAM_SDK_PATH=/opt/MVS
export MVCAM_COMMON_RUNENV=/opt/MVS/lib
export LD_LIBRARY_PATH=/opt/MVS/lib/aarch64:$LD_LIBRARY_PATH
```

## 代码接入

`core/camera.py` — MVS SDK 直连，后台拉流，支持拍照存 JPEG。

使用方式：
```python
from core.camera import CameraController

camera = CameraController(camera_ip='192.168.2.100', net_ip='192.168.2.1')
camera.connect()          # 初始化 SDK + 连接 + 开始拉流
camera.trigger_capture()  # 拍照 → 通过 capture_saved 信号返回路径
camera.disconnect()       # 停止拉流 + 释放资源
```

## 关键目录

```
/opt/MVS/
├── bin/                # 工具 (Ip_Configurator 等)
├── lib/aarch64/        # SDK 动态库
├── Samples/aarch64/Python/  # Python 示例
│   ├── MvImport/       # Python 封装
│   ├── General/GrabImage/        # 枚举+拉流
│   ├── General/ConnectSpecCamera/ # IP 直连
│   └── General/ImageSave/        # 保存图片
└── driver/gige/        # GigE 内核驱动（当前未加载）
```

## 注意事项

- GigE 内核驱动 (gevfilter.ko) 未编译，因为缺少 5.10.198 内核头文件。SDK 在用户态工作正常。
- 相机口 MUST 是独立网段 (192.168.2.x)，不可与 PLC/HMI 的 192.35.2.x 网段混用。
- 保存 JPEG 质量 = 80，格式 = MV_Image_Jpeg。
