"""明確相依、生命週期與反向清理；不持有 Tk、socket 或遊戲邏輯。"""
from __future__ import annotations

import math
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from enum import Enum
from threading import Thread, get_ident
from types import MappingProxyType

from wlre.core.application.configuration import ApplicationConfiguration
from wlre.core.application.diagnostics import DiagnosticLog
from wlre.core.application.state import StateManager
from wlre.core.events import EventBus
from wlre.core.primitives import Owned, identifier


class Lifecycle(str, Enum):
    CREATED = 'created'
    INITIALIZED = 'initialized'
    READY = 'ready'
    RUNNING = 'running'
    STOPPING = 'stopping'
    STOPPED = 'stopped'
    FAILED = 'failed'


class LifecycleError(RuntimeError):
    """錯誤代碼不攜帶模組內的任意例外內容。"""


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    responsibility: str
    public_api: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    emits: tuple[str, ...] = ()
    official_requirements: tuple[str, ...] = ()

    def __post_init__(self):
        identifier(self.name)
        if not isinstance(self.responsibility, str) or not self.responsibility.strip():
            raise ValueError('module_responsibility_required')
        for value in (self.public_api, self.dependencies, self.consumes,
                      self.emits, self.official_requirements):
            if type(value) is not tuple or len(set(value)) != len(value):
                raise ValueError('invalid_module_contract')
            for item in value:
                identifier(item)
        if not self.public_api:
            raise ValueError('module_public_api_required')


@dataclass(frozen=True)
class ModuleContext:
    configuration: ApplicationConfiguration
    events: EventBus
    states: StateManager
    diagnostics: DiagnosticLog
    dependencies: Mapping[str, object]


class _PublicAPI:
    """只公開契約列出的方法；持有方法引用也不能繞過停止檢查。"""

    def __init__(self, module, implementation):
        self._module = module
        self._implementation = implementation

    def __getattr__(self, name):
        if name not in self._module.spec.public_api:
            raise AttributeError(name)

        def invoke(*args, **kwargs):
            self._module.assert_owner()
            if (self._module._quiescing or
                    self._module.state not in (Lifecycle.READY, Lifecycle.RUNNING)):
                raise LifecycleError('module_api_requires_ready')
            return getattr(self._implementation, name)(*args, **kwargs)

        return invoke


class ManagedModule(Owned):
    def __init__(self, spec, *, api):
        super().__init__()
        if not isinstance(spec, ModuleSpec):
            raise TypeError('module_spec_required')
        for name in spec.public_api:
            if not callable(getattr(api, name, None)):
                raise TypeError('module_public_api_missing')
        self.spec = spec
        self.api = _PublicAPI(self, api)
        self._state = Lifecycle.CREATED
        self._resources = ExitStack()
        self._initialization_attempted = False
        self._cleaned = False
        self._quiescing = False

    @property
    def state(self):
        self.assert_owner()
        return self._state

    def own(self, cleanup, *args, **kwargs):
        """登記已取得的訂閱／計時器／工作清理；依反向順序釋放。"""
        self.assert_owner()
        if (not self._initialization_attempted or self._cleaned or self._quiescing or
                self._state in (Lifecycle.STOPPING, Lifecycle.FAILED)):
            raise LifecycleError('module_cannot_acquire_resources')
        if not callable(cleanup):
            raise TypeError('cleanup_not_callable')
        self._resources.callback(cleanup, *args, **kwargs)

    def initialize(self, context):
        self.assert_owner()
        if self._state is not Lifecycle.CREATED:
            raise LifecycleError('module_initialize_requires_created')
        self._initialization_attempted = True
        try:
            self.on_initialize(context)
            self._state = Lifecycle.INITIALIZED
            self.on_ready()
            self._state = Lifecycle.READY
        except Exception:  # noqa: BLE001 -- 生命週期邊界必須清理任意模組失敗，且不輸出例外內容。
            self._state = Lifecycle.FAILED
            raise LifecycleError('module_initialization_failed') from None

    def own_worker(self, worker, request_stop, *, timeout=2):
        """有界停止已註冊的工作；未退出必須視為停止失敗，不能假裝已釋放。"""
        self.assert_owner()
        if (not isinstance(worker, Thread) or worker.ident == get_ident()
                or not callable(request_stop) or type(timeout) not in (int, float)
                or not math.isfinite(timeout) or not 0 < timeout <= 30):
            raise ValueError('invalid_owned_worker')

        def close_worker():
            try:
                request_stop()
            finally:
                if worker.ident is not None:
                    worker.join(timeout)
            if worker.is_alive():
                raise LifecycleError('owned_worker_did_not_stop')

        self.own(close_worker)

    def start(self):
        self.assert_owner()
        if self._state is not Lifecycle.READY:
            raise LifecycleError('module_start_requires_ready')
        try:
            self.on_start()
            self._state = Lifecycle.RUNNING
        except Exception:  # noqa: BLE001 -- 生命週期邊界必須清理任意模組失敗，且不輸出例外內容。
            self._state = Lifecycle.FAILED
            raise LifecycleError('module_start_failed') from None

    def stop(self):
        self.assert_owner()
        if self._cleaned:
            return
        self._quiesce()
        failed = self._state is Lifecycle.FAILED
        self._state = Lifecycle.STOPPING
        stop_failed = False
        try:
            if self._initialization_attempted:
                self.on_stop()
        except Exception:  # noqa: BLE001 -- 生命週期邊界必須清理任意模組失敗，且不輸出例外內容。
            stop_failed = True
        try:
            self._resources.close()
        except Exception:  # noqa: BLE001 -- 生命週期邊界必須清理任意模組失敗，且不輸出例外內容。
            stop_failed = True
        self._cleaned = True
        self._state = Lifecycle.FAILED if failed or stop_failed else Lifecycle.STOPPED
        if stop_failed:
            raise LifecycleError('module_stop_failed') from None

    def _quiesce(self):
        self.assert_owner()
        self._quiescing = True

    def on_initialize(self, context):
        pass

    def on_ready(self):
        pass

    def on_start(self):
        pass

    def on_stop(self):
        pass


