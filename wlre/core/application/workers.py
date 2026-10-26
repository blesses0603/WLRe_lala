"""背景工作登記與合作式取消；不依賴 GUI，也不強制終止執行緒。"""
import math
import time
from threading import Thread

from wlre.core.application.modules import LifecycleError
from wlre.core.primitives import Owned


class WorkerGroup(Owned):
    def __init__(self):
        super().__init__()
        self._workers = {}
        self._closing = False
        self._cancel_failed = False

    def _prune(self):
        self._workers = {thread: cancel for thread, cancel in self._workers.items()
                         if thread.is_alive()}

    def running(self, name):
        self.assert_owner()
        self._prune()
        return any(thread.name == name for thread in self._workers)

    def start(self, worker, request_stop):
        self.assert_owner()
        if self._closing:
            raise LifecycleError('worker_group_closing')
        if not isinstance(worker, Thread) or worker.ident is not None or not callable(request_stop):
            raise ValueError('invalid_background_worker')
        if self.running(worker.name):
            raise LifecycleError('duplicate_background_worker')
        self._workers[worker] = request_stop
        try:
            worker.start()
        except Exception:  # noqa: BLE001 -- 登記失敗不可留下虛假的執行中工作。
            self._workers.pop(worker, None)
            raise LifecycleError('background_worker_start_failed') from None

    def pending(self):
        self.assert_owner()
        self._prune()
        return len(self._workers)

    def request_stop_all(self):
        self.assert_owner()
        if self._closing:
            return
        self._closing = True
        self._prune()
        for request_stop in tuple(self._workers.values()):
            try:
                request_stop()
            except Exception:  # noqa: BLE001 -- 個別取消失敗不能阻止其他工作的取消。
                self._cancel_failed = True

    def close(self, *, timeout=2):
        self.assert_owner()
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 <= timeout <= 30):
            raise ValueError('invalid_worker_shutdown_timeout')
        self.request_stop_all()
        deadline = time.monotonic() + timeout
        for worker in tuple(self._workers):
            worker.join(max(0, deadline - time.monotonic()))
        if self.pending() or self._cancel_failed:
            raise LifecycleError('background_workers_not_released')
