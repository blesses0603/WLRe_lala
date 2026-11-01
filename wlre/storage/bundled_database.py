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


def load_bundled_bytes(name, *, root=None, database=None, refresh=False):
    """Prefer verified SQLite BLOBs; import bundled files only when needed.

    Existing verified rows are read without opening the original file.
    Use refresh=True or resource_migration to import a new bundled revision.
    An existing active row must pass its SHA-256 check before it can be used
    or replaced. A changed bundled file is an explicit new bundled revision,
    not evidence that a 1262 catalog is valid for 1275 gameplay.
    """
    if (not isinstance(name, str) or Path(name).name != name
            or not name.endswith(('.json', '.zip', '.gz'))):
        raise ValueError('Invalid bundled resource name')
    if root is None:
        from wlre.paths import RESOURCE_ROOT
        root = RESOURCE_ROOT
    source = Path(root) / name
    path = (Path(database) if database is not None else data_root() /
            'official_sync' / 'derived_catalogs' / 'resource_inventory.sqlite3')
    # A missing DB and missing file must not create an empty user database.
    if not path.is_file() and not source.is_file():
        raise FileNotFoundError('Bundled resource missing: ' + name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=15)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS bundled_resources (name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(name,sha256))')
        db.execute('CREATE TABLE IF NOT EXISTS bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
        active = db.execute('SELECT sha256 FROM bundled_active WHERE name=?',
                            (name,)).fetchone()
        stored = None
        if active:
            stored = db.execute(
                'SELECT data FROM bundled_resources WHERE name=? AND sha256=?',
                (name, active[0])).fetchone()
            if (stored is None or not isinstance(stored[0], bytes)
                    or hashlib.sha256(stored[0]).hexdigest() != active[0]):
                raise ValueError('Bundled database resource failed integrity check')
        if active and not refresh:
            return bytes(stored[0])
        if source.is_file():
            # Preserve support for a new source revision without rewriting
            # SQLite when the source and the active verified BLOB are identical.
            raw = source.read_bytes()
            if len(raw) > 64 * 1024 * 1024:
                raise ValueError('Bundled resource is too large')
            digest = hashlib.sha256(raw).hexdigest()
            if active and active[0] == digest:
                return bytes(stored[0])
            db.execute('INSERT OR IGNORE INTO bundled_resources VALUES (?, ?, ?)',
                       (name, digest, raw))
            db.execute('INSERT INTO bundled_active VALUES (?, ?) '
                       'ON CONFLICT(name) DO UPDATE SET sha256=excluded.sha256',
                       (name, digest))
            return raw
        if not active:
            raise FileNotFoundError('Bundled resource missing from database: ' + name)
        return bytes(stored[0])


def load_bundled_json(name, *, root=None, database=None, refresh=False):
    if not isinstance(name, str) or not name.endswith('.json'):
        raise ValueError('Invalid bundled JSON name')
    return json.loads(load_bundled_bytes(name, root=root, database=database, refresh=refresh).decode('utf-8-sig'))


def read_pinned_legacy_bytes(name, *, root=None, database=None):
    """Read a pinned 1262 resource from SQLite without recreating or modifying it.

    This is a historical display-only source, never a 1275 gameplay authority.
    The DB must already exist and the stored BLOB must match the independent
    SHA-256 pinned in the repository. A missing or mismatched row fails closed.
    """
    import re
    if name not in (
        'instance_catalog_1262.json', 'npc_battle_talk_1262.json.gz',
        'npc_event_index_1262.json.gz', 'npc_interact_1262.json.gz',
        'npc_talk_1262.json.gz', 'npc_text_1262.json.gz',
    ):
        raise ValueError('非核准的 1262 歷史資源')
    from wlre.storage.paths import data_root
    db_path = (Path(database) if database is not None else
               data_root() / 'official_sync' / 'derived_catalogs' /
               'resource_inventory.sqlite3')
    if not db_path.is_file():
        raise FileNotFoundError('1262 歷史資料庫不存在')
    # The original bundled source is not consulted. This function is read-only.
    with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute(
            'SELECT a.sha256, b.data FROM bundled_active a '
            'JOIN bundled_resources b ON a.name=b.name AND a.sha256=b.sha256 '
            'WHERE a.name=?', (name,)
        ).fetchone()
    if row is None:
        raise FileNotFoundError('1262 歷史資源尚未匯入 SQLite: ' + name)
    digest, data = row
    if name in ('npc_talk_1262.json.gz', 'npc_text_1262.json.gz', 'npc_battle_talk_1262.json.gz'):
        from wlre.services.world.npc_asset_install import ASSETS
        expected = ASSETS[name]
        if digest != expected[0] or len(data) != expected[1]:
            raise ValueError('1262 NPC 歷史資源固定版本指紋不符')
    if name == 'npc_interact_1262.json.gz':
        from wlre.services.world.npc_interact import EXPECTED_SHA256
        if digest != EXPECTED_SHA256 or len(data) != 19914:
            raise ValueError('1262 NPC 選項歷史資源固定版本指紋不符')
    if (not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)
            or not isinstance(data, bytes) or len(data) > 16 * 1024 * 1024
            or hashlib.sha256(data).hexdigest() != digest):
        raise ValueError('1262 歷史資源 SQLite 完整性驗證失敗')
    return data


def load_legacy_resource(name, *, root=None, database=None):
    """Prefer validated SQLite data; use verified bundled files on a fresh install.

    Database corruption must fail closed; only a missing DB/row may fall back
    to the existing resource file. Never write to the database here.
    """
    if root is None:
        from wlre.paths import RESOURCE_ROOT
        root = RESOURCE_ROOT
    try:
        return read_pinned_legacy_bytes(name, database=database)
    except FileNotFoundError:
        path = Path(root) / name
        if not path.is_file():
            raise
        raw = path.read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('1262 歷史檔案超過大小上限')
        import re
        from wlre.services.world.npc_asset_install import ASSETS
        from wlre.services.world.npc_interact import EXPECTED_SHA256
        pinned = ({k: v[0] for k, v in ASSETS.items()} |
                  {'npc_interact_1262.json.gz': EXPECTED_SHA256})
        if name in pinned and hashlib.sha256(raw).hexdigest() != pinned[name]:
            raise ValueError('1262 歷史檔案與固定版本指紋不符')
        return raw
