"""Versioned normalized resource snapshots; callers verify official bytes first.

Only derived data is repaired. Unknown binary formats and damaged raw storage
fail closed. SQLite publication is atomic; failed imports retain their inputs.
This database never grants permission to log in or send game packets.
"""
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

FORMAT_VERSION = 1
MAX_BYTES = 64 * 1024 * 1024


def _pack(value):
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) in (list, tuple):
        return ['tuple' if type(value) is tuple else 'list', [_pack(v) for v in value]]
    if type(value) is dict:
        return ['dict', [[_pack(k), _pack(v)] for k, v in value.items()]]
    raise ValueError('Unsupported normalized resource value')


def _unpack(value):
    if type(value) is not list:
        if value is None or type(value) in (str, bool, int):
            return value
        if type(value) is float and math.isfinite(value):
            return value
        raise ValueError('Invalid normalized scalar')
    if len(value) != 2 or type(value[1]) is not list:
        raise ValueError('Invalid normalized container')
    tag, rows = value
    if tag in ('list', 'tuple'):
        result = [_unpack(v) for v in rows]
        return tuple(result) if tag == 'tuple' else result
    if tag == 'dict':
        result = {}
        for pair in rows:
            if type(pair) is not list or len(pair) != 2:
                raise ValueError('Invalid normalized mapping')
            key, item = map(_unpack, pair)
            if key in result:
                raise ValueError('Duplicate normalized key')
            result[key] = item
        return result
    raise ValueError('Unknown normalized container')


def _encode(value):
    raw = json.dumps(_pack(value), ensure_ascii=True, allow_nan=False,
                     separators=(',', ':')).encode('ascii')
    if len(raw) > MAX_BYTES:
        raise ValueError('Normalized resource exceeds quota')
    return raw


def _decode(raw):
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        raise ValueError('Invalid normalized payload')
    return _unpack(json.loads(raw))


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS normalized_schema (version INTEGER NOT NULL)')
    versions = db.execute('SELECT version FROM normalized_schema').fetchall()
    if not versions:
        db.execute('INSERT INTO normalized_schema VALUES (?)', (FORMAT_VERSION,))
    elif versions != [(FORMAT_VERSION,)]:
        raise ValueError('Unsupported normalized database version; upgrade required')
    db.execute('CREATE TABLE IF NOT EXISTS normalized_raw '
               '(sha256 TEXT PRIMARY KEY, data BLOB NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS normalized_snapshots '
               '(catalog_key TEXT, feature TEXT, schema_id TEXT, inputs TEXT NOT NULL, '
               'sha256 TEXT NOT NULL, data BLOB NOT NULL, '
               'PRIMARY KEY(catalog_key,feature,schema_id))')
    db.execute('CREATE TABLE IF NOT EXISTS normalized_history '
               '(id INTEGER PRIMARY KEY, catalog_key TEXT, feature TEXT, schema_id TEXT, '
               'status TEXT NOT NULL, inputs TEXT NOT NULL, sha256 TEXT, data BLOB)')


