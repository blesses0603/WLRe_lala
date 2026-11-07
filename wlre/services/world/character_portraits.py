"""Read-only portrait selection and bounded asynchronous pixel cache.

No login, downloads, or Unity parsing happens on the Tk thread. An absent or
unrecognized observation never selects an arbitrary character as a fallback.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import time


def current_catalog():
    from wlre.services.world.dynamic_bundle_runtime import current_runtime
    return getattr(current_runtime(), 'portraits', None)


def select_portrait(state, kind, catalog):
    player = state.get('player', {})
    if not player.get('role_id'):
        return None
    if kind == 'player':
        sex, head = player.get('sex'), player.get('head')
        if type(sex) is not int or type(head) is not int:
            return None
        ident = catalog.characters.get((sex, head))
        values = (player.get('palette1'), player.get('palette5'))
        if ident is None or any(type(v) is not int or not 0 <= v <= 999999999 for v in values):
            return None
        return ('player', f'{ident:04d}', ((1, values[0]), (5, values[1])))
    if kind != 'companion':
        return None
    knowledge = state.get('knowledge', {})
    active = knowledge.get('active_npc_id')
    matches = [p for p in knowledge.get('companions', {}).values()
               if active and p.get('npc_id') == active and p.get('ready') is True]
    if len(matches) != 1:
        return None
    profile = matches[0]
    modeling = profile.get('stats', {}).get('modeling')
    if type(modeling) is not int or not 0 <= modeling <= 65535:
        return None
    npc = catalog.npcs.get(modeling or profile['npc_id'])
    if npc is None:
        return None
    return ('companion', npc['icon'], tuple(sorted(npc['palettes'].items())))


class PortraitProvider:
    """At most two in-flight renders and 32 owned Pillow images per window.

    The caller polls request during its existing refresh; no callback touches
    Tk from a worker. Version/role changes cannot publish an old portrait.
    """
    def __init__(self, source=None, executor=None, clock=None):
        self.source = source or current_catalog
        self.clock = clock or time.monotonic
        self._failures = {}
        self.executor = executor
        self._owns_executor = executor is None
        self._cache = OrderedDict()
        self._pending = {}
        self._source = None
        self._generation = 0
        self._closed = False

    def _clear(self):
        for image in self._cache.values():
            if image is not None:
                image.close()
        self._cache.clear()
        self._failures.clear()
        def discard(future):
            if not future.cancelled():
                try:
                    image = future.result()
                    if image is not None:
                        image.close()
                except Exception:
                    pass
        for future in self._pending.values():
            if not future.cancel():
                future.add_done_callback(discard)
        self._pending.clear()
        self._generation += 1

    @staticmethod
    def _render(catalog, selection, size):
        from PIL import Image
        image = catalog.image(*selection)
        if image is None:
            return None
        try:
            result = image.convert('RGBA')
            result.thumbnail((size, size), Image.Resampling.LANCZOS)
            return result
        finally:
            image.close()

    def request(self, state, kind, size):
        result = {'image': None, 'revision': (self._generation, kind, None), 'status': '頭像待同步'}
        if self._closed or type(size) is not int or not 16 <= size <= 128:
            return result
        catalog = self.source()
        token = (getattr(catalog, 'catalog_key', None), id(catalog))
        if token != self._source:
            self._clear()
            self._source = token
        selection = select_portrait(state, kind, catalog) if catalog is not None else None
        key = (token, selection, size)
        result['revision'] = (self._generation, key)
        if selection is None:
            return result
        # Reap all completed work so rapid role switching cannot fill the queue.
        for pending_key, future in list(self._pending.items()):
            if not future.done():
                continue
            del self._pending[pending_key]
            try:
                image = future.result()
            except Exception:
                image = None
                attempts = self._failures.get(pending_key, (0, 0))[0] + 1
                self._failures[pending_key] = (min(attempts, 4), self.clock() + min(60, 5 * 2 ** min(attempts - 1, 4)))
            else:
                self._failures.pop(pending_key, None)
            self._cache[pending_key] = image
            while len(self._cache) > 32:
                old_key, old = self._cache.popitem(last=False)
                self._failures.pop(old_key, None)
                if old is not None:
                    old.close()
        if key in self._failures and self.clock() >= self._failures[key][1] and key not in self._pending:
            self._cache.pop(key, None)
        if key in self._cache:
            self._cache.move_to_end(key)
            image = self._cache[key]
            result.update(image=image, revision=(self._generation, key, 'ready' if image else 'unavailable'),
                          status='官方頭像' if image else '頭像待同步')
        elif key not in self._pending and len(self._pending) < 2:
            if self.executor is None:
                self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='official-portrait')
            self._pending[key] = self.executor.submit(self._render, catalog, selection, size)
        return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._clear()
        if self.executor is not None and self._owns_executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
