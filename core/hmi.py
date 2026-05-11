"""
昆仑通态触摸屏 (HMI) — Modbus TCP 客户端。
HMI 是 Modbus 服务端，所有寄存器在 4 区（保持寄存器），只读。

寄存器映射（十进制地址）：
  0:   设备名称   (字符串, 最长100字节)
  150: 地区       (字符串, 最长100字节)
  200: 天气状况   (字符串, 最长100字节)
  250: 气温       (16位整数)
  300: 物联网信息 (字符串, 最长100字节)
"""

import threading

from .request_chain import RequestChain
from pymodbus.client import ModbusTcpClient

# 寄存器定义
HMI_REG = {
    'device':  0,    # 设备名称
    'region':  150,  # 地区
    'weather': 200,  # 天气状况
    'temp':    250,  # 气温 (16位)
    'iot':     300,  # 物联网信息
}

MAX_STR_BYTES = 100  # 字符串最大字节数
MAX_STR_REGS = 50    # 对应的寄存器数 (100 bytes / 2)


class KunlunHMI(RequestChain):
    """昆仑通态 HMI 通讯适配器。

    每轮读取 5 个寄存器段，30 秒间隔。

    回调事件:
        'data_updated': callback(dict)  # {'device':str, ...}
        'error':        callback(msg)
    """

    

    def __init__(self, host, port=502, slave=1):
        super().__init__(timeout_ms=1000, gap_ms=1000)  # 1s 间隔
        self.host  = host
        self.port  = port
        self.slave = slave
        self._client = None
        self._cache  = {}
        self._lock   = threading.Lock()

    def _ensure(self):
        if self._client is not None and self._client.connected:
            return True
        try:
            if self._client is not None: self._client.close()
            self._client = None
            self._client = ModbusTcpClient(
                host=self.host, port=self.port, timeout=1.0)
            if self._client.connect():
                return True
        except Exception:
            pass
        self._client = None
        return False

    def _read_str(self, start, length=MAX_STR_REGS, encoding='gbk'):
        """读保持寄存器，解码为字符串。默认 GBK 支持中文。"""
        with self._lock:
            if not self._ensure():
                raise ConnectionError("HMI 未连接")
            try:
                rr = self._client.read_holding_registers(
                    start, count=length, device_id=self.slave)
            except Exception as e:
                self._close_client()
                raise ConnectionError(f"HMI 读寄存器异常: {e}")
            if rr.isError():
                raise IOError(str(rr))
            bytes_data = b''.join(
                r.to_bytes(2, 'little') for r in rr.registers)
            return bytes_data.decode(encoding, errors='replace').strip('\x00').strip()

    def _read_int(self, start):
        """读单个 16 位整数"""
        with self._lock:
            if not self._ensure():
                raise ConnectionError("HMI 未连接")
            try:
                rr = self._client.read_holding_registers(
                    start, count=1, device_id=self.slave)
            except Exception as e:
                self._close_client()
                raise ConnectionError(f"HMI 读寄存器异常: {e}")
            if rr.isError():
                raise IOError(str(rr))
            return rr.registers[0]

    # ── 请求链 ─────────────────────────────────────────────

    def configure_polling(self):
        """配置 5 个读取请求"""
        self.off('finished')
        self.off('failed')

        self.set_requests([
            ('device',  lambda: self._read_str(HMI_REG['device'])),
            ('region',  lambda: self._read_str(HMI_REG['region'])),
            ('weather', lambda: self._read_str(HMI_REG['weather'])),
            ('temp',    lambda: self._read_int(HMI_REG['temp'])),
            ('iot',     lambda: self._read_str(HMI_REG['iot'])),
        ])
        self.on('finished', self._collect)
        self.on('failed', self._on_fail)

    def _collect(self, name, value):
        self._cache[name] = value
        if len(self._cache) >= 5:
            self._emit('data_updated', dict(self._cache))
            self._cache.clear()

    def _on_fail(self, name, error):
        self._emit('error', f'HMI {name}: {error}')

    def disconnect(self):
        self.stop()
        if self._client:
            self._client.close()
            self._client = None

    def run(self):
        """驱动循环：在后台线程中持续执行请求链。"""
        while self._running:
            self.drive_one()
