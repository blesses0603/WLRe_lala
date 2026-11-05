"""Verified, distributable legacy catalog seed; no account or live user database."""
import hashlib
from pathlib import Path
import sqlite3
from contextlib import closing

NAMES = (
    'instance_catalog_1262.json', 'npc_battle_talk_1262.json.gz',
)
SEED_NAME = 'legacy_catalog_seed.sqlite3'


def pinned_hashes():
    from wlre.services.world.npc_asset_install import ASSETS
    from wlre.services.world.npc_interact import EXPECTED_SHA256
    return {**{name: ASSETS[name][0] for name in ASSETS},
            'npc_interact_1262.json.gz': EXPECTED_SHA256}


def verify_seed(path):
    """Check structure, names and all BLOB digests before accepting a seed."""
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    hashes = pinned_hashes()
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('初始資料庫完整性檢查失敗')
        rows = db.execute('SELECT a.name, a.sha256, b.data FROM bundled_active a '
                          'JOIN bundled_resources b ON a.name=b.name AND a.sha256=b.sha256').fetchall()
        if {r[0] for r in rows} != set(NAMES):
            raise ValueError('初始資料庫資源清單不完整')
        for name, digest, data in rows:
            if (not isinstance(data, bytes) or len(data) > 16 * 1024 * 1024
                    or hashlib.sha256(data).hexdigest() != digest
                    or (name in hashes and digest != hashes[name])):
                raise ValueError('初始資料庫雜湊或內容不正確: ' + name)
    return True


def build_seed(resource_root, destination):
    """Generate deterministic seed from source-controlled resources, then verify."""
    resource_root, destination = Path(resource_root), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.tmp')
    temporary.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.execute('CREATE TABLE bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
            db.execute('CREATE TABLE bundled_resources (name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(name,sha256))')
            for name in NAMES:
                from wlre.storage.full_resource_seed import read_config
                source = resource_root / name
                raw = source.read_bytes() if source.is_file() else read_config(name, root=resource_root)
                digest = hashlib.sha256(raw).hexdigest()
                if name in pinned_hashes() and pinned_hashes()[name] != digest:
                    raise ValueError('資源固定 SHA-256 不符: ' + name)
                db.execute('INSERT INTO bundled_active VALUES (?,?)', (name, digest))
                db.execute('INSERT INTO bundled_resources VALUES (?,?,?)', (name, digest, raw))
        verify_seed(temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def provision_seed(seed, database):
    """Copy only missing entries to user DB; never overwrite existing active data."""
    verify_seed(seed)
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=15)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS bundled_resources (name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(name,sha256))')
        with closing(sqlite3.connect(Path(seed).resolve().as_uri() + '?mode=ro', uri=True)) as src:
            for name, digest, raw in src.execute('SELECT a.name, a.sha256, b.data FROM bundled_active a JOIN bundled_resources b ON a.name=b.name AND a.sha256=b.sha256'):
                db.execute('INSERT OR IGNORE INTO bundled_resources VALUES (?,?,?)', (name, digest, raw))
                db.execute('INSERT OR IGNORE INTO bundled_active VALUES (?,?)', (name, digest))
