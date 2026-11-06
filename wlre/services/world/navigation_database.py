"""Atomic, version-pinned navigation previews; unknown caches fail closed."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from wlre.services.world.astar_cache import review_cache

REVIEWED_MODELS = {
    13217: 'a728cd68b449c76d89585bcb2f8c29a7bdd146e5da18d9ad01f6647565e689e6',
    13218: 'ab622995a92f4bc8f6914c716fda0a82bc2bbfc52a3b6636e616c30d25485889',
    13219: '5fb34818dba90dd16c133f2504fd4e3a6da1351eb90262bab538da87b8de61cb',
    13220: '721540e7699eaa738ef8bf899bf2deb9b808fc11cf05c2678efbbf82b003337d',
    13221: '13c46904d5c16e3418f4c2dd7a7ab24621323b8eccad677900c3031c9c3edc3f',
    13222: '4899fcbe081b3f8924219ef26b4ae490afc007c38d85fb9b1b96d7a7dd38f1b9',
    13223: '2bc5d749067948ad630697f71da34d9a79164ca7f8783625a1341b14be3bc455',
    13224: '493c40032453791d503112d95dfc5ab87a5aa9674ba5be50b60122b7abe8b552',
    13225: '713401e696f3befe979e17db6e0182bbcd20822e02cae187dfa83feabc5b10e1',
    13226: 'bd4581bbc2c1661123cd16e46303f0d9e8da63afea47330a50e38fce0b128828',
    13227: 'd95005692c09067a3ca6e5d32759d4ed002baec095535a4f7bc592f141a8ae90',

    12050: '5ce014b21935647aceaeb697cde52110c1509ced3212388972c5f7e0132e004e',
    13216: '998e421e3ec0fe29cd9c5fe215f0336d20a9afb7a6a480d28c135bede226d06f',
    11139: 'aac34ed3b1d41360d48a116a301d60aa523d7df79e986a762e8fc5d71b874ff9',

    10001: '3703387b6fee3cc4e4654ba682366277ec13bc2e90baf8f115c8c31a4785acab',
    12600: '3203818b7256474b28539346256fb08a7e866939e9af8ae5aa0ef1c740526ab0',
    10000: '8260bebfbefe5818ae705595d58f6f2ec3b85a415f778d5312bd5bdda7ddcb8d',
    58001: '9fafab7be0d03215611949d69fbfeecf0ca4bb280f812f2bedda462d6067d227',
    10004: '5ff98ac860fd1f161a9bc5134555fe207afb03a3f3961eb178d2aa35b8ef1384',
    10005: '6e915dac61f477eaa0f2e07bce729d730e1875bad882c80e940fe9d8b1ed5b78',
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS navigation_schema (version INTEGER NOT NULL)')
    rows=db.execute('SELECT version FROM navigation_schema').fetchall()
    if not rows:db.execute('INSERT INTO navigation_schema VALUES (1)')
    elif rows!=[(1,)]:raise ValueError('Unsupported navigation database schema')
    db.execute('CREATE TABLE IF NOT EXISTS navigation_snapshots ('
               'version TEXT, model INTEGER, digest TEXT, provenance TEXT, raw BLOB, geometry TEXT, '
               'PRIMARY KEY(version,model,digest))')
    db.execute('CREATE TABLE IF NOT EXISTS navigation_active ('
               'version TEXT, model INTEGER, digest TEXT, PRIMARY KEY(version,model))')
    db.execute('CREATE TABLE IF NOT EXISTS navigation_attempts ('
               'version TEXT, model INTEGER, status TEXT, detail TEXT)')


def _identity(version, model):
    if not isinstance(version,str) or not re.fullmatch('[0-9a-f]{64}',version) or type(model) is not int or model not in REVIEWED_MODELS:
        raise ValueError('Navigation version or model has not been reviewed')


def import_cache(database, version, model, raw, provenance):
    """Validate before any activation; preserve source bytes and old snapshots."""
    _identity(version,model)
    if hashlib.sha256(raw).hexdigest()!=REVIEWED_MODELS[model]:
        raise ValueError('Navigation cache does not match reviewed model')
    result=review_cache(raw)
    normalized=_json(result);source=_json(provenance)
    database=Path(database);database.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(database)) as db, db:
        _schema(db)
        db.execute('INSERT OR REPLACE INTO navigation_snapshots VALUES (?,?,?,?,?,?)',
                   (version,model,REVIEWED_MODELS[model],source,raw,normalized))
        db.execute('INSERT OR REPLACE INTO navigation_active VALUES (?,?,?)',
                   (version,model,REVIEWED_MODELS[model]))
        db.execute('INSERT INTO navigation_attempts VALUES (?,?,?,?)',(version,model,'ready',source))
    return result


def record_failure(database,version,model,error):
    _identity(version,model)
    database=Path(database);database.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(database)) as db, db:
        _schema(db)
        db.execute('INSERT INTO navigation_attempts VALUES (?,?,?,?)',(version,model,'failed',str(error)[:300]))


def load_cache(database,version,model):
    _identity(version,model)
    database=Path(database)
    if not database.is_file():return None
    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('SELECT version FROM navigation_schema').fetchall()!=[(1,)]:
            raise ValueError('Unsupported navigation database schema')
        row=db.execute('SELECT s.raw,s.geometry,s.digest FROM navigation_snapshots s JOIN navigation_active a '
                       'ON a.version=s.version AND a.model=s.model AND a.digest=s.digest '
                       'WHERE a.version=? AND a.model=?',(version,model)).fetchone()
    if row is None:return None
    raw,normalized,digest=row
    if digest!=REVIEWED_MODELS[model] or hashlib.sha256(raw).hexdigest()!=digest:
        raise ValueError('Navigation database integrity failure')
    expected=review_cache(raw)
    if normalized!=_json(expected):raise ValueError('Normalized navigation data differs from verified source')
    return json.loads(normalized)


def database_path(root=None):
    from wlre.storage.paths import data_root
    root=Path(root) if root is not None else data_root()/'official_sync'
    return root/'derived_catalogs'/'navigation.sqlite3'
