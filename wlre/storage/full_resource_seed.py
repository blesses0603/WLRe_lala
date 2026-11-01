"""Build and provision the complete pinned bundled resource database."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
from wlre.storage.resource_seed_manifest import SOURCE_MANIFEST
from wlre.storage.resource_migration import migrate_resources

SEED_NAME = 'resource_catalog_seed.sqlite3'


def verify_seed(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('資源種子資料庫結構損壞')
        names={r[0] for r in db.execute('SELECT name FROM bundled_active')}
        if names != set(SOURCE_MANIFEST):
            raise ValueError('完整資源種子清單不符')
        for name,(size,digest) in SOURCE_MANIFEST.items():
            row=db.execute('SELECT a.sha256,b.data FROM bundled_active a LEFT JOIN bundled_resources b ON a.name=b.name AND a.sha256=b.sha256 WHERE a.name=?',(name,)).fetchone()
            if (row is None or row[0]!=digest or not isinstance(row[1],bytes)
                    or len(row[1])!=size or hashlib.sha256(row[1]).hexdigest()!=digest):
                raise ValueError('資源種子來源校驗失敗：'+name)
    return True


def build_seed(root,destination):
    destination=Path(destination)
    if destination.exists():
        verify_seed(destination)
        return destination
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        staged=Path(directory)/'seed.sqlite3'
        migrate_resources(root,staged)
        verify_seed(staged)
        # Publish without overwriting another build's result.
        import os
        os.link(staged,destination)
    return destination


def provision_seed(seed,database):
    verify_seed(seed)
    database=Path(database);database.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(database,timeout=15)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS bundled_resources (name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(name,sha256))')
        db.execute('CREATE TABLE IF NOT EXISTS bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        with closing(sqlite3.connect(Path(seed).resolve().as_uri()+'?mode=ro',uri=True)) as src:
            for name,(size,digest) in SOURCE_MANIFEST.items():
                active=db.execute('SELECT a.sha256,b.data FROM bundled_active a LEFT JOIN bundled_resources b ON a.name=b.name AND a.sha256=b.sha256 WHERE a.name=?',(name,)).fetchone()
                if active is not None:
                    if not isinstance(active[1],bytes) or hashlib.sha256(active[1]).hexdigest()!=active[0]:
                        raise ValueError('既有資源資料損壞：'+name)
                    continue
                raw=src.execute('SELECT data FROM bundled_resources WHERE name=? AND sha256=?',(name,digest)).fetchone()[0]
                if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=digest:
                    raise ValueError('資源種子在安裝期間變更')
                db.execute('INSERT OR IGNORE INTO bundled_resources VALUES (?,?,?)',(name,digest,raw))
                stored=db.execute('SELECT data FROM bundled_resources WHERE name=? AND sha256=?',(name,digest)).fetchone()
                if stored is None or stored[0]!=raw:
                    raise ValueError('既有歷史資源內容損壞：'+name)
                db.execute('INSERT INTO bundled_active VALUES (?,?)',(name,digest))
    return len(SOURCE_MANIFEST)


def main(argv=None):
    import argparse
    from wlre.paths import RESOURCE_ROOT
    parser=argparse.ArgumentParser(description='依獨立來源 SHA-256 建立完整隨附資源初始資料庫')
    parser.add_argument('--root',type=Path,default=RESOURCE_ROOT)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    build_seed(args.root,args.output)
    print('完整資源種子校驗通過：',len(SOURCE_MANIFEST))
    return 0


def read_config(name, *, root):
    """Read shipped policy/config from the pinned seed, never user SQLite."""
    root=Path(root);seed=root/SEED_NAME
    if not seed.is_file():
        return (root/name).read_bytes()
    verify_seed(seed)
    if name not in SOURCE_MANIFEST:
        raise ValueError('未知的隨附設定')
    with closing(sqlite3.connect(seed.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        digest=SOURCE_MANIFEST[name][1]
        raw=db.execute('SELECT data FROM bundled_resources WHERE name=? AND sha256=?',(name,digest)).fetchone()[0]
    if hashlib.sha256(raw).hexdigest()!=digest:
        raise ValueError('隨附設定來源在讀取期間變更')
    return raw


if __name__=='__main__':
    raise SystemExit(main())
