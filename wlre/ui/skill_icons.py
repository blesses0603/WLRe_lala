"""Bounded official atlas icons, mapped exactly as reviewed SkillData.lua.

Missing GId/assets remain absent. No skill-ID substitution or invented art.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import hashlib
import io
import sqlite3
from contextlib import closing
from PIL import Image, ImageTk
from wlre.paths import RESOURCE_ROOT

ASSET_ROOT = RESOURCE_ROOT / 'assets' / 'skill-icons'


def _database():
    path = ASSET_ROOT / 'skill-icons.sqlite3'
    if path.is_symlink() or not 0 < path.stat().st_size <= 16 * 1024 * 1024:
        raise ValueError('Invalid official skill icon database size')
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


@lru_cache(maxsize=1)
def _manifest():
    with closing(_database()) as db:
        if db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone() != ('1',):
            raise ValueError('Invalid official skill icon database schema')
        count = db.execute('SELECT count(*) FROM provenance').fetchone()[0]
        if not 0 < count <= 512:
            raise ValueError('Invalid official skill icon inventory')
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT * FROM provenance').fetchall()
    return {row['name']: dict(row) for row in rows}


def icon_name(data):
    gid = data.get('GId')
    if type(gid) is not int or not 0 < gid <= 65535:
        return None
    return 'icon_sk%ds' % gid


@lru_cache(maxsize=128)
def _pixels(name, size):
    entry = _manifest().get(name)
    if entry is None:
        return None
    if not 0 < entry['bytes'] <= 256 * 1024:
        raise ValueError('Official skill icon exceeds reviewed size')
    with closing(_database()) as db:
        row = db.execute('SELECT png FROM images WHERE name=? AND length(png)=?',
                         (name, entry['bytes'])).fetchone()
    if row is None or type(row[0]) is not bytes:
        raise ValueError('Official skill icon length or image missing')
    raw = row[0]
    if hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('Official skill icon checksum mismatch')
    with Image.open(io.BytesIO(raw)) as source:
        if source.format != 'PNG' or source.size != (entry['width'], entry['height']):
            raise ValueError('Official skill icon dimensions mismatch')
        if not 0 < source.width <= 256 or not 0 < source.height <= 256:
            raise ValueError('Official skill icon dimensions exceed limit')
        result = source.convert('RGBA')
    result.thumbnail((size, size), Image.Resampling.LANCZOS)
    return result


def skill_icon_image(data, size=64):
    """Return original official pixels resized to fit, or None if unavailable."""
    if type(size) is not int or not 1 <= size <= 256:
        raise ValueError('Skill icon size must be 1..256')
    name = icon_name(data)
    if name is None:
        return None
    try:
        result = _pixels(name, size)
        return result.copy() if result is not None else None
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return None


class SkillIcons:
    """Decode on one worker; create at most four Tk photos per UI tick.

    SQLite reads, checksums and PNG decoding never run on the Tk thread.
    Closing cancels queued work; completed workers never call Tk directly.
    """
    def __init__(self, master, on_ready=None, executor=None):
        self.master = master
        self.on_ready = on_ready
        self.cache = OrderedDict()
        self.pending = OrderedDict()
        self.executor = executor
        self.owns_executor = executor is None
        self.timer = None
        self.closed = False

    def get(self, data, size=64):
        if self.closed:
            return None
        name = icon_name(data)
        if name is None:
            return None
        key = name, size
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if key not in self.pending and len(self.pending) < 512:
            if self.executor is None:
                self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='skill-icons')
            self.pending[key] = self.executor.submit(skill_icon_image, {'GId': data['GId']}, size)
            if self.timer is None:
                self.timer = self.master.after(15, self._poll)
        return None

    def _poll(self):
        self.timer = None
        if self.closed:
            return
        completed = 0
        for key, future in list(self.pending.items()):
            if not future.done():
                continue
            del self.pending[key]
            try:
                pixels = future.result()
            except Exception:
                pixels = None
            photo = None
            if pixels is not None:
                try:
                    photo = ImageTk.PhotoImage(pixels, master=self.master)
                finally:
                    pixels.close()
            self.cache[key] = photo  # Cache misses as well; no per-refresh retry storm.
            while len(self.cache) > 512:
                self.cache.popitem(last=False)
            if self.on_ready is not None:
                self.on_ready(key, photo)
            completed += 1
            if completed == 4:
                break
        if self.pending:
            self.timer = self.master.after(15, self._poll)

    @staticmethod
    def _discard(future):
        if not future.cancelled():
            try:
                pixels = future.result()
                if pixels is not None:
                    pixels.close()
            except Exception:
                pass

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.timer is not None:
            self.master.after_cancel(self.timer)
            self.timer = None
        for future in self.pending.values():
            if not future.cancel():
                future.add_done_callback(self._discard)
        self.pending.clear()
        if self.executor is not None and self.owns_executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
        self.cache.clear()
