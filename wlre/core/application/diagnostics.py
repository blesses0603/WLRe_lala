"""有界結構化診斷；不接受任意訊息、事件內容或例外文字。"""
from collections import deque
from dataclasses import dataclass
from threading import Lock

from wlre.core.primitives import identifier


@dataclass(frozen=True)
class Diagnostic:
    component: str
    code: str
    counters: tuple[tuple[str, int | bool], ...]


class DiagnosticLog:
    def __init__(self, capacity=256, *, logger=None):
        if type(capacity) is not int or not 1 <= capacity <= 65536:
            raise ValueError('invalid_diagnostic_capacity')
        self._rows = deque(maxlen=capacity)
        self._logger = logger
        self._lock = Lock()
        self._closed = False

    def record(self, component, code, **counters):
        identifier(component)
        identifier(code)
        if len(counters) > 8:
            raise ValueError('too_many_diagnostic_counters')
        for name, value in counters.items():
            identifier(name)
            if type(value) not in (int, bool):
                raise TypeError('diagnostic_counters_must_be_numeric')
        row = Diagnostic(component, code, tuple(sorted(counters.items())))
        with self._lock:
            if self._closed:
                return
            self._rows.append(row)
        if self._logger is not None:
            try:
                self._logger.info('core component=%s code=%s counters=%s',
                                  row.component, row.code, row.counters)
            except Exception:  # noqa: BLE001 -- 記錄 sink 的任意失敗不遞迴呼叫 logging。
                with self._lock:
                    self._rows.append(Diagnostic('diagnostics', 'sink_failed', ()))

    def snapshot(self):
        with self._lock:
            return tuple(self._rows)

    def close(self):
        with self._lock:
            self._closed = True

