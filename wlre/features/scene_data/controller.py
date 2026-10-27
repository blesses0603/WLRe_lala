"""場景資料頁控制器，只使用資源 Module 公開 API。"""
from wlre.resources_runtime.official.contracts import (
    SCENE_DEFINITIONS,
    TEXT_DEFINITIONS,
)

SCOPE = 'scene_references'


class SceneDataController:
    def __init__(self, api):
        self._api = api
        self.window = None
        self._signature = None

    def open(self, parent, exe_version=''):
        if self.window is None or not self.window.winfo_exists():
            from wlre.features.scene_data.window import SceneDataWindow
            self.window = SceneDataWindow(parent, self, exe_version=exe_version)
        else:
            self.window.deiconify()
            self.window.lift()
        self.tick(force=True)

    def refresh(self, exe_version):
        try:
            self._api.refresh(exe_version, scope=SCOPE, requirements=(SCENE_DEFINITIONS, TEXT_DEFINITIONS))
        finally:
            self.tick(force=True)

    def cancel(self):
        self._api.cancel()
        self.tick(force=True)

    def tick(self, *, force=False):
        if self.window is None or not self.window.winfo_exists():
            return
        status = self._api.status()
        signature = (status.phase, status.job_id, status.snapshot_id, status.workers,
                     getattr(status, 'notification_pending', False))
        if force or signature != self._signature:
            self._signature = signature
            service = self._api.current() if status.phase == 'current' else None
            self.window.render(status, service)

    def close(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.window = None
        self._api = None
