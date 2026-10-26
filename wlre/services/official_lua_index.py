"""Read-only PC LuaScriptPathList inventory and hash-difference checker.

This module never downloads Lua sources, executes code, or modifies the
release-reviewed LaLa compatibility baseline. Only the game's published
relative-path/MD5 list is observed and cached privately for comparison.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.request import build_opener

from wlre.storage.paths import data_root
from wlre.resources_runtime.downloader import DownloadManager
from wlre.resources_runtime.downloader.https import NoRedirect as _NoRedirect
from wlre.resources_runtime.official.source import ROOT as OFFICIAL_LUA_BASE


MAX_LIST_BYTES = 512 * 1024
MAX_ENTRIES = 20000
_DATA_VER = re.compile(r'[0-9]{1,4}(?:\.[0-9]{1,4}){2}\Z')
_PART = re.compile(r'[A-Za-z0-9_.-]{1,100}\Z')
_MD5 = re.compile(r'[A-Fa-f0-9]{32}\Z')


class LuaIndexError(ValueError):
    pass


def list_url(data_ver):
    if not isinstance(data_ver, str) or not _DATA_VER.fullmatch(data_ver):
        raise LuaIndexError('Invalid official DataVer for LuaScripts')
    return OFFICIAL_LUA_BASE + '/' + data_ver + '/LuaScripts/LuaScriptPathList.txt'


def parse_list(body):
    """Strict path|MD5 table; reject traversal, duplicates and bad encodings."""
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_LIST_BYTES:
        raise LuaIndexError('Official Lua list is empty or too large')
    try:
        source = body.decode('utf-8-sig')
    except UnicodeError as exc:
        raise LuaIndexError('Official Lua list must be UTF-8') from exc
    result = {}
    for lineno, row in enumerate(source.splitlines(), start=1):
        if not row.strip():
            continue
        fields = row.split('|')
        if len(fields) != 2:
            raise LuaIndexError(f'Invalid Lua list record at line {lineno}')
        path, md5 = fields[0].strip(), fields[1].strip()
        pieces = path.split('/')
        if (len(path) > 255 or len(pieces) < 2 or pieces[0] != 'Lua' or
                not path.endswith('.lua') or
                any(not _PART.fullmatch(piece) or piece in ('.', '..') for piece in pieces) or
                not _MD5.fullmatch(md5)):
            raise LuaIndexError(f'Unsafe Lua list path/hash at line {lineno}')
        if path in result:
            raise LuaIndexError('Duplicate Lua entry: ' + path)
        result[path] = md5.lower()
        if len(result) > MAX_ENTRIES:
            raise LuaIndexError('Too many Lua list records')
    if not result:
        raise LuaIndexError('Official Lua list has no records')
    return result


def fetch_list(data_ver, *, opener=None, timeout=12, cache_bust=True):
    """Fetch the one fixed official index URL with a bounded response."""
    canonical = list_url(data_ver)
    url = canonical + ('?' + str(time.time()) if cache_bust else '')
    opener = build_opener(_NoRedirect()).open if opener is None else opener
    try:
        with DownloadManager(opener=opener, timeout=timeout) as manager:
            raw = manager.read(url, limit=MAX_LIST_BYTES)
    except (OSError, ValueError) as exc:
        raise LuaIndexError('Cannot reach or validate official Lua list endpoint') from exc
    return parse_list(raw)


def compare_lists(current, previous=None):
    if not isinstance(current, dict) or not current:
        raise LuaIndexError('Current Lua list missing')
    if previous is None:
        return {'first_observation': True, 'added': len(current),
                'modified': 0, 'removed': 0, 'unchanged': 0}
    if not isinstance(previous, dict):
        raise LuaIndexError('Previous Lua list invalid')
    common = current.keys() & previous.keys()
    return {'first_observation': False, 'added': len(current.keys() - previous.keys()),
            'modified': sum(current[name] != previous[name] for name in common),
            'removed': len(previous.keys() - current.keys()),
            'unchanged': sum(current[name] == previous[name] for name in common)}


def cache_path(data_ver, base=None):
    list_url(data_ver)
    return (Path(base) if base is not None else data_root() / 'official_sync') / ('lua_' + data_ver + '.json')


def load_cache(data_ver, base=None):
    target = cache_path(data_ver, base)
    if not target.is_file():
        return None
    try:
        if target.stat().st_size > MAX_LIST_BYTES * 2:
            raise LuaIndexError('Lua list cache too large')
        document = json.loads(target.read_text(encoding='utf-8'))
        if (not isinstance(document, dict) or document.get('data_ver') != data_ver or
                document.get('schema_version') != 1 or
                document.get('origin') != 'official_pc_lua_list' or
                not isinstance(document.get('entries'), dict)):
            raise LuaIndexError('Lua list cache schema invalid')
        # Recheck all cache paths/hashes with the same strict parser.
        rows = ('\n'.join(name + '|' + digest for name, digest in document['entries'].items())).encode('utf-8')
        return parse_list(rows)
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise LuaIndexError('Lua list cache corrupted') from exc


def save_cache(data_ver, entries, *, base=None):
    target = cache_path(data_ver, base)
    parsed = parse_list(('\n'.join(name + '|' + md5 for name, md5 in entries.items())).encode('utf-8'))
    payload = json.dumps({'schema_version': 1, 'origin': 'official_pc_lua_list',
                          'data_ver': data_ver, 'entries': parsed,
                          'checked_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')},
                         ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(payload) > MAX_LIST_BYTES * 2:
        raise LuaIndexError('Lua cache exceeds size limit')
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.lua_index_',
                                         suffix='.tmp', delete=False) as handle:
            pending = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, target)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return target
