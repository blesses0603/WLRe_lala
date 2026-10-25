"""Read-only feature-to-official-resource map for LaLa desktop modules.

This reads the private, path-only classification made by the PR #56 Launcher.
It must NEVER authorize NPC trades, item use, crafting, expeditions or login.
Verified gameplay data still comes exclusively from the existing pinned runtime
and independent server packet/state validation.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from wlre.storage.paths import data_root

MAX_INDEX_BYTES = 16 * 1024 * 1024
_ROOT = 'Assets/ResourcesBuild/Data/'
# Exact official table names, not heuristic category labels.
FEATURE_TABLES = {
    'npc': ('Eve', 'NpcData_C', 'TalkData_C'),
    'bag': ('ItemData_C',),
    'crafting': ('SmithData_C', 'ItemData_C'),
    'expedition': ('AdventureData_C', 'AdventureLvData_C',
                   'NpcData_C', 'NpcCareerData_C', 'TextData_C'),
}
MESSAGES = {
    'index_unavailable': '尚無同版本官方分類索引',
    'version_mismatch': '官方分類版本與 LaLa 正式資料基準不同',
    'manifest_only': '已分類定位，尚無全部本機原始資料',
    'partial_local': '部分原始資料已保存，仍有缺口',
    'all_local_unapproved': '原始資料均已保存，但不能代替正式相容性驗證',
}


@lru_cache(maxsize=4)
def _read_index(filename, mtime_ns, size):
    # Time/size keys permit refreshing after Launcher atomically updates the file.
    if not 0 < size <= MAX_INDEX_BYTES:
        return None
    try:
        with Path(filename).open('rb') as file:
            body = file.read(MAX_INDEX_BYTES + 1)
        if len(body) != size:
            return None
        return json.loads(body.decode('utf-8'))
    except (OSError, ValueError, UnicodeError):
        return None


def _current_index(root):
    """Only select a catalog explicitly named by the current Launcher receipt."""
    from wlre.services.world.launcher_catalog import read_launcher_status
    receipt = read_launcher_status(root=root)
    if not receipt or receipt.get('schema_version') != 2:
        return None
    key = receipt.get('catalog_key')
    if type(key) is not str or len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        return None
    target = root / 'derived_catalogs' / key / 'asset_classification.json'
    try:
        if target.is_symlink() or not target.is_file():
            return None
        info = target.stat()
        doc = _read_index(str(target), info.st_mtime_ns, info.st_size)
        if type(doc) is not dict or doc.get('catalog_key') != key:
            return None
        return doc
    except OSError:
        return None


def describe_feature(feature, *, report=None, revisions=None, root=None):
    """Status for display/diagnostics only; never a gameplay readiness flag.

    Explicit report/revisions injection is for offline tests. It must not be
    used to authorize commands or replace release-pinned data.
    """
    if feature not in FEATURE_TABLES:
        raise ValueError('未知 LaLa 功能分類')
    expected = tuple(_ROOT + table + '.bytes' for table in FEATURE_TABLES[feature])
    status = {'feature': feature, 'required_assets': list(expected),
              'collected': 0, 'required': len(expected),
              'missing': list(expected), 'state': 'index_unavailable',
              'message': MESSAGES['index_unavailable'], 'display_only': True,
              'assets_ready': False, 'can_send_packets': False}
    if revisions is None:
        from wlre.services.resource_compatibility import load_supported_resources
        packages = load_supported_resources()['packages']
        revisions = {p: packages[p]['manifest']
                     for p in ('DataPackage', 'MainPackage')}
    if report is None:
        sync_root = Path(root) if root is not None else data_root() / 'official_sync'
        report = _current_index(sync_root)
    if (type(report) is not dict or report.get('schema_version') != 1
            or report.get('approved') is not False
            or report.get('assets_ready') is not False
            or report.get('can_send_packets') is not False):
        return status
    packages = report.get('packages')
    if (type(packages) is not dict
            or any(type(packages.get(p)) is not dict or
                   packages[p].get('revision') != revisions.get(p)
                   for p in ('DataPackage', 'MainPackage'))):
        return {**status, 'state': 'version_mismatch',
                'message': MESSAGES['version_mismatch']}
    assets = report.get('assets')
    if type(assets) is not list or len(assets) > 30000:
        return status
    rows = {}
    for row in assets:
        if type(row) is not dict or row.get('package') != 'DataPackage':
            continue
        path = row.get('asset_path')
        if path not in expected:
            continue
        if path in rows or row.get('revision') != revisions['DataPackage'] or not isinstance(row.get('bundle'), str):
            return status
        if row.get('status') not in ('manifest_only', 'local_checksum_checked_not_approved'):
            return status
        rows[path] = row
    collected = sum(row['status'] == 'local_checksum_checked_not_approved'
                    for row in rows.values())
    missing = [path for path in expected if path not in rows or
               rows[path]['status'] != 'local_checksum_checked_not_approved']
    if collected == len(expected):
        state = 'all_local_unapproved'
    elif collected:
        state = 'partial_local'
    else:
        state = 'manifest_only'
    return {**status, 'collected': collected,
            'missing': missing, 'state': state, 'message': MESSAGES[state]}


def feature_note(feature):
    result = describe_feature(feature)
    return '官方資源：' + result['message'] + f"（{result['collected']}/{result['required']}）"