def load_parsed(database, catalog_key, feature, schema_id, payloads, parse):
    """Import or read one exact source set, preserving Python IDs/tuples in JSON.

    The caller must independently verify payloads against the current official
    manifest on EVERY call. schema_id must change when parser semantics change.
    No fallback to a different catalog or schema is ever performed. Existing
    application compatibility/relationship checks still run on returned data.
    """
    if (type(catalog_key) is not str or not re.fullmatch('[a-f0-9]{64}', catalog_key)
            or any(type(v) is not str or not re.fullmatch('[a-zA-Z0-9_.:-]{1,160}', v)
                   for v in (feature, schema_id))
            or type(payloads) is not dict or not payloads
            or any(type(k) is not str or not re.fullmatch('[a-zA-Z0-9_.-]{1,120}', k)
                   or type(v) is not bytes or not 0 < len(v) <= MAX_BYTES
                   for k, v in payloads.items())
            or sum(map(len, payloads.values())) > MAX_BYTES):
        raise ValueError('Invalid normalized import identity or sources')
    path = Path(database)
    if path.is_symlink():
        raise ValueError('Normalized database cannot be a symbolic link')
    path.parent.mkdir(parents=True, exist_ok=True)
    inputs = json.dumps({k: _digest(v) for k, v in sorted(payloads.items())}, sort_keys=True)
    key = (catalog_key, feature, schema_id)
    # Serialize readers/importers so concurrent launches cannot publish mixed sets.
    with closing(sqlite3.connect(path, timeout=15)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            _schema(db)
            for raw in payloads.values():
                digest = _digest(raw)
                old = db.execute('SELECT data FROM normalized_raw WHERE sha256=?', (digest,)).fetchone()
                if old is not None and old[0] != raw:
                    raise ValueError('Stored raw resource integrity failure; original source retained')
                db.execute('INSERT OR IGNORE INTO normalized_raw VALUES (?,?)', (digest, raw))
            previous = db.execute('SELECT inputs,sha256,data FROM normalized_snapshots '
                                  'WHERE catalog_key=? AND feature=? AND schema_id=?', key).fetchone()
            if previous is not None:
                if previous[0] != inputs:
                    raise ValueError('Source changed for immutable catalog identity')
                try:
                    if type(previous[2]) is not bytes or _digest(previous[2]) != previous[1]:
                        raise ValueError('Derived checksum mismatch')
                    result = _decode(previous[2])
                except (ValueError, TypeError, RecursionError, UnicodeError):
                    pass  # Rebuild only from caller-verified exact source bytes.
                else:
                    db.commit()
                    return result
            try:
                result = parse()
                encoded = _encode(result)
                # Verify lossless serialization before any snapshot is published.
                if _decode(encoded) != result:
                    raise ValueError('Normalized round trip failed')
            except Exception:
                db.execute('INSERT INTO normalized_history '
                           '(catalog_key,feature,schema_id,status,inputs) VALUES (?,?,?,?,?)',
                           (*key, 'parse_failed', inputs))
                db.commit()  # Preserve failed raw inputs, never replace prior snapshot.
                raise
            if previous is not None:
                db.execute('INSERT INTO normalized_history '
                           '(catalog_key,feature,schema_id,status,inputs,sha256,data) VALUES (?,?,?,?,?,?,?)',
                           (*key, 'repaired_derived', *previous))
            else:
                db.execute('INSERT INTO normalized_history '
                           '(catalog_key,feature,schema_id,status,inputs) VALUES (?,?,?,?,?)',
                           (*key, 'imported', inputs))
            db.execute('INSERT OR REPLACE INTO normalized_snapshots VALUES (?,?,?,?,?,?)',
                       (*key, inputs, _digest(encoded), encoded))
            db.commit()
            # Runtime always consumes the stored representation, including first import.
            return _decode(encoded)
        except BaseException:
            db.rollback()
            raise


def inspect_database(database):
    """Return bounded source/checksum/status metadata without resource content."""
    path = Path(database)
    if path.is_symlink() or not path.is_file():
        return {'status': 'unavailable', 'snapshots': [], 'events': []}
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'normalized_schema' not in names:
            return {'status': 'not_imported', 'snapshots': [], 'events': []}
        if db.execute('SELECT version FROM normalized_schema').fetchall() != [(FORMAT_VERSION,)]:
            raise ValueError('Unsupported normalized database version')
        rows = db.execute('SELECT catalog_key,feature,schema_id,inputs,sha256,data '
                          'FROM normalized_snapshots ORDER BY catalog_key,feature LIMIT 1000')
        snapshots = []
        for key, feature, schema, inputs, digest, data in rows:
            status = 'verified_checksum'
            try:
                if type(data) is not bytes or _digest(data) != digest:
                    raise ValueError('checksum')
                _decode(data)
            except (ValueError, TypeError, RecursionError, UnicodeError):
                status = 'derived_rebuild_required'
            try:
                sources = json.loads(inputs)
                if type(sources) is not dict:
                    raise ValueError('inputs')
                for source_digest in sources.values():
                    raw = db.execute('SELECT data FROM normalized_raw WHERE sha256=?', (source_digest,)).fetchone()
                    if raw is None or type(raw[0]) is not bytes or _digest(raw[0]) != source_digest:
                        status = 'raw_integrity_failed'
            except (ValueError, TypeError, sqlite3.Error):
                status = 'source_metadata_invalid'
                sources = {}
            snapshots.append(dict(catalog_key=key, feature=feature, schema_id=schema,
                                  source_sha256=sources, status=status))
        events = [dict(sequence=r[0], catalog_key=r[1], feature=r[2], schema_id=r[3], status=r[4])
                  for r in db.execute('SELECT id,catalog_key,feature,schema_id,status '
                                      'FROM normalized_history ORDER BY id DESC LIMIT 100')]
        return {'status': 'inspected', 'schema_version': FORMAT_VERSION,
                'snapshots': snapshots, 'events': events, 'can_send_packets': False}