class ModuleManager(Owned):
    def __init__(self, modules):
        super().__init__()
        self._modules = {}
        for module in modules:
            if not isinstance(module, ManagedModule) or module.state is not Lifecycle.CREATED:
                raise LifecycleError('manager_requires_created_modules')
            if module.spec.name in self._modules:
                raise LifecycleError('duplicate_module_name')
            self._modules[module.spec.name] = module
        self._order = self._resolve_order()
        self._busy = False

    def _resolve_order(self):
        order, visiting, visited = [], set(), set()

        def visit(name):
            if name not in self._modules:
                raise LifecycleError('module_dependency_missing')
            if name in visiting:
                raise LifecycleError('module_dependency_cycle')
            if name in visited:
                return
            visiting.add(name)
            for dependency in self._modules[name].spec.dependencies:
                visit(dependency)
            visiting.remove(name)
            visited.add(name)
            order.append(name)

        for name in self._modules:
            visit(name)
        return tuple(order)

    @property
    def order(self):
        self.assert_owner()
        return self._order

    def statuses(self):
        self.assert_owner()
        return MappingProxyType({name: module.state for name, module in self._modules.items()})

    def _enter(self):
        self.assert_owner()
        if self._busy:
            raise LifecycleError('recursive_module_lifecycle_rejected')
        self._busy = True

    def initialize(self, context):
        self._enter()
        try:
            for name in self._order:
                module = self._modules[name]
                dependencies = {}
                for dependency in module.spec.dependencies:
                    required = self._modules[dependency]
                    if required.state is not Lifecycle.READY:
                        raise LifecycleError('module_dependency_not_ready')
                    dependencies[dependency] = required.api
                module.initialize(ModuleContext(
                    context.configuration, context.events, context.states, context.diagnostics,
                    MappingProxyType(dependencies)))
        finally:
            self._busy = False

    def start(self):
        self._enter()
        try:
            for name in self._order:
                self._modules[name].start()
        finally:
            self._busy = False

    def stop(self):
        self._enter()
        failures = []
        try:
            # 先關閉所有模組的業務 API，再依反向順序執行清理。
            for module in self._modules.values():
                module._quiesce()
            for name in reversed(self._order):
                try:
                    self._modules[name].stop()
                except Exception:  # noqa: BLE001 -- 生命週期邊界必須清理任意模組失敗，且不輸出例外內容。
                    failures.append(name)
        finally:
            self._busy = False
        return tuple(failures)
