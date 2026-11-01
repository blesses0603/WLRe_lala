"""唯讀稽核所有隨附 JSON/ZIP/GZ 是否已完整保存於 bundled SQLite。

不會匯入、覆寫、刪除或修改任何檔案及資料庫。
用法：py -3 -m tools.audit_all_resource_database
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

from wlre.paths import RESOURCE_ROOT
from wlre.storage.paths import data_root

SUFFIXES = frozenset(('.json', '.zip', '.gz'))
LEGACY = frozenset((
    'instance_catalog_1262.json', 'npc_battle_talk_1262.json.gz',
    'npc_event_index_1262.json.gz', 'npc_interact_1262.json.gz',
    'npc_talk_1262.json.gz', 'npc_text_1262.json.gz',
))
# The audit does not authorize deleting resources or changing packaging.
KEEP_AS_FILES = frozenset((
    'default_profile.json', 'server_list.json', 'lala_supported_resources.json',
    'emoji_images.zip', 'item_icons.zip', 'smallmaps.zip',
))


def _recommendation(name):
    if name in KEEP_AS_FILES:
        return 'keep_as_file'
    if name in LEGACY:
        return 'legacy_verify_runtime_before_removal'
    return 'review_for_database_migration'


def audit(database, root=RESOURCE_ROOT):
    root, database = Path(root), Path(database)
    paths = sorted((p for p in root.rglob('*')
                    if p.is_file() and p.suffix.lower() in SUFFIXES),
                   key=lambda p: p.relative_to(root).as_posix())
    result = {'database': str(database), 'read_only': True, 'files': [],
              'summary': {}, 'all_identical': False}
    if not database.is_file():
        result['error'] = 'database_missing'
        return result
    try:
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'bundled_resources', 'bundled_active'} <= tables:
                result['error'] = 'bundled_tables_missing'
                return result
            for path in paths:
                name = path.relative_to(root).as_posix()
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                row = {'name': name, 'size': len(raw), 'sha256': digest,
                       'recommendation': _recommendation(name)}
                active = db.execute('SELECT sha256 FROM bundled_active WHERE name=?',
                                    (name,)).fetchone()
                if active is None:
                    row['status'] = 'not_imported'
                elif active[0] != digest:
                    row['status'] = 'active_hash_mismatch'
                    row['database_sha256'] = active[0]
                else:
                    stored = db.execute(
                        'SELECT data FROM bundled_resources WHERE name=? AND sha256=?',
                        (name, digest)).fetchone()
                    if stored is None:
                        row['status'] = 'blob_missing'
                    elif not isinstance(stored[0], bytes) or hashlib.sha256(stored[0]).hexdigest() != digest:
                        row['status'] = 'blob_corrupt'
                    elif stored[0] != raw:
                        row['status'] = 'content_mismatch'
                    else:
                        row['status'] = 'identical'
                result['files'].append(row)
    except (sqlite3.DatabaseError, OSError) as exc:
        result['error'] = type(exc).__name__
        return result
    result['summary'] = dict(sorted(Counter(row['status'] for row in result['files']).items()))
    result['summary']['total'] = len(result['files'])
    result['all_identical'] = bool(result['files']) and all(
        row['status'] == 'identical' for row in result['files'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=(
        data_root() / 'official_sync' / 'derived_catalogs' / 'resource_inventory.sqlite3'))
    parser.add_argument('--root', type=Path, default=RESOURCE_ROOT)
    args = parser.parse_args(argv)
    result = audit(args.database, args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get('error') else 1


if __name__ == '__main__':
    raise SystemExit(main())
