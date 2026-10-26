"""核心組裝與關閉協調；沒有 GUI 迴圈或遊戲傳輸行為。"""
from types import MappingProxyType

from wlre.core.application.configuration import ApplicationConfiguration
from wlre.core.application.diagnostics import DiagnosticLog
from wlre.core.application.modules import (
    Lifecycle,
    LifecycleError,
    ModuleContext,
    ModuleManager,
)
from wlre.core.application.state import StateManager
from wlre.core.events import EventBus
from wlre.core.primitives import Owned


class Application(Owned):
    def __init__(self, modules=(), *, configuration=None, diagnostics=None):
        super().__init__()
        self.configuration = configuration if configuration is not None else ApplicationConfiguration()
        if not isinstance(self.configuration, ApplicationConfiguration):
            raise TypeError('application_configuration_required')
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticLog()
        if not isinstance(self.diagnostics, DiagnosticLog):
            raise TypeError('application_diagnostic_log_required')
        self.events = EventBus(self.configuration.event_capacity, record=self.diagnostics.record)
        self.states = StateManager()
        self.modules = ModuleManager(modules)
        self._state = Lifecycle.CREATED
        self._closed = False
        self._busy = False

    @property
    def state(self):
        self.assert_owner()
        return self._state

    def _begin(self, required):
        self.assert_owner()
        if self._busy or self._closed or self._state is not required:
            raise LifecycleError('invalid_application_transition')
        self._busy = True

    def initialize(self):
        self._begin(Lifecycle.CREATED)
        try:
            self.modules.initialize(ModuleContext(
                self.configuration, self.events, self.states, self.diagnostics, MappingProxyType({})))
            self._state = Lifecycle.INITIALIZED
            self._state = Lifecycle.READY
            self.diagnostics.record('application', 'ready')
        except Exception:  # noqa: BLE001 -- 生命週期邊界必須清理任意模組失敗，且不輸出例外內容。
            self._fail('initialization_failed')
            raise LifecycleError('application_initialization_failed') from None
        finally:
            self._busy = False

    def start(self):
        self._begin(Lifecycle.READY)
        try:
            self.modules.start()
            self._state = Lifecycle.RUNNING
            self.diagnostics.record('application', 'running')
        except Exception:  # noqa: BLE001 -- 生命週期邊界必須清理任意模組失敗，且不輸出例外內容。
            self._fail('start_failed')
            raise LifecycleError('application_start_failed') from None
        finally:
            self._busy = False

    def pump(self):
        self.assert_owner()
        if self._state is not Lifecycle.RUNNING or self._closed:
            raise LifecycleError('application_pump_requires_running')
        return self.events.drain(self.configuration.events_per_tick)

    def _release(self):
        failures = self.modules.stop()
        self.events.close()
        self.states.close()
        self._closed = True
        return failures

    def _fail(self, code):
        self._state = Lifecycle.FAILED
        failures = self._release()
        self.diagnostics.record('application', code, cleanup_failures=len(failures))
        self.diagnostics.close()

    def stop(self):
        self.assert_owner()
        if self._busy:
            raise LifecycleError('recursive_application_stop_rejected')
        if self._closed:
            return
        self._busy = True
        self._state = Lifecycle.STOPPING
        try:
            failures = self._release()
            self._state = Lifecycle.FAILED if failures else Lifecycle.STOPPED
            self.diagnostics.record('application', 'stopped', cleanup_failures=len(failures))
            self.diagnostics.close()
            if failures:
                raise LifecycleError('application_stop_failed')
        finally:
            self._busy = False
