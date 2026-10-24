"""Read-only, integrity-checked access to auto-rebuilt official candidate indexes.

Candidate indexes are bound to the current Launcher catalog identity, not the
official runtime's release-pinned approval. They may be shown in the UI only:
never use these values for actions, inventory effects or packet decisions.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile, BadZipFile

from wlre.storage.paths import data_root

_ALLOWED = {
    'item_data': ('ItemData_C', 20000),
}
_KEY = re.compile(r'[0-9a-f]{64}\Z')
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_INDEX = 16 * 1024 * 1024
MAX_INVENTORY = 128 * 1024


def _candidate_path(root):
    from wlre.services.world.launcher_catalog import read_launcher_status
    receipt = read_launcher_status(root=root)
    if receipt is None:
        return None
    key = receipt.get('catalog_key')
    if (type(key) is not str or not _KEY.fullmatch(key)
            or receipt['status'] not in ('review_required', 'downloaded_unparsed')
            or receipt.get('can_send_packets') is not False
            or receipt.get('assets_ready') is not False):
        return None
    target = Path(root) / 'derived_catalogs' / key / 'verified_raw_inventory.zip'
    if target.is_symlink():
        return None
    return target, key


@lru_cache(maxsize=4)
def _load(path, key, kind, mtime_ns, length):
    source, max_rows = _ALLOWED[kind]
    if not 0 < length <= MAX_ARCHIVE:
        return None
    member = 'candidate_indexes/' + kind + '.json'
    try:
        with ZipFile(path) as archive:
            if len(archive.infolist()) > 270:
                return None
            meta = archive.getinfo('inventory.json')
            if not 0 < meta.file_size <= MAX_INVENTORY:
                return None
            inventory = json.loads(archive.read(meta))
            if (type(inventory) is not dict
                    or inventory.get('schema_version') != 1
                    or inventory.get('catalog_key') != key
                    or inventory.get('formal_approved') is not False
                    or inventory.get('assets_ready') is not False
                    or inventory.get('can_send_packets') is not False
                    or inventory.get('protocol_compatibility') != 'unverified'
                    or type(inventory.get('entries')) is not dict):
                return None
            entry = inventory['entries'].get(member)
            if (type(entry) is not dict
                    or entry.get('source') != 'derived_unapproved'
                    or type(entry.get('size')) is not int
                    or type(entry.get('sha256')) is not str
                    or not _KEY.fullmatch(entry['sha256'])):
                return None
            info = archive.getinfo(member)
            if not 0 < info.file_size <= MAX_INDEX or info.file_size != entry['size']:
                return None
            raw = archive.read(info)
            if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                return None
            doc = json.loads(raw)
            if (type(doc) is not dict or doc.get('revision') != 1275
                    or doc.get('source') != source
                    or doc.get('record_count') != len(doc.get('records', {}))
                    or type(doc.get('records')) is not dict
                    or not 0 <= doc['record_count'] <= max_rows
                    or doc.get('approved') is True
                    or doc.get('can_send_packets') is True):
                return None
            return doc['records']
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, BadZipFile):
        return None


def candidate_item_name(item_id, *, root=None):
    """Show a locally reconstructed, explicitly unapproved name if available."""
    if type(item_id) is not int or not 1 <= item_id <= 65535:
        return None
    base = Path(root) if root is not None else data_root() / 'official_sync'
    located = _candidate_path(base)
    if located is None:
        return None
    path, key = located
    try:
        if not path.is_file():
            return None
        stat = path.stat()
        rows = _load(str(path), key, 'item_data', stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None
    if rows is None:
        return None
    value = rows.get(str(item_id))
    if type(value) is not dict:
        return None
    name = value.get('name')
    if (type(name) is not str or not name.strip() or len(name) > 256
            or any(ord(c) < 32 and c not in '\r\n\t' for c in name)):
        return None
    return name
