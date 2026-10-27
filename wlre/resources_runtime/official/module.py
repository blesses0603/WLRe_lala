"""將官方資源接入核心生命週期；沒有 GUI、遊戲指令或自動網路請求。"""
import math
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

from wlre.core.application.modules import ManagedModule, ModuleSpec
from wlre.core.application.workers import WorkerGroup
from wlre.core.primitives import identifier
from wlre.resources_runtime.official.contracts import validated_requirements
from wlre.resources_runtime.official.manager import (
    OfficialResourceManager,
    ResourceRefreshError,
)


@dataclass(frozen=True)
class ResourceRefreshFinished:
    job_id: int
    scope: str
    phase: str
    snapshot_id: str | None
    code: str


@dataclass(frozen=True)
class ResourceModuleStatus:
    phase: str
    job_id: int
    scope: str | None
    snapshot_id: str | None
    code: str
    workers: int
    notification_pending: bool


@dataclass(frozen=True)
class _Outcome:
    phase: str
    code: str
    service: object = None


def _refresh(manager, exe_version, scope, requirements, cancel, results, result_lock, stopping):
    """工作執行緒只寫私人單槽結果，不呼叫 UI、EventBus 或模組公開 API。"""
    try:
        service = manager.refresh(exe_version, scope=scope, requirements=requirements,
                                  cancel_event=cancel)
        outcome = _Outcome('current', 'official_scope_validated', service)
    except ResourceRefreshError as exc:
        reviewed = {'official_resource_gaps', 'official_resource_incompatible',
                    'official_resource_extract_failed', 'official_versions_changed_during_refresh',
                    'official_manifest_changed_during_refresh', 'official_bundle_cache_changed',
                    'official_manifest_cache_changed'}
        code = str(exc) if str(exc) in reviewed else 'official_resource_refresh_failed'
        outcome = _Outcome('failed', code)
    except InterruptedError:
        outcome = _Outcome('cancelled', 'official_refresh_cancelled')
    except Exception:  # noqa: BLE001 -- 外部 I/O 邊界不洩漏憑證／原始例外，結果交擁有者處理。
        outcome = _Outcome('failed', 'official_resource_refresh_failed')
    if cancel.is_set():
        outcome = _Outcome('cancelled', 'official_refresh_cancelled')
    with result_lock:
        if not stopping.is_set():
            results.put_nowait(outcome)  # 每份結果槽只對應一個工作；停止後不再寫入。


class OfficialResourceModule(ManagedModule):
    def __init__(self, cache_root, *, opener=None, shutdown_timeout=2):
        if (type(shutdown_timeout) not in (int, float) or not math.isfinite(shutdown_timeout)
                or not 0 < shutdown_timeout <= 30):
            raise ValueError('invalid_resource_shutdown_timeout')
        super().__init__(ModuleSpec(
            'official_resources', '取得並核對明確範圍的官方資料，納管背景工作與查詢租約',
            ('refresh', 'poll', 'status', 'cancel', 'current', 'diagnose'),
            emits=('resource_refresh_finished',),
            official_requirements=('explicit_verified_resource_requirements',)), api=self)
        self._cache_root, self._opener = cache_root, opener
        self._shutdown_timeout = shutdown_timeout
        self._manager = self._workers = self._events = None
        self._results = Queue(maxsize=1)
        self._cancel = Event()
        self._result_lock, self._stopping = Lock(), Event()
        self._service = self._pending_event = None
        self._active = False
        self._phase, self._code = 'idle', 'official_refresh_not_requested'
        self._job_id, self._scope = 0, None

    def on_initialize(self, context):
        self._events = context.events
        self.own(self._discard_result)
        self._workers = WorkerGroup()
        self.own(self._workers.close, timeout=self._shutdown_timeout)
        self._manager = OfficialResourceManager(self._cache_root, opener=self._opener)
        self.own(self._manager.close)

    def _discard_result(self):
        self._service = self._pending_event = None
        try:
            self._results.get_nowait()
        except Empty:
            pass
        self._events = None

    def on_stop(self):
        with self._result_lock:
            self._stopping.set()
        self._cancel.set()
        self._service = self._pending_event = None
        if self._manager is not None:
            self._manager.close()  # 先撤銷租約／取消傳輸，再由受管工作等待退出。
        if self._workers is not None:
            self._workers.request_stop_all()
        self._phase, self._code = 'stopped', 'official_resources_stopped'

    def refresh(self, exe_version, *, scope, requirements):
        identifier(scope)
        validated_requirements(requirements)
        if self._active or self._workers.pending():
            raise ResourceRefreshError('official_refresh_already_running')
        if self._pending_event is not None:
            raise ResourceRefreshError('official_notification_backpressure')
        self._manager.revoke_views()
        self._service = None
        self._cancel = Event()
        self._job_id += 1
        self._scope = scope
        self._phase, self._code = 'refreshing', 'official_refresh_running'
        self._active = True
        worker = Thread(target=_refresh,
                        args=(self._manager, exe_version, scope, requirements,
                              self._cancel, self._results, self._result_lock, self._stopping),
                        name='official_resource_refresh', daemon=False)
        try:
            self._workers.start(worker, self._cancel.set)
        except Exception:  # noqa: BLE001 -- 啟動失敗也必須清除工作狀態且保留租約撤銷。
            self._active = False
            self._phase, self._code = 'failed', 'official_worker_start_failed'
            raise ResourceRefreshError(self._code) from None
        return self._job_id

    def status(self):
        return ResourceModuleStatus(
            self._phase, self._job_id, self._scope,
            None if self._service is None else self._service.snapshot_id,
            self._code, self._workers.pending(), self._pending_event is not None)

    def poll(self):
        """擁有者 tick 接收一份結果；EventBus 滿載時保留通知供下一次重試。"""
        if self._active:
            try:
                outcome = self._results.get_nowait()
            except Empty:
                pass
            else:
                self._active = False
                if self._cancel.is_set():
                    self._manager.revoke_views()
                    self._phase, self._code = 'cancelled', 'official_refresh_cancelled'
                    self._service = None
                else:
                    self._phase, self._code, self._service = outcome.phase, outcome.code, outcome.service
                self._pending_event = ResourceRefreshFinished(
                    self._job_id, self._scope, self._phase,
                    None if self._service is None else self._service.snapshot_id, self._code)
        if self._pending_event is not None:
            try:
                self._events.post(self._pending_event)
            except Full:
                pass
            else:
                self._pending_event = None
        return self.status()

    def cancel(self):
        self._cancel.set()
        self._manager.revoke_views()
        self._service = None
        self._phase = 'cancel_requested' if self._active else 'cancelled'
        self._code = 'official_refresh_cancelled'
        if not self._active and self._job_id:
            self._pending_event = ResourceRefreshFinished(
                self._job_id, self._scope, self._phase, None, self._code)

    def current(self):
        if self._phase != 'current' or self._service is None:
            raise ResourceRefreshError('official_data_not_current')
        return self._service

    def diagnose(self, scope):
        return self._manager.diagnose(scope)
