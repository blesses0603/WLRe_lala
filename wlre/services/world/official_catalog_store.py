"""Atomic SQLite storage for fully verified official catalog sources.

Official metadata is independent of legacy tables and grants no gameplay authority.
"""
from __future__ import annotations

import sqlite3
import re
from contextlib import closing
from pathlib import Path

from wlre.services.world.catalog_adapters import FEATURES, ParsedCatalog


def store_official_catalog(db_path, parsed):
    """Publish four already-validated sources in one SQLite transaction.

    Any incomplete or malformed input leaves the active version unchanged.
    """
    if type(parsed) is not dict or set(parsed) != set(FEATURES):
        raise ValueError('Four verified official sources required')
    keys = set()
    for feature in FEATURES:
        item = parsed[feature]
        if (type(item) is not ParsedCatalog or item.feature != feature
                or type(item.catalog_key) is not str
                or len(item.catalog_key) != 64
                or any(ch not in '0123456789abcdef' for ch in item.catalog_key)
                or type(item.source_sha256) is not str
                or len(item.source_sha256) != 64
                or any(ch not in '0123456789abcdef' for ch in item.source_sha256)
                or item.assets_ready is not False
                or item.can_send_packets is not False):
            raise ValueError('Invalid official source verification')
        keys.add(item.catalog_key)
    if len(keys) != 1:
        raise ValueError('Official source versions are inconsistent')
    key = keys.pop()
    path = Path(db_path)
    if not path.parent.is_dir():
        raise ValueError('Official database parent directory missing')
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA busy_timeout=5000')
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS official_catalog_versions '
                       '(catalog_key TEXT PRIMARY KEY, verified_count INTEGER NOT NULL CHECK(verified_count=4))')
            db.execute('CREATE TABLE IF NOT EXISTS official_catalog_sources '
                       '(catalog_key TEXT NOT NULL, feature TEXT NOT NULL, '
                       'source_name TEXT NOT NULL, schema_id TEXT NOT NULL, '
                       'sha256 TEXT NOT NULL, record_count INTEGER NOT NULL, '
                       'PRIMARY KEY(catalog_key,feature))')
            db.execute('CREATE TABLE IF NOT EXISTS official_catalog_active '
                       '(singleton INTEGER PRIMARY KEY CHECK(singleton=1), catalog_key TEXT NOT NULL)')
            for feature in FEATURES:
                item = parsed[feature]
                old = db.execute('SELECT source_name,schema_id,sha256,record_count '
                                 'FROM official_catalog_sources WHERE catalog_key=? AND feature=?',
                                 (key, feature)).fetchone()
                values = (item.source_name, item.schema_id, item.source_sha256, item.record_count)
                if old is not None and old != values:
                    raise ValueError('Immutable official source identity changed')
                db.execute('INSERT OR IGNORE INTO official_catalog_sources VALUES (?,?,?,?,?,?)',
                           (key, feature, *values))
            db.execute('INSERT OR IGNORE INTO official_catalog_versions VALUES (?,4)', (key,))
            db.execute('INSERT INTO official_catalog_active VALUES (1,?) '
                       'ON CONFLICT(singleton) DO UPDATE SET catalog_key=excluded.catalog_key', (key,))
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return key


def active_official_catalog(db_path):
    """Read active source metadata; never returns runtime permission."""
    path = Path(db_path)
    if not path.is_file():
        return None
    with closing(sqlite3.connect(f'file:{path.resolve().as_posix()}?mode=ro', uri=True)) as db:
        try:
            row = db.execute('SELECT catalog_key FROM official_catalog_active WHERE singleton=1').fetchone()
            if row is None:
                return None
            records = db.execute('SELECT feature,source_name,schema_id,sha256,record_count '
                                 'FROM official_catalog_sources WHERE catalog_key=?', (row[0],)).fetchall()
        except sqlite3.OperationalError:
            return None
    if (len(records) != len(FEATURES)
            or {r[0] for r in records} != set(FEATURES)
            or not isinstance(row[0], str)
            or re.fullmatch(r'[0-9a-f]{64}', row[0]) is None):
        return None
    for feature, source, schema, digest, count in records:
        if (type(source) is not str or not source or len(source) > 120
                or type(schema) is not str or not schema
                or type(digest) is not str
                or re.fullmatch(r'[0-9a-f]{64}', digest) is None
                or type(count) is not int or not 0 <= count <= 20000):
            return None
    return {'catalog_key': row[0], 'sources': {r[0]: {'source_name': r[1],
            'schema_id': r[2], 'sha256': r[3], 'record_count': r[4]} for r in records},
            'assets_ready': False, 'can_send_packets': False}
