# BD 系列 ARM 嵌入式主板 快速参考

> 来源：嵌入式Linux开发快速入门指南V1.pdf (34页)
> 适用：RK3588 / RK3568 系列 | Ubuntu 20.04/22.04

---

## 1. 系统账号

| 系统 | 普通用户 | 密码 | root 密码 |
|------|----------|------|-----------|
| Ubuntu 20.04/22.04 | teamhd | (空) | root |
| Debian 10/11 | linaro | linaro | root |
| Ubuntu 18.04 | teamhd | (空) | root |

```bash
# 修改密码
sudo passwd teamhd
sudo passwd root

# SSH 允许 root 登录
sudo sed -i 's/#\?PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

---

## 2. GPIO 引脚

**RK3588 (J38 排针):**

| Pin | GPIO# | 方向设置 | 值读写 |
|-----|-------|----------|--------|
| K1  | #116  | `/sys/class/gpio/gpio116/direction` | `/sys/class/gpio/gpio116/value` |
| K2  | #125  | 同上 | 同上 |
| K3  | #135  | ... | ... |
| K4  | #27   | ... | ... |
| K5  | #152  | ... | ... |
| K6  | #153  | ... | ... |
| K7  | #154  | ... | ... |
| K8  | #155  | ... | ... |

**RK3568:**

| Pin | GPIO# |
|-----|-------|
| K1  | #88   |
| K2  | #107  |
| K3  | #89   |
| K4  | #108  |
| K5  | #90   |
| K6  | #109  |
| K7  | #91   |
| K8  | #110  |

```bash
# 测试 GPIO (以3588 K8=#155 为例)
echo 155 > /sys/class/gpio/export
echo out > /sys/class/gpio/gpio155/direction
echo 1 > /sys/class/gpio/gpio155/value    # 高电平
echo 0 > /sys/class/gpio/gpio155/value    # 低电平
cat /sys/kernel/debug/gpio                # 查看全部 IO 状态
```

**引脚编号计算公式：**

```
bank ∈ [0,4]   group: A=0, B=1, C=2, D=3   X ∈ [0,7]
number = group * 8 + X
pin = bank * 32 + number

例: GPIO0_B5 → bank=0, group=1, X=5
    number = 1*8+5 = 13, pin = 0*32+13 = 13
```

---

## 3. 显示 & 触摸

### 查看屏参

```bash
dmesg | grep mode=
xrandr
cat /var/log/Xorg.0.log
```

### 旋转屏幕 (Ubuntu 20.04)

```bash
xrandr -o left      # 左旋 90°
xrandr -o right     # 右旋 90°
xrandr -o inverted  # 180°
xrandr -o normal    # 0°
```

永久生效：创建 `/etc/X11/Xsession.d/55gnome-session_gnomerc`

### 触摸旋转 (Ubuntu 20.04)

创建/编辑 `/etc/X11/xorg.conf.d/05-touchscreen.conf`：

| 旋转 | CalibrationMatrix |
|------|-------------------|
| 正常 | `1 0 0 0 1 0 0 0 1` |
| 左旋90° | `0 -1 1 1 0 0 0 0 1` |
| 右旋90° | `0 1 0 -1 0 1 0 0 1` |
| 180° | `-1 0 1 0 -1 1 0 0 1` |

### 自定义分辨率

```bash
cvt 1920 1080 60
xrandr --newmode "1920x1080_60.00" ...参数...
xrandr --addmode DSI-1 "1920x1080_60.00"
xrandr --output DSI-1 --mode "1920x1080_60.00"
```

---

## 4. 网络

### WiFi

```bash
sudo nmcli dev wifi                          # 扫描
sudo nmcli dev wifi connect "SSID" password "密码" ifname wlan0
sudo nmcli r wifi on/off                     # 开关
```

### 静态 IP

```bash
sudo nmcli con mod "Wired connection 1" \
  ipv4.addresses "192.168.1.110" \
  ipv4.gateway "192.168.1.1" \
  ipv4.dns "8.8.8.8" \
  ipv4.method "manual"
