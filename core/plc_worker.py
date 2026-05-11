"""
台达 AS 系列 PLC — Modbus TCP Worker (QObject)
==============================================
运行在独立 QThread 中，所有 Modbus IO 在此线程执行，
UI 线程零阻塞。

架构：
  UI 线程                       Worker 线程 (QThread)
  ────────                      ──────────────────────
  按钮点击                        _process_next() 循环
    emit write_xxx_request         │
      → 入队 (deque)               ├─ 取队首请求
                                   ├─ Modbus IO (connect/read/write)
                                   ├─ emit 结果信号 → UI
                                   └─ QTimer.singleShot(0, _process_next)
                                       ↑ 无固定间隔，上一个完立刻下一个

多核：Qt 自动将 QThread 分配到不同 CPU 核，无需手动设置亲缘性。
多个 PLC 可各建独立 QThread + Worker，真正多核并行。

关键保证：
- UI 线程绝不调用 socket/pymodbus
- Worker 线程绝不操作 UI 控件
- 不用 time.sleep() — 用 QTimer.singleShot 延迟
- 不用忙等循环 — Qt 事件循环驱动
"""

from collections import deque
from PySide6.QtCore import QObject, Signal, QTimer
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException
import time


class PlcWorker(QObject):
    """Modbus TCP 通讯 Worker。

    使用方式：
        worker = PlcWorker(host, port, slave, parse_fn=parse_snapshot)
        worker.set_read_config(...)
        thread = QThread()
        worker.moveToThread(thread)
        worker.write_coil_request.connect(worker.write_coil)   # 槽在 Worker 线程执行
        worker.data_updated.connect(ui_on_data)                # 信号回 UI 线程
        thread.started.connect(worker.start)
        thread.start()
    """

    # ── 发往 UI 线程的信号 ────────────────────────────────
    data_updated = Signal(dict)           # 完整扫描周期快照 {name: value, ...}
    connection_changed = Signal(bool)     # 连接状态变化
    error_occurred = Signal(str)          # 错误消息
    write_done = Signal(str, bool)        # 写入结果 (点位名, 是否成功)

    # ── UI 发来的写入请求信号 ──────────────────────────────
    write_coil_request = Signal(int, bool)       # (Modbus地址, 值)
    write_register_request = Signal(int, int)    # (Modbus地址, 值)
    write_point_request = Signal(str, object)    # (点名称, 值) — 由 parse_fn 反向解析

    def __init__(self, host='192.168.1.10', port=502, slave=1,
                 parse_fn=None, parent=None):
        """
        Args:
            host: PLC IP 地址
            port: Modbus TCP 端口
            slave: 站号
            parse_fn: callable(raw_cache) -> snapshot_dict
                      把一轮扫描的原始数据 {name: raw_data} 解析为命名快照。
        """
        super().__init__(parent)
        self.host = host
        self.port = port
        self.slave = slave
        self._parse_fn = parse_fn

        self._client = None
        self._connected = False
        self._running = False
        self._last_connect_fail = 0.0

        # ── 请求队列 ──
        # 元素格式:
        #   ('read', name, 'coils'|'discrete'|'hr', addr, count)
        #   ('write_coil', addr, value)
        #   ('write_register', addr, value)
        self._queue = deque()

        # 读请求模板: [(name, type, addr, count), ...]
        self._read_configs = []

        # 当前扫描周期状态
        self._cycle_results = {}    # {name: raw_data_or_None}
        self._cycle_total = 0       # 本周期总读请求数
        self._cycle_all_failed = True

    # ═══════════════════════════════════════════════════════
    # 配置
    # ═══════════════════════════════════════════════════════

    def set_read_config(self, configs: list):
        """设置读请求模板。

        configs: [(name, type, start_addr, count), ...]
          name:  请求标识 (如 'X', 'Y', 'd_grp_0_6')
          type:  'coils' | 'discrete' | 'hr'
        """
        self._read_configs = configs

    def _refill_queue(self):
        """用读请求模板重新填满队列（标记新扫描周期开始）。"""
        for name, rtype, addr, count in self._read_configs:
            self._queue.append(('read', name, rtype, addr, count))
        self._cycle_total = len(self._read_configs)
        self._cycle_results.clear()
        self._cycle_all_failed = True

    # ═══════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════

    def start(self):
        """启动 Worker（连接到 QThread.started 信号，在 Worker 线程执行）。"""
        self._running = True
        self._refill_queue()
        # 用 QTimer.singleShot(0) 而非直接调用，把首次执行交给事件循环
        QTimer.singleShot(0, self._process_next)

    def stop(self):
        """停止 Worker。"""
        self._running = False
        self._close()

    # ═══════════════════════════════════════════════════════
    # 写入槽（UI 线程 emit 信号 → Worker 线程执行）
    # ═══════════════════════════════════════════════════════

    def write_coil(self, addr: int, value: bool):
        """写线圈 — 插入队首，写优先于读。"""
        self._queue.appendleft(('write_coil', addr, value))

    def write_register(self, addr: int, value: int):
        """写保持寄存器 — 插入队首。"""
        self._queue.appendleft(('write_register', addr, value))

    def write_point(self, name: str, addr: int, value, region: str = 'coil'):
        """写命名点位（已知 Modbus 地址和区域）。"""
        self._queue.appendleft(('write_point', name, addr, value, region))

    # ═══════════════════════════════════════════════════════
    # 连接管理（仅在 Worker 线程调用）
    # ═══════════════════════════════════════════════════════

    def _ensure_connected(self) -> bool:
        """确保 TCP 连接有效。带 10 秒冷却防重连风暴。"""
        # 已有有效连接
        if self._client is not None and self._client.connected:
            return True

        # 10 秒冷却
        now = time.monotonic()
        if now - self._last_connect_fail < 10.0:
            return False

        was = self._connected

        # 先关闭旧连接
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass

        # 尝试连接
        try:
            self._client = ModbusTcpClient(
                self.host, self.port, timeout=1.0)
            self._connected = self._client.connect()
        except Exception:
            self._connected = False

        if not self._connected:
            self._last_connect_fail = now
            self._client = None

        if was != self._connected:
            self.connection_changed.emit(self._connected)

        return self._connected

    def _close(self):
        """安全关闭连接。"""
        self._connected = False
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    # ═══════════════════════════════════════════════════════
    # 核心驱动：逐个处理请求
    # ═══════════════════════════════════════════════════════

    def _process_next(self):
        """处理队列中的下一个请求。

        设计要点：
        - 不用 while 循环 + 递归：用 QTimer.singleShot(0, self._process_next)
        - 每次处理完一个请求后，控制权还给 Qt 事件循环
        - Worker 线程能在此期间处理停止信号、新的写入请求
        - 不会导致调用栈无限增长
        - 上一个请求完成（成功或失败）后立即处理下一个，零固定间隔
        """
        if not self._running:
            return

        # ── 队列空 → 当前扫描周期完成 → 发射快照，开始新周期 ──
        if not self._queue:
            self._finish_cycle()
            self._refill_queue()
            if not self._queue:
                return  # 读配置为空，不再继续
            # 如果本轮全部失败，延迟 1.5 秒再开始下一轮
            # （用 QTimer.singleShot，不阻塞事件循环）
            if self._cycle_all_failed:
                QTimer.singleShot(1500, self._process_next)
                return

        # ── 取队首请求 ──
        req = self._queue.popleft()
        req_type = req[0]

        try:
            if req_type == 'read':
                self._do_read(req)
            elif req_type == 'write_coil':
                self._do_write_coil(req)
            elif req_type == 'write_register':
                self._do_write_register(req)
            elif req_type == 'write_point':
                self._do_write_point(req)
        except Exception as e:
            self.error_occurred.emit(f"请求异常: {e}")

        # ── 立即安排下一个请求（零间隙）──
        QTimer.singleShot(0, self._process_next)

    # ═══════════════════════════════════════════════════════
    # 读请求处理
    # ═══════════════════════════════════════════════════════

    def _do_read(self, req):
        """处理单个读请求。"""
        _, name, rtype, addr, count = req

        if not self._ensure_connected():
            self._cycle_results[name] = None
            return

        try:
            if rtype == 'coils':
                rr = self._client.read_coils(
                    addr, count=count, device_id=self.slave)
                if rr.isError():
                    raise ConnectionException(str(rr))
                data = [bool(b) for b in rr.bits[:count]]

            elif rtype == 'discrete':
                rr = self._client.read_discrete_inputs(
                    addr, count=count, device_id=self.slave)
                if rr.isError():
                    raise ConnectionException(str(rr))
                data = [bool(b) for b in rr.bits[:count]]

            elif rtype == 'hr':
                rr = self._client.read_holding_registers(
                    addr, count=count, device_id=self.slave)
                if rr.isError():
                    raise ConnectionException(str(rr))
                data = list(rr.registers)

            else:
                self._cycle_results[name] = None
                return

            self._cycle_results[name] = data
            self._cycle_all_failed = False

        except (ConnectionException, OSError) as e:
            self._close()
            self._cycle_results[name] = None
        except Exception as e:
            self.error_occurred.emit(f"读取 {name} 失败: {e}")
            self._cycle_results[name] = None

    # ═══════════════════════════════════════════════════════
    # 写请求处理
    # ═══════════════════════════════════════════════════════

    def _do_write_coil(self, req):
        """处理写线圈请求。"""
        _, addr, value = req
        label = f"coil_{addr}"
        try:
            if not self._ensure_connected():
                self.write_done.emit(label, False)
                return
            rr = self._client.write_coil(addr, value, device_id=self.slave)
            if rr.isError():
                raise ConnectionException(str(rr))
            self.write_done.emit(label, True)
        except (ConnectionException, OSError) as e:
            self._close()
            self.write_done.emit(label, False)
        except Exception as e:
            self.error_occurred.emit(f"写线圈 {addr}: {e}")
            self.write_done.emit(label, False)

    def _do_write_register(self, req):
        """处理写寄存器请求。"""
        _, addr, value = req
        label = f"reg_{addr}"
        try:
            if not self._ensure_connected():
                self.write_done.emit(label, False)
                return
            rr = self._client.write_register(addr, value, device_id=self.slave)
            if rr.isError():
                raise ConnectionException(str(rr))
            self.write_done.emit(label, True)
        except (ConnectionException, OSError) as e:
            self._close()
            self.write_done.emit(label, False)
        except Exception as e:
            self.error_occurred.emit(f"写寄存器 {addr}: {e}")
            self.write_done.emit(label, False)

    def _do_write_point(self, req):
        """处理命名点位写入。"""
        _, name, addr, value, region = req
        try:
            if not self._ensure_connected():
                self.write_done.emit(name, False)
                return
            if region == 'coil':
                rr = self._client.write_coil(addr, value, device_id=self.slave)
            else:
                rr = self._client.write_register(addr, value, device_id=self.slave)
            if rr.isError():
                raise ConnectionException(str(rr))
            self.write_done.emit(name, True)
        except (ConnectionException, OSError) as e:
            self._close()
            self.write_done.emit(name, False)
        except Exception as e:
            self.error_occurred.emit(f"写入 {name}: {e}")
            self.write_done.emit(name, False)

    # ═══════════════════════════════════════════════════════
    # 周期完成
    # ═══════════════════════════════════════════════════════

    def _finish_cycle(self):
        """一轮扫描完成，调用解析函数生成快照并发射。"""
        if self._parse_fn is not None:
            try:
                snapshot = self._parse_fn(self._cycle_results)
                self.data_updated.emit(snapshot)
            except Exception as e:
                self.error_occurred.emit(f"快照解析失败: {e}")
        else:
            # 无解析函数时直接发射原始数据
            self.data_updated.emit(dict(self._cycle_results))
