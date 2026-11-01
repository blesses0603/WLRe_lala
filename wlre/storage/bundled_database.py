"""Migrate bundled JSON resources into the local resource database.

Bundled files are release data, not the current official catalog. Their
content hash is kept alongside each copy; this module never changes the
official version or grants compatibility.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from wlre.storage.paths import data_root


def load_bundled_bytes(name, *, root=None, database=None):
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(('.json', '.zip', '.gz')):
        raise ValueError('Invalid bundled resource name')
    if root is None:
        from wlre.paths import RESOURCE_ROOT
        root = RESOURCE_ROOT
    source = Path(root) / name
    path = Path(database) if database is not None else data_root() / 'official_sync' / 'derived_catalogs' / 'resource_inventory.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=15)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS bundled_resources (name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(name,sha256))')
        db.execute('CREATE TABLE IF NOT EXISTS bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
        if source.is_file():
            raw = source.read_bytes()
            if len(raw) > 64 * 1024 * 1024:
                raise ValueError('Bundled resource is too large')
            digest = hashlib.sha256(raw).hexdigest()
            db.execute('INSERT OR IGNORE INTO bundled_resources VALUES (?, ?, ?)', (name, digest, raw))
            db.execute('INSERT INTO bundled_active VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET sha256=excluded.sha256', (name, digest))
        else:
            active = db.execute('SELECT sha256 FROM bundled_active WHERE name=?', (name,)).fetchone()
            if not active:
                raise FileNotFoundError('Bundled resource missing from database: ' + name)
            digest = active[0]
        stored = db.execute('SELECT data FROM bundled_resources WHERE name=? AND sha256=?', (name, digest)).fetchone()
        if not stored or hashlib.sha256(stored[0]).hexdigest() != digest:
            raise ValueError('Bundled database resource failed integrity check')
        return bytes(stored[0])


def load_bundled_json(name, *, root=None, database=None):
    if not isinstance(name, str) or not name.endswith('.json'):
        raise ValueError('Invalid bundled JSON name')
    return json.loads(load_bundled_bytes(name, root=root, database=database).decode('utf-8-sig'))