```

### 禁用 WiFi/蓝牙

```bash
# 方法1: 删除 ko 驱动
rm -f /system/lib/modules/aic8800_*.ko
# 方法2: 注释 /etc/rc.local 中的 insmod 语句
# 方法3: 命令关闭
sudo nmcli r wifi off
sudo rfkill block bluetooth
```

### 4G 模块

```bash
# AT 指令
cat /dev/ttyUSB2 &
echo -e "ATI\r\n" > /dev/ttyUSB2
# 拨号程序: /sbin/quectel-CM
# 自启: /etc/rc.local
# 模块复位 (GPIO30)
echo 30 > /sys/class/gpio/export
echo out > /sys/class/gpio/gpio30/direction
echo 0 > /sys/class/gpio/gpio30/value; sleep 3
echo 1 > /sys/class/gpio/gpio30/value
```

### 网卡名传统命名

```bash
mv /usr/lib/udev/rules.d/80-net-setup-link.rules /usr/lib/udev/rules.d/80-net-setup-link.rules.bak
```

---

## 5. 串口 & CAN

```bash
# 串口工具
sudo apt install -y cutecom

# CAN
sudo apt install -y can-utils
ip link set can0 down
ip link set can0 type can bitrate 1000000
ip link set can0 up
cansend can0 123#DEADBEEF    # 发送
candump can0                  # 接收
```

---

## 6. 音频

**声卡：**
- `controlC0` = HDMI 音频输出 (card 0)
- `controlC1` = 板载 ES8388 音频芯片 (card 1)

```bash
# 查看声卡
aplay -l
arecord -l
pacmd list-sinks | grep -e 'name:' -e 'index:'

# 设置默认声卡
pactl set-default-sink alsa_output.platform-es8388-sound.stereo-fallback

# 调节音量 (索引号1为例)
pactl set-sink-volume 1 +5%
pactl set-sink-volume 1 50%

# 测试播放
aplay /usr/share/sounds/alsa/Rear_Right.wav
```

---

## 7. GPU / NPU / RGA

### GPU

```bash
glmark2-es2                                # 跑分
cat /sys/class/devfreq/fb000000.gpu/cur_freq  # GPU 频率
cat /sys/class/devfreq/fb000000.gpu/load      # GPU 占用率

