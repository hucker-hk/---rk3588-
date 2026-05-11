"""
请求链引擎 — 纯后台，不依赖任何 GUI 框架。

发一条 → 等回复 → 发下一条。
超时自动跳过并报故障，支持请求间间隔。
内部用 threading.Event 做间隔。
使用回调模式与外部通信，不导入 PySide6/Qt。
"""

import time
import threading


class RequestChain:
    """通用请求链引擎。

    timeout_ms: 单次请求超时时间（由底层 socket 保证）
    gap_ms:     请求间最小间隔（0=无间隔）

    回调注册:
        chain.on('finished', callback)   # callback(name, result)
        chain.on('failed', callback)     # callback(name, error_msg)
        chain.on('idle', callback)       # callback()
    """

    def __init__(self, timeout_ms=1000, gap_ms=0):
        self._timeout = timeout_ms / 1000.0
        self._gap_ms  = gap_ms
        self._running = False
        self._queue   = []                   # [(name, fn, gap_override), ...]
        self._stopped = threading.Event()
        self._waker   = threading.Event()    # 用于立即唤醒间隔等待
        self._callbacks = {}                 # {event: [callback, ...]}

    # ── 回调系统 ────────────────────────────────────────────

    def on(self, event: str, callback):
        """注册回调。event: 'finished' | 'failed' | 'idle'"""
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def off(self, event: str, callback=None):
        """移除回调。callback=None 时清空该事件的所有回调"""
        if callback is None:
            self._callbacks.pop(event, None)
        elif event in self._callbacks:
            try:
                self._callbacks[event].remove(callback)
            except ValueError:
                pass

    def _emit(self, event: str, *args):
        """触发回调"""
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args)
            except Exception:
                pass

    # ── public API ──────────────────────────────────────────

    def set_requests(self, requests: list):
        """
        requests 格式:
            [(name, fn), ...]                 → 用默认 gap
            [(name, fn, gap_ms), ...]         → 覆盖这条的间隔

        fn 是 callable，返回任意可序列化数据。
        """
        self._queue.clear()
        for item in requests:
            if len(item) == 2:
                self._queue.append((item[0], item[1], None))
            else:
                self._queue.append(tuple(item))

    def start(self):
        if self._queue and not self._running:
            self._running = True
            self._stopped.clear()
            self._waker.clear()

    def stop(self):
        self._running = False
        self._waker.set()    # 唤醒任何正在等待的间隔

    @property
    def is_running(self):
        return self._running

    # ── 驱动循环（由外部线程调用）──────────────────────────

    def drive_one(self):
        """执行一次请求，然后按 gap 等待。由外部线程循环调用。

        调用模式:
            while chain._running:
                chain.drive_one()

        内部阻塞在 gap 等待上，使用 waker 支持立即退出。
        """
        if not self._running or not self._queue:
            return

        name, fn, gap_override = self._queue.pop(0)
        self._queue.append((name, fn, gap_override))   # 循环

        try:
            result = fn()
            self._emit('finished', name, result)
        except Exception as e:
            self._emit('failed', name, str(e))

        # 间隔等待（可被 stop 中断）
        gap = gap_override if gap_override is not None else self._gap_ms
        if gap > 0:
            self._waker.clear()
            self._waker.wait(timeout=gap / 1000.0)
