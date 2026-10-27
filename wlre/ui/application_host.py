"""將既有桌面功能接入新核心；僅此轉接層認識 Tk 與 App。"""
import time
import tkinter as tk
from dataclasses import dataclass

from wlre.core.application import Application, LifecycleError, ManagedModule, ModuleSpec
from wlre.core.application.workers import WorkerGroup
from wlre.resources_runtime.official.module import OfficialResourceModule
from wlre.storage.paths import data_root


@dataclass(frozen=True)
class DesktopStatus:
    closing: bool
    live: bool
    workers: int


class DesktopModule(ManagedModule):
    def __init__(self, root, app_factory, request_close):
        super().__init__(ModuleSpec(
            'legacy_desktop', '保留現有畫面與功能，轉接新核心的生命週期', ('status',),
            dependencies=('official_resources',)), api=self)
        self.root = root
        self._app_factory = app_factory
        self._request_close = request_close
        self.tasks = WorkerGroup()
        self.app = None

    def status(self):
        return DesktopStatus(bool(self.app and self.app._closing),
                             bool(self.app and self.app.live_active), self.tasks.pending())

    def on_initialize(self, context):
        self.own(self._destroy)
        self.own(self.tasks.close, timeout=0.05)
        self.app = self._app_factory(self.root, tasks=self.tasks)
        self.app._request_shutdown = self._request_close
        attach = getattr(self.app, 'attach_official_scene_data', None)
        if callable(attach):
            cleanup = attach(context.dependencies['official_resources'])
            if not callable(cleanup):
                raise TypeError('scene_data_cleanup_required')
            self.own(cleanup)

    def _destroy(self):
        try:
            exists = self.root.winfo_exists()
        except tk.TclError:
            return
        if not exists:
            return
        for job in self.root.tk.call('after', 'info'):
            # Tcl／ttk 的 timer command 由所屬 widget 在 destroy 時釋放。
            self.root.tk.call('after', 'cancel', job)
        if self.app is not None:
            self.app._request_shutdown = None
            self.app._destroy_desktop()
        else:
            self.root.destroy()


class DesktopHost:
    def __init__(self, root, *, app_factory=None, close_timeout=15, clock=time.monotonic,
                 resource_module=None):
        if not 0 < close_timeout <= 30:
            raise ValueError('invalid_desktop_close_timeout')
        if app_factory is None:
            from wlre.ui.gui import App
            app_factory = App
        self.root = root
        self._clock = clock
        self._close_timeout = close_timeout
        self._closing = False
        self._failure = False
        self._pump_job = None
        self._close_job = None
        self.module = DesktopModule(root, app_factory, self.request_close)
        self.resources = (resource_module if resource_module is not None else
                          OfficialResourceModule(data_root() / 'official_resources_v1'))
        self.core = Application([self.resources, self.module])

    def start(self):
        self.core.initialize()
        self.core.start()
        self._pump_job = self.root.after(20, self._pump)

    def _pump(self):
        self._pump_job = None
        if not self._closing:
            self.resources.api.poll()
            app = self.module.app
            poll = getattr(app, 'poll_official_scene_data', None)
            if callable(poll):
                poll()
            self.core.pump()
            if not self._closing:
                self._pump_job = self.root.after(20, self._pump)

    def _cancel_job(self, attribute):
        job = getattr(self, attribute)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
            setattr(self, attribute, None)

    def request_close(self):
        self.core.assert_owner()
        if self._closing:
            return
        self._closing = True
        self._deadline = self._clock() + self._close_timeout
        self._cancel_job('_pump_job')
        app = self.module.app
        if app is not None:
            app._closing = True
            app.stop_event.set()
            app.password.set('')
        # 先隱藏視窗，保留 Tk pump 非阻塞等待合作式取消／現有 HTTP 逾時。
        for child in self.root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.withdraw()
        self.root.withdraw()
        self.resources.api.cancel()
        self.module.tasks.request_stop_all()
        self._wait_for_workers()

    def _wait_for_workers(self):
        self._close_job = None
        pending = self.module.tasks.pending() + self.resources.api.status().workers
        if pending and self._clock() < self._deadline:
            self._close_job = self.root.after(20, self._wait_for_workers)
            return
        try:
            self.core.stop()
        except LifecycleError:
            # 不從 Tk callback 直接拋出；交由主程式錯誤處理回報固定錯誤碼。
            self._failure = True

    def finish(self):
        """mainloop 非正常結束也必須停止核心，不將清理失敗標為成功。"""
        self._cancel_job('_pump_job')
        self._cancel_job('_close_job')
        self.core.stop()
        if self._failure:
            raise LifecycleError('desktop_shutdown_failed')


def run_desktop():
    root = tk.Tk()
    host = DesktopHost(root)
    try:
        host.start()
        root.mainloop()
    finally:
        host.finish()
