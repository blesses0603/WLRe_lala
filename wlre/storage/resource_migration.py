"""Transactional replacement storage for bundled JSON/ZIP/GZ resources."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3


def migrate_resources(root, database):
    """Verify existing rows, then import all resources atomically; keep history."""
    root, database = Path(root), Path(database)
    files = sorted(p for p in root.iterdir()
                   if p.is_file() and p.suffix in ('.json', '.zip', '.gz'))
    if not files:
        from wlre.storage.full_resource_seed import SEED_NAME, provision_seed
        if (root / SEED_NAME).is_file():
            return provision_seed(root / SEED_NAME, database)
        raise ValueError('沒有可匯入的資源或完整初始資料庫')
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=15)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS bundled_resources (name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(name,sha256))')
        db.execute('CREATE TABLE IF NOT EXISTS bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        for name, digest, raw in db.execute(
                'SELECT a.name,a.sha256,b.data FROM bundled_active a LEFT JOIN bundled_resources b ON a.name=b.name AND a.sha256=b.sha256'):
            if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('既有資源資料庫損壞：' + name)
        for path in files:
            with path.open('rb') as stream:
                raw = stream.read(64 * 1024 * 1024 + 1)
            if len(raw) > 64 * 1024 * 1024:
                raise ValueError('資源超過大小限制：' + path.name)
            digest = hashlib.sha256(raw).hexdigest()
            db.execute('INSERT OR IGNORE INTO bundled_resources VALUES (?,?,?)',
                       (path.name, digest, raw))
            stored = db.execute('SELECT data FROM bundled_resources WHERE name=? AND sha256=?',
                                (path.name, digest)).fetchone()
            if stored is None or stored[0] != raw:
                raise ValueError('資料庫資源內容校驗失敗：' + path.name)
            db.execute('INSERT INTO bundled_active VALUES (?,?) ON CONFLICT(name) DO UPDATE SET sha256=excluded.sha256',
                       (path.name, digest))
    return len(files)


def main(argv=None):
    import argparse
    from wlre.paths import RESOURCE_ROOT
    from wlre.storage.paths import data_root
    parser = argparse.ArgumentParser(description='完整匯入隨附資源至 SQLite 並逐檔核對；保留原始檔')
    parser.add_argument('--root', type=Path, default=RESOURCE_ROOT)
    parser.add_argument('--database', type=Path, default=data_root() / 'official_sync' / 'derived_catalogs' / 'resource_inventory.sqlite3')
    args = parser.parse_args(argv)
    print('已匯入並核對資源：', migrate_resources(args.root, args.database))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