# 高性能模式
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
echo 1000000000 | sudo tee /sys/class/devfreq/fb000000.gpu/max_freq
```

GPU 驱动: `libmali-valhall-g610-g13p0-x11-gbm_1.9-1_arm64.deb`

### NPU (RKNN)

```bash
# 查看 NPU 驱动版本
cat /sys/kernel/debug/rknpu/version
# 查看 NPU 频率
sudo cat /sys/kernel/debug/clk/clk_summary | grep clk_npu_dsu0
# RKNN 库版本
strings /usr/lib/librknnrt.so | grep version
strings /usr/bin/rknn_server | grep build
```

| 主板版本 | librknnrt | rknn_server | rknpu driver |
|----------|-----------|-------------|--------------|
| L10      | 1.4.0     | 1.4.0       | 0.8.2        |
| L12      | 1.5.0     | 1.5.0       | 0.8.8        |
| L14      | 1.5.2     | 1.5.2       | 0.9.3        |

### RGA (2D 加速)

```bash
strings /usr/lib/aarch64-linux-gnu/librga.so | grep rga_api | grep version
# 输出示例: rga_api version 1.9.3_[2]
```

---

## 8. 蓝牙

```bash
sudo rfkill unblock bluetooth    # 开启
sudo rfkill block bluetooth      # 关闭
bluetoothctl                     # 交互式调试
# 进入后: power on → scan on → scan off
```

---

## 9. RTC 时钟

```bash
# 设置时区
sudo timedatectl set-timezone Asia/Shanghai
# 手动设时间
date -s "20230303 17:10:00"
hwclock -w                       # 写入硬件 RTC
```

---

## 10. 看门狗

```bash
echo A > /dev/watchdog    # 开启，需每44秒喂一次
echo V > /dev/watchdog    # 开启，内核每22秒自动喂
wdctl                     # 查看状态和超时
```

---

## 11. 自启动 (4种方式)

| 方式 | 路径 | 适用场景 |
|------|------|----------|
| init.d | `/etc/init.d/xxx.sh` + `/etc/rcS.d/Sxxlink` | 早期启动 |
| systemd | `/etc/systemd/system/xxx.service` + `systemctl enable` | 服务类 |
| desktop | `/etc/xdg/autostart/xxx.desktop` | **Qt/GUI 程序推荐** |
| rc.local | `/etc/rc.local` (exit 0 之前) | 简单脚本 |

**Qt 程序推荐用 desktop 方式：**

```ini
# /etc/xdg/autostart/pancake.desktop
[Desktop Entry]
Type=Application
Name=Pancake UI
Exec=/opt/pancake_ui/main.py
```

---

## 12. Qt 开发

- **Qt 5.15** → 需要 Ubuntu 20.04 x86-64 主机交叉编译
- **目标板**：RK3588 / RK3568 / Ubuntu 20.04
- 支持后端：EGLFS / LinuxFB / XCB
- 环境变量：`/etc/profile.d/target_qtEnv.sh`

```bash
# 主板安装 Qt 运行库
apt install -y libqt5multimedia5 qtmultimedia5-dev libqt5quick5 qtdeclarative5-dev
```

---

## 13. 系统烧录

1. 安装驱动：双击 `DriverInstall.exe`
2. 按住主板 **uboot 按键** → DC12V 通电 → 松开
3. `RKDevTool.exe` 显示"发现一个LOADER设备" → 点击"执行"
4. 等待 2~3 分钟至"下载完成"

### U 盘刷补丁

- U 盘必须 **FAT/FAT32** 格式
- 补丁文件放 U 盘根目录
- 主板断电 → 插 U 盘 → 上电 → 等 20 秒 → 灯变红/灭 → 拔 U 盘 → 重启

---

## 14. 分区与磁盘

默认根分区 14G，可修改 `parameter.txt` 调整。

```bash
df -h          # 查看分区
lsblk
```

---

## 15. 日志管理（防磁盘满）

```bash
sudo journalctl --vacuum-size=100M    # 限制日志
sudo du -h -m /var/log               # 查看日志大小
```

---

## 16. 常用调试命令

| 功能 | 命令 |
|------|------|
| 系统信息 | `cat /etc/os-release` |
| 内核版本 | `uname -a` |
| CPU 信息 | `cat /proc/cpuinfo` |
| 内存 | `free -h` |
| 磁盘 | `df -h` |
| USB 设备 | `lsusb` |
| IP 地址 | `ip addr show` |
| 桌面环境 | `echo $XDG_CURRENT_DESKTOP` |
| 显示后端 | `echo $XDG_SESSION_TYPE` |
| 内核日志 | `dmesg` |
| 异常日志 | `journalctl -xe` |
| 显示日志 | `cat /var/log/Xorg.0.log` |
| GPU 跑分 | `glmark2-es2` |
| 查找文件 | `find ./ -name "*.sh"` (不要在/sys /proc /system下执行) |

---

## 17. 禁用/启用桌面

```bash
# 禁用桌面
sudo systemctl disable lightdm.service

# 启用桌面
sudo systemctl start lightdm.service
sudo systemctl enable lightdm.service
```

---

## 18. 禁止待机

```bash
sudo xset -dpms
sudo xset s off
```

---

## 19. 关闭图形界面

```bash
sudo systemctl set-default multi-user.target
# 恢复图形
sudo systemctl set-default graphical.target
```

---

## 20. 中文环境

```bash
echo 'LANG="zh_CN.UTF-8"' > /etc/default/locale
echo 'LANGUAGE="zh_CN:zh"' >> /etc/default/locale
locale-gen zh_CN.UTF-8

# 中文输入法
sudo apt install -y fcitx fcitx-googlepinyin
# .xprofile 添加:
# export XMODIFIERS="@im=fcitx"
# export QT_IM_MODULE="fcitx"
```

---

## 当前设备

- **型号**: DXB LP4 V10 (RK3588)
- **系统**: Ubuntu 22.04 (Xubuntu/XFCE)
- **桌面**: 已禁用 (lightdm masked)
- **屏幕**: MIPI-DSI 1280×800
- **触摸**: Goodix
- **NPU 驱动**: (需确认版本)
- **串口**: /dev/ttyS0 (风扇 Modbus)
- **网络**: eth0 + enP2p33s0 (双千兆) + wlan0 (WiFi)
- **GPIO**: 8路可用 (J38 排针)
