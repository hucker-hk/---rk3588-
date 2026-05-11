"""
海康 MV-CU060-10GC 相机模块 — MVS SDK 直连 v2。

通过 GigE 连接到指定 IP 的相机，后台持续拉流。
支持 PLC 触发拍照（保存 JPEG），通过 Qt 信号上报帧和状态。
若 MVS SDK 不可用则降级为 stub。
"""

import os
import sys
import time
import threading
from ctypes import *
from datetime import datetime


# ── MVS SDK 导入 ──────────────────────────────────────────
try:
    mvs_path = '/opt/MVS/Samples/aarch64/Python/MvImport'
    if mvs_path not in sys.path:
        sys.path.insert(0, mvs_path)
    from MvCameraControl_class import *
    HAS_MVS = True
except Exception:
    HAS_MVS = False


# ── 相机控制器 ────────────────────────────────────────────

class CameraController:
    """MVS SDK 相机控制器。

    后台线程持续拉流，通过信号上报状态和帧。
    拍照时使用当前帧（延迟释放，确保缓冲区有效）。

    信号:
        frame_ready(dict)         {'data': bytes, 'w': int, 'h': int, 'fn': int}
        status_changed(dict)      {'connected': bool, 'fps': float, 'resolution': str}
        capture_saved(str)        拍照文件保存路径
        error_occurred(str)       异常信息
    """

    def __init__(self, camera_ip='192.168.2.100', net_ip='192.168.2.1',
                 save_dir='/userdata/camera', parent=None):
        super().__init__(parent)
        self._camera_ip  = camera_ip
        self._net_ip     = net_ip
        self._save_dir   = save_dir
        self._cam        = None
        self._running    = False
        self._thread     = None
        self._lock       = threading.Lock()
        self._latest_frame = None    # MV_FRAME_OUT (held until next frame or disconnect)
        self._latest_info  = {}      # {w, h, fn, pixel_type, data}
        self._connected  = False
        self._fps        = 0.0
        self._resolution = ''

    # ── 连接 / 断开 ───────────────────────────────────────

    def connect(self) -> bool:
        """初始化 SDK、连接相机、启动拉流线程。"""
        if not HAS_MVS:
            self._emit('error_occurred', "MVS SDK 不可用")
            self._emit('status_changed', self.get_status())
            return False

        os.makedirs(self._save_dir, exist_ok=True)

        try:
            ret = MvCamera.MV_CC_Initialize()
            if ret != 0:
                self._emit('error_occurred', f"SDK 初始化失败 ret=0x{ret:x}")
                self._emit('status_changed', self.get_status())
                return False

            # 按 IP 直连
            stDevInfo = MV_CC_DEVICE_INFO()
            stGigEDev = MV_GIGE_DEVICE_INFO()

            parts = self._camera_ip.split('.')
            stGigEDev.nCurrentIp = ((int(parts[0]) << 24) |
                                     (int(parts[1]) << 16) |
                                     (int(parts[2]) << 8) |
                                     int(parts[3]))

            net_parts = self._net_ip.split('.')
            stGigEDev.nNetExport = ((int(net_parts[0]) << 24) |
                                     (int(net_parts[1]) << 16) |
                                     (int(net_parts[2]) << 8) |
                                     int(net_parts[3]))

            stDevInfo.nTLayerType = MV_GIGE_DEVICE
            stDevInfo.SpecialInfo.stGigEInfo = stGigEDev

            self._cam = MvCamera()

            ret = self._cam.MV_CC_CreateHandle(stDevInfo)
            if ret != 0:
                raise RuntimeError(f"创建句柄失败 ret=0x{ret:x}")

            ret = self._cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
            if ret != 0:
                raise RuntimeError(f"打开设备失败 ret=0x{ret:x}")

            # 优化网络包大小
            if stDevInfo.nTLayerType == MV_GIGE_DEVICE:
                nPacketSize = self._cam.MV_CC_GetOptimalPacketSize()
                if int(nPacketSize) > 0:
                    self._cam.MV_CC_SetIntValue("GevSCPSPacketSize", nPacketSize)

            # 关闭触发模式（自由拉流）
            self._cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)

            # 获取分辨率
            width_val = MVCC_INTVALUE()
            height_val = MVCC_INTVALUE()
            self._cam.MV_CC_GetIntValue("Width", width_val)
            self._cam.MV_CC_GetIntValue("Height", height_val)
            self._resolution = f"{width_val.nCurValue}x{height_val.nCurValue}"

            ret = self._cam.MV_CC_StartGrabbing()
            if ret != 0:
                raise RuntimeError(f"开始拉流失败 ret=0x{ret:x}")

            self._connected = True

        except Exception as e:
            self._connected = False
            self._emit('error_occurred', f"相机连接异常: {e}")
            self._cleanup_cam()
            self._emit('status_changed', self.get_status())
            return False

        self._running = True
        self._thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._thread.start()

        self._emit('status_changed', self.get_status())
        return True

    def disconnect(self):
        """停止拉流并释放相机。"""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        with self._lock:
            self._free_latest_frame()

        self._cleanup_cam()
        self._connected = False
        self._emit('status_changed', self.get_status())

    def _cleanup_cam(self):
        if self._cam is None:
            return
        try:
            self._cam.MV_CC_StopGrabbing()
        except Exception:
            pass
        try:
            self._cam.MV_CC_CloseDevice()
        except Exception:
            pass
        try:
            self._cam.MV_CC_DestroyHandle()
        except Exception:
            pass
        self._cam = None

    def _free_latest_frame(self):
        """释放当前持有的帧缓冲区。"""
        if self._cam is not None and self._latest_frame is not None:
            try:
                self._cam.MV_CC_FreeImageBuffer(self._latest_frame)
            except Exception:
                pass
        self._latest_frame = None
        self._latest_info = {}

    # ── 后台拉流 ─────────────────────────────────────────

    def _stream_loop(self):
        """后台线程：持续从相机取帧。"""
        frame_count = 0
        t_start = time.time()

        while self._running:
            if self._cam is None:
                time.sleep(0.5)
                continue

            # 分配新的帧缓冲区
            stOutFrame = MV_FRAME_OUT()
            memset(byref(stOutFrame), 0, sizeof(stOutFrame))

            ret = self._cam.MV_CC_GetImageBuffer(stOutFrame, 1000)

            if ret == 0 and stOutFrame.pBufAddr is not None:
                fi = stOutFrame.stFrameInfo
                buf_size = fi.nFrameLen if fi.nFrameLen > 0 else fi.nWidth * fi.nHeight * 3

                # 复制像素数据到 Python bytes
                try:
                    src_ptr = cast(stOutFrame.pBufAddr, POINTER(c_ubyte * buf_size))
                    raw_data = bytes(src_ptr.contents)
                except Exception:
                    raw_data = b''

                info = {
                    'data': raw_data,
                    'w': fi.nWidth,
                    'h': fi.nHeight,
                    'fn': fi.nFrameNum,
                    'pixel_type': fi.enPixelType,
                    'frame_len': fi.nFrameLen,
                }

                # 替换 latest_frame（先释放旧帧）
                with self._lock:
                    self._free_latest_frame()
                    self._latest_frame = stOutFrame   # 保持引用防止 GC
                    self._latest_info = info
                    self._connected = True

                frame_count += 1
                if frame_count % 30 == 0:
                    elapsed = time.time() - t_start
                    if elapsed > 0:
                        self._fps = frame_count / elapsed

                self._emit('frame_ready', info)

            else:
                # 取帧失败，释放本次的空 stOutFrame
                if stOutFrame.pBufAddr is not None:
                    try:
                        self._cam.MV_CC_FreeImageBuffer(stOutFrame)
                    except Exception:
                        pass
                time.sleep(0.1)

    # ── 拍照 ──────────────────────────────────────────────

    def trigger_capture(self):
        """PLC 触发拍照。保存当前帧为 JPEG。"""
        filepath = self._save_jpeg()
        if filepath:
            self._emit('capture_saved', filepath)
        return filepath

    def capture(self):
        """拍照，返回文件路径或 None。"""
        return self._save_jpeg()

    def _save_jpeg(self):
        """使用 MVS SDK 保存当前帧为 JPEG。"""
        if not HAS_MVS or self._cam is None:
            self._emit('error_occurred', "相机未就绪")
            return None

        with self._lock:
            frame = self._latest_frame
            info = dict(self._latest_info)

        if frame is None or info.get('data') is None:
            self._emit('error_occurred', "无可用帧")
            return None

        ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        filename = f"pancake_{ts}.jpg"
        filepath = os.path.join(self._save_dir, filename)

        try:
            stSaveParam = MV_SAVE_IMAGE_TO_FILE_PARAM_EX()
            memset(byref(stSaveParam), 0, sizeof(stSaveParam))

            stSaveParam.enPixelType = info['pixel_type']
            stSaveParam.nWidth  = info['w']
            stSaveParam.nHeight = info['h']
            stSaveParam.nDataLen = info.get('frame_len', 0)
            stSaveParam.pData = frame.pBufAddr   # 指向原始 SDK 缓冲区
            stSaveParam.enImageType = MV_Image_Jpeg
            stSaveParam.pcImagePath = create_string_buffer(filepath.encode())
            stSaveParam.iMethodValue = 1
            stSaveParam.nQuality = 80

            ret = self._cam.MV_CC_SaveImageToFileEx(stSaveParam)
            if ret != 0:
                self._emit('error_occurred', f"保存 JPEG 失败 ret=0x{ret:x}")
                return None

        except Exception as e:
            self._emit('error_occurred', f"拍照异常: {e}")
            return None

        return filepath

    # ── 状态 ──────────────────────────────────────────────

    def get_status(self):
        return {
            'connected':  self._connected and HAS_MVS,
            'fps':        round(self._fps, 1),
            'resolution': self._resolution or 'N/A',
        }

    def is_connected(self) -> bool:
        return self._connected and HAS_MVS
