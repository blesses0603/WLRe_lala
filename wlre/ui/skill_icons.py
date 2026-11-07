"""Bounded official atlas icons, mapped exactly as reviewed SkillData.lua.

Missing GId/assets remain absent. No skill-ID substitution or invented art.
"""
from collections import OrderedDict
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
    """Window-local Tk references; caller retains photos shown in live cards."""
    def __init__(self, master):
        self.master = master
        self.cache = OrderedDict()

    def get(self, data, size=64):
        name = icon_name(data)
        key = name, size
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        pixels = skill_icon_image(data, size)
        if pixels is None:
            return None
        photo = ImageTk.PhotoImage(pixels, master=self.master)
        self.cache[key] = photo
        while len(self.cache) > 128:
            self.cache.popitem(last=False)
        return photo

    def close(self):
        self.cache.clear()
