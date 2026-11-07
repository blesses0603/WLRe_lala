"""Observed official ServerList.txt -> versioned SQLite, without game login.

Server metadata is verified HTTPS content, not a Manifest-authenticated Bundle.
A refresh never deletes the preceding successful version or changes accounts.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sqlite3
from urllib.request import HTTPRedirectHandler, Request, build_opener

from wlre.services.parser_diagnostics import diagnosed
from wlre.services.official_source import selected_host
from wlre.storage.paths import data_root
from wlre.storage.normalized_resources import load_parsed, _decode

MAX_BYTES = 64 * 1024


def database_path():
    return data_root() / 'official_sync' / 'derived_catalogs' / 'resource_inventory.sqlite3'


def server_list_url(data_ver):
    if type(data_ver) is not str or not re.fullmatch(r'[0-9]{1,4}(?:\.[0-9]{1,4}){2,3}', data_ver):
        raise ValueError('Invalid official server-list version')
    return 'https://' + selected_host() + '/WLN/TW/' + data_ver + '/ResourcesPC/ServerList.txt'


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Official server-list redirects are not permitted')


def fetch_server_list(data_ver, *, opener=None):
    url = server_list_url(data_ver)
    opener = build_opener(_NoRedirect()).open if opener is None else opener
    with opener(Request(url, headers={'Accept': '*/*', 'Cache-Control': 'no-cache',
                                      'User-Agent': 'WLRe-LaLa-ServerList/1'}), timeout=12) as response:
        if response.geturl() != url or getattr(response, 'status', 200) != 200:
            raise ValueError('Unexpected official server-list response')
        raw = response.read(MAX_BYTES + 1)
    if not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('Official server list exceeds quota')
    return raw


@diagnosed('server-list-v1')
def parse_server_list(raw):
    from wlre.storage.server_lines import parse
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('Invalid official server-list size')
    document = json.loads(raw.decode('utf-8-sig'))
    if type(document) is not list or not 0 < len(document) <= 256:
        raise ValueError('Invalid official server-list structure')
    ids = set()
    for row in document:
        if (type(row) is not dict or type(row.get('id')) is not int
                or not 0 < row['id'] <= 65535 or row['id'] in ids
                or type(row.get('name')) is not str or not 0 < len(row['name']) <= 120):
            raise ValueError('Invalid or duplicate official server ID')
        ids.add(row['id'])
        if row['id'] > 100:
            # The observed source supplies literal public IPs. A future hostname
            # needs review; do not turn downloaded metadata into arbitrary URLs.
            if type(row.get('address')) is not str or not ipaddress.ip_address(row['address']).is_global:
                raise ValueError('Official server address is not a public IP')
    rows = parse(document)
    if any(row['id'] // 100 not in ids for row in rows):
        raise ValueError('Official server group is missing')
    return rows


def _state_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS official_server_list_active '
               '(singleton INTEGER PRIMARY KEY CHECK(singleton=1), catalog_key TEXT NOT NULL, '
               'data_ver TEXT NOT NULL, origin TEXT NOT NULL, checked_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS official_server_list_attempt '
               '(singleton INTEGER PRIMARY KEY CHECK(singleton=1), status TEXT NOT NULL, checked_at TEXT NOT NULL)')


def sync_server_list(*, database=None, observe=None, fetch=None):
    from wlre.services.official_resource_sync import observe_official_versions, validate_snapshot
    path = Path(database) if database is not None else database_path()
    observe = observe_official_versions if observe is None else observe
    fetch = fetch_server_list if fetch is None else fetch
    checked = datetime.now(timezone.utc).isoformat(timespec='seconds')
    try:
        before = validate_snapshot(observe())
        raw = fetch(before['data_ver'])
        after = validate_snapshot(observe())
        if any(before[k] != after[k] for k in ('data_ver', 'exe_version', 'packages')):
            raise ValueError('Official versions changed during server-list refresh')
        origin = server_list_url(before['data_ver'])
        identity = hashlib.sha256(origin.encode('ascii') + b'\0' + raw).hexdigest()
        rows = load_parsed(path, identity, 'server_list', 'server-list-v1',
                           {'ServerList.txt': raw}, lambda: parse_server_list(raw))
        with closing(sqlite3.connect(path, timeout=15)) as db:
            db.execute('BEGIN IMMEDIATE')
            _state_schema(db)
            db.execute('INSERT OR REPLACE INTO official_server_list_active VALUES (1,?,?,?,?)',
                       (identity, before['data_ver'], origin, checked))
            db.execute('INSERT OR REPLACE INTO official_server_list_attempt VALUES (1,?,?)', ('updated', checked))
            db.commit()
        return {'status': 'updated', 'count': len(rows), 'origin': origin, 'data_ver': before['data_ver']}
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        # Only record a sanitized failure; never replace the usable active pointer.
        if not path.is_symlink():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(path, timeout=15)) as db, db:
                    _state_schema(db)
                    db.execute('INSERT OR REPLACE INTO official_server_list_attempt VALUES (1,?,?)',
                               ('refresh_failed', checked))
            except (OSError, sqlite3.Error):
                pass
        raise ValueError('Official server-list refresh failed; previous version retained') from error


def _read_cached_server_list(*, database=None):
    """Use only a prior official HTTPS import, never the shipped seed snapshot."""
    path = Path(database) if database is not None else database_path()
    empty = {'status': 'not_downloaded', 'rows': [], 'origin': None, 'checked_at': None}
    if path.is_symlink():
        raise ValueError('Server-list database cannot be a symbolic link')
    if not path.is_file():
        return empty
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='official_server_list_active'").fetchone():
            return empty
        active = db.execute('SELECT catalog_key,data_ver,origin,checked_at FROM official_server_list_active WHERE singleton=1').fetchone()
        attempt = db.execute('SELECT status,checked_at FROM official_server_list_attempt WHERE singleton=1').fetchone()
        if active is None:
            return {**empty, 'status': attempt[0] if attempt else 'not_downloaded'}
        key, version, origin, checked = active
        from wlre.services.official_source import OFFICIAL_HOSTS
        if origin not in tuple('https://' + host + '/WLN/TW/' + version + '/ResourcesPC/ServerList.txt' for host in OFFICIAL_HOSTS):
            raise ValueError('Stored server-list origin is invalid')
        saved = db.execute('SELECT inputs,sha256,data FROM normalized_snapshots '
                           "WHERE catalog_key=? AND feature='server_list' AND schema_id='server-list-v1'", (key,)).fetchone()
        if saved is None or type(saved[2]) is not bytes or hashlib.sha256(saved[2]).hexdigest() != saved[1]:
            raise ValueError('Stored server-list snapshot integrity failure')
        inputs = json.loads(saved[0])
        if type(inputs) is not dict or set(inputs) != {'ServerList.txt'}:
            raise ValueError('Stored server-list input identity failure')
        raw = db.execute('SELECT data FROM normalized_raw WHERE sha256=?', (inputs['ServerList.txt'],)).fetchone()
        if raw is None or type(raw[0]) is not bytes or hashlib.sha256(raw[0]).hexdigest() != inputs['ServerList.txt']:
            raise ValueError('Stored server-list source integrity failure')
        if hashlib.sha256(origin.encode('ascii') + b'\0' + raw[0]).hexdigest() != key:
            raise ValueError('Stored server-list catalog identity failure')
        rows = _decode(saved[2])
        if rows != parse_server_list(raw[0]):
            raise ValueError('Stored server list differs from its official source')
        return {'status': 'cached_after_refresh_failure' if attempt and attempt[0] == 'refresh_failed' else 'cached',
                'rows': rows, 'origin': origin, 'checked_at': checked, 'data_ver': version}


def read_cached_server_list(*, database=None):
    try:
        return _read_cached_server_list(database=database)
    except (sqlite3.Error, TypeError, KeyError, UnicodeError) as error:
        raise ValueError('Stored official server list cannot be read') from error
