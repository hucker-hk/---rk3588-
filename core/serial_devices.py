"""
串口设备 Modbus RTU 控制器。
继承 RequestChain，串口 3 秒超时，请求间 10ms 间隔。

多实例共享同一个 ModbusSerialClient（按 port+baudrate 缓存），
通过 device_id 区分从站，消除 RS485 半双工总线端口锁冲突。
"""

import threading

from .request_chain import RequestChain
from pymodbus.client import ModbusSerialClient


# 站号 → 设备名映射（用于自动推导命名前缀）
_SLAVE_NAME = {1: "peel", 2: "oil"}


class SerialDeviceController(RequestChain):
    """串口设备控制器。

    通过 Modbus RTU 控制串口上挂载的设备（风扇、步进电机等）。
    每个设备有独立的站号。多个站号共享同一个物理连接，
    通过 device_id 区分从站。

    寄存器表（4区 Holding Registers，功能码 0x03）：
        寄存器0 — 只读 — 温度（揭皮=电源箱温度，抹油=从屏箱温度）
        寄存器3 — 只写 — 目标转速 0-100%
        寄存器7 — 只读 — 实际转速

    回调事件:
        'data_updated': callback(dict)  — 完整快照
        'error':        callback(msg)   — 错误消息
    """

    # ── 类级别共享客户端 ──────────────────────────────────
    # 缓存结构: {(port, baudrate): {'client': ModbusSerialClient|None,
    #                               'lock': threading.Lock,
    #                               'refcount': int}}
    _clients = {}
    _clients_lock = threading.Lock()

    def __init__(self, port, slave_id, name_base="", baudrate=9600):
        super().__init__(timeout_ms=3000, gap_ms=10)     # 串口: 3s 超时, 10ms 间隔
        self.port      = port
        self.slave     = slave_id
        self.baudrate  = baudrate
        self.name_base = name_base or _SLAVE_NAME.get(slave_id, f"dev{slave_id}")
        self._cache    = {}         # 累积本周期轮询结果
        self._joined   = False     # 本实例是否已加入共享客户端

        # 写寄存器目标值（默认 0）
        self.w_speed   = 0          # 寄存器3: w_{name_base}_speed

    @property
    def _key(self):
        """共享客户端缓存键"""
        return (self.port, self.baudrate)

    def _ensure(self):
        """确保本实例已加入共享客户端，必要时（重新）建立连接。"""
        key = self._key
        with SerialDeviceController._clients_lock:
            # 首次加入：创建缓存条目并增加引用计数
            if key not in SerialDeviceController._clients:
                SerialDeviceController._clients[key] = {
                    'client': None,
                    'lock': threading.Lock(),
                    'refcount': 0,
                }
            entry = SerialDeviceController._clients[key]

            if not self._joined:
                entry['refcount'] += 1
                self._joined = True

            # 已有可用连接
            if entry['client'] is not None and entry['client'].connected:
                return True

            # 需要（重新）建立连接
            if entry['client'] is not None:
                try:
                    entry['client'].close()
                except Exception:
                    pass
                entry['client'] = None

            try:
                client = ModbusSerialClient(
                    port=self.port, baudrate=self.baudrate,
                    bytesize=8, parity='N', stopbits=1, timeout=3.0)
                ok = client.connect()
                if ok:
                    entry['client'] = client
                    return True
            except Exception:
                pass

        return False

    def _get_entry(self):
        """获取共享客户端条目，检查连接状态。"""
        key = self._key
        with SerialDeviceController._clients_lock:
            entry = SerialDeviceController._clients.get(key)
            if entry is None or entry['client'] is None or not entry['client'].connected:
                raise ConnectionError(f"设备站号={self.slave} 未连接")
            return entry

    def _read(self, addr, count=1):
        if not self._ensure():
            raise ConnectionError(f"设备站号={self.slave} 未连接")
        entry = self._get_entry()
        client = entry['client']
        with entry['lock']:
            try:
                rr = client.read_holding_registers(addr, count=count, device_id=self.slave)
            except Exception as e:
                self._invalidate_client()
                raise ConnectionError(f"串口设备{self.slave} 读寄存器异常: {e}")
            if rr.isError():
                raise IOError(str(rr))
            return rr.registers

    def _write(self, addr, value):
        if not self._ensure():
            raise ConnectionError(f"设备站号={self.slave} 未连接")
        entry = self._get_entry()
        client = entry['client']
        with entry['lock']:
            try:
                rr = client.write_register(addr, int(value), device_id=self.slave)
            except Exception as e:
                self._invalidate_client()
                raise ConnectionError(f"串口设备{self.slave} 写寄存器异常: {e}")
            if rr.isError():
                raise IOError(str(rr))

    def _invalidate_client(self):
        """标记共享连接为失效，下次 _ensure 将重新连接。"""
        key = self._key
        with SerialDeviceController._clients_lock:
            entry = SerialDeviceController._clients.get(key)
            if entry is not None:
                try:
                    if entry['client'] is not None:
                        entry['client'].close()
                except Exception:
                    pass
                entry['client'] = None

    # ── 请求链 ─────────────────────────────────────────────

    def configure_polling(self):
        """配置轮询：只读寄存器0(温度)和寄存器7(实际转速)。"""
        # 清除旧回调，防止多次调用导致重复
        self.off('finished')
        self.off('failed')

        nb = self.name_base

        def read_temp():
            raw = self._read(0)[0]
            return raw - 40

        def read_actual_speed():
            return self._read(7)[0]

        self.set_requests([
            (f'r_{nb}_temp',         read_temp),
            (f'r_{nb}_actual_speed', read_actual_speed),
        ])
        self.on('finished', self._collect)
        self.on('failed', self._on_fail)

    def _collect(self, name, value):
        """收集本周期轮询结果，集齐后推送完整快照。"""
        self._cache[name] = value
        if len(self._cache) >= 2:
            snapshot = dict(self._cache)
            nb = self.name_base
            temp = snapshot.get(f'r_{nb}_temp', 0)
            snapshot[f'r_{nb}_temp_fault'] = (temp == 128)
            snapshot[f'w_{nb}_speed'] = self.w_speed
            self._emit('data_updated', snapshot)
            self._cache.clear()

    def _on_fail(self, name, error):
        self._emit('error', f"串口设备{self.slave} {name}: {error}")

    # ── 写入 ───────────────────────────────────────────────

    def set_speed(self, pct: int):
        """设置目标转速比例 0-100%，写入寄存器3。"""
        val = max(0, min(100, pct))
        self.w_speed = val
        self._write(3, val)

    def disconnect(self):
        """断开连接。引用计数归零时才真正关闭物理连接。"""
        self.stop()
        key = self._key
        with SerialDeviceController._clients_lock:
            if self._joined:
                entry = SerialDeviceController._clients.get(key)
                if entry is not None:
                    entry['refcount'] -= 1
                    if entry['refcount'] <= 0:
                        try:
                            if entry['client'] is not None:
                                entry['client'].close()
                        except Exception:
                            pass
                        del SerialDeviceController._clients[key]
                self._joined = False

    def run(self):
        """驱动循环：在后台线程中持续执行请求链。"""
        while self._running:
            self.drive_one()
