"""One bounded background cache preparation job; never owns game commands."""
import copy
import threading
from wlre.services.world.dynamic_bundle_runtime import current_runtime
from wlre.services.world.navigation_database import database_path, load_cache, REVIEWED_MODELS
from wlre.services.world.navigation_preview import REVIEWED_COORDINATE_CATALOGS
from wlre.services.world.navigation_sync import sync_model
from wlre.services.world.house_navigation import require_general_navigation


class NavigationAutoSync:
    def __init__(self, *, runtime_getter=current_runtime, loader=load_cache,
                 sync=sync_model, root=None):
        self.runtime_getter = runtime_getter
        self.loader, self.sync, self.root = loader, sync, root
        self.worker = None
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.closed = False
        self.context = None
        self.attempted = set()
        self.value = {'status': 'idle', 'message': '導航：等待目前地圖。'}

    def update(self, state, *, enabled, retry=False):
        """Called on the UI thread. Polls never perform disk reads or downloads."""
        runtime = self.runtime_getter()
        player = state.get('player', {})
        scene = player.get('scene')
        context = None
        error = None
        if enabled and runtime is not None and type(scene) is int:
            try:
                require_general_navigation(scene=scene)
                model = runtime.stages[scene]['model_id']
                require_general_navigation(model=model)
                if type(model) is not int or model not in REVIEWED_MODELS:
                    raise ValueError('此模型尚未完成導航格式核對。')
                if runtime.catalog_identity.key not in REVIEWED_COORDINATE_CATALOGS:
                    raise ValueError('此版本官方座標尚未完成格式核對。')
                context = (id(runtime), runtime.catalog_identity.key, model, scene, player.get('role_id'))
            except (KeyError, ValueError, TypeError) as exc:
                error = str(exc) if not isinstance(exc, KeyError) else '官方場景表缺少此地圖。'
        with self.lock:
            if self.closed:
                return dict(status='closed', message='導航同步已關閉。')
            if context != self.context:
                self.cancelled.set()
                self.context = context
                self.value = dict(status='idle', message='導航：等待目前地圖。')
            if context is None:
                self.value = dict(status='blocked', message='導航：'+(error or '離線、版本暫停或官方資料尚未就緒。'))
                return self.value.copy()
            key = context[:3]
            if self.worker and self.worker.is_alive():
                if self.cancelled.is_set():
                    return dict(status='cancelling', message='導航：等待上一筆同步安全結束。')
                return self.value.copy()
            if retry:
                self.attempted.discard(key)
            if key in self.attempted:
                # Returning to an old scene must not display another scene's result.
                if self.value['status'] == 'idle':
                    self.value = dict(status='idle', message='導航：此模型已嘗試同步；需要時可按「同步導航」重試。')
                return self.value.copy()
            self.attempted.add(key)
            cancelled = threading.Event()
            self.cancelled = cancelled
            identity = copy.deepcopy(runtime.catalog_identity)
            self.value = dict(status='working', message=f'導航：正在背景校驗／同步 M{model:05d}…')

            def obsolete():
                return cancelled.is_set() or self.runtime_getter() is not runtime

            def run():
                try:
                    if obsolete():
                        return
                    cached = self.loader(database_path(self.root), identity.key, model)
                    if cached is None:
                        self.sync(identity, model, root=self.root, cancelled=obsolete)
                    if obsolete():
                        return
                    # Validate the actual persisted bytes, not just a download receipt.
                    if self.loader(database_path(self.root), identity.key, model) is None:
                        raise ValueError('同步未產生同版本導航資料。')
                    value = dict(status='ready', message=f'導航 M{model:05d} 已就緒；請重新操作，不會自動移動。')
                except Exception as exc:
                    value = dict(status='error', message='導航同步失敗：'+(str(exc)[:180] or type(exc).__name__)+'；未使用舊版資料，可手動重試。')
                with self.lock:
                    if not self.closed and self.context == context and not obsolete():
                        self.value = value

            self.worker = threading.Thread(target=run, name='official-navigation-sync', daemon=True)
            self.worker.start()
            return self.value.copy()

    def cancel(self):
        with self.lock:
            self.cancelled.set()
            self.value = dict(status='cancelled', message='導航同步已取消；不會自動重試，可手動同步。')

    def close(self):
        with self.lock:
            self.closed = True
            self.cancelled.set()
