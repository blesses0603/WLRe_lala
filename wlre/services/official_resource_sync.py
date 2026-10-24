"""Standalone-PC official CDN bootstrap: version metadata only (phase 1).

Does not assume an installed Unity player, download guessed Manifest/Bundle URLs,
alter the release-reviewed compatibility baseline, or imply assets are ready.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile


SCHEMA = 1
PACKAGES = ('DataPackage', 'MainPackage')
SNAPSHOT_NAME = 'pc_versions.json'
MAX_SNAPSHOT_BYTES = 4096
_DATA_VERSION = re.compile(r'[0-9]{1,4}(?:\.[0-9]{1,4}){2}\Z')
_PACKAGE_VERSION = re.compile(r'[1-9][0-9]{0,5}_20[0-9]{2}(?:_[0-9]{2}){6}\Z')


class OfficialSyncError(ValueError):
    """Official metadata or previously cached metadata is unusable."""


def snapshot_path(base=None):
    from wlre.storage.paths import data_root
    return data_root(base) / 'official_sync' / SNAPSHOT_NAME


def validate_snapshot(value):
    """Snapshots hold non-sensitive version identifiers, never game files."""
    if (not isinstance(value, dict) or
            set(value) != {'schema_version', 'origin', 'data_ver', 'exe_version',
                           'packages', 'checked_at_utc', 'assets_ready'} or
            type(value['schema_version']) is not int or value['schema_version'] != SCHEMA or
            value['origin'] != 'official_pc_version_endpoint' or
            not isinstance(value['data_ver'], str) or
            not _DATA_VERSION.fullmatch(value['data_ver']) or
            not isinstance(value['exe_version'], str) or
            not _DATA_VERSION.fullmatch(value['exe_version']) or
            not isinstance(value['packages'], dict) or
            set(value['packages']) != set(PACKAGES) or
            type(value['assets_ready']) is not bool or value['assets_ready'] is not False or
            not isinstance(value['checked_at_utc'], str) or
            len(value['checked_at_utc']) > 40):
        raise OfficialSyncError('本機官方版本快取格式錯誤')
    for package in PACKAGES:
        revision = value['packages'][package]
        if not isinstance(revision, str) or not _PACKAGE_VERSION.fullmatch(revision):
            raise OfficialSyncError('本機官方 Package 版本快取無效：' + package)
    return value


def observe_official_versions(*, fetcher=None, checked_at=None):
    """Exactly three bounded official GETs, reusing the audited URL validator.

    A successful observation is NOT an installation or a compatibility test.
    Inject a fake fetcher for offline tests; no implicit cache fallback exists.
    """
    from wlre.services import official_version
    fetcher = official_version.fetch_bytes if fetcher is None else fetcher
    try:
        mapping = official_version.parse_resource_path(
            fetcher(official_version.RESOURCE_MAP_URL),
            exe_version=official_version.SUPPORTED_OFFICIAL_EXE_VERSION)
        urls = official_version.official_package_urls(mapping['data_version'])
        revisions = {}
        for package in PACKAGES:
            revisions[package] = official_version.parse_version(fetcher(urls[package]))
            if not _PACKAGE_VERSION.fullmatch(revisions[package]):
                raise OfficialSyncError('官方 Package 版本不是完整 Manifest 識別碼：' + package)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise OfficialSyncError('無法確認官方資源版本，未更新本機快取') from exc
    value = {
        'schema_version': SCHEMA,
        'origin': 'official_pc_version_endpoint',
        'data_ver': mapping['data_version'],
        'exe_version': mapping['selected_exe_version'],
        'packages': revisions,
        'checked_at_utc': checked_at or datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'assets_ready': False,
    }
    return validate_snapshot(value)


def read_snapshot(path=None):
    path = Path(path) if path is not None else snapshot_path()
    if not path.is_file():
        return None
    try:
        with path.open('rb') as stream:
            content = stream.read(MAX_SNAPSHOT_BYTES + 1)
        if len(content) > MAX_SNAPSHOT_BYTES:
            raise OfficialSyncError('本機版本快取超過上限')
        return validate_snapshot(json.loads(content.decode('utf-8')))
    except (OSError, ValueError, UnicodeError) as exc:
        raise OfficialSyncError('本機版本快取損毀，需人工確認或重新初始化') from exc


def compare_snapshot(current, previous=None):
    validate_snapshot(current)
    if previous is not None:
        validate_snapshot(previous)
    return {
        'data_ver_changed': None if previous is None else current['data_ver'] != previous['data_ver'],
        'exe_version_changed': None if previous is None else current['exe_version'] != previous['exe_version'],
        'package_changes': {
            name: ('first_observation' if previous is None else
                   'unchanged' if current['packages'][name] == previous['packages'][name]
                   else 'changed') for name in PACKAGES
        },
        'resource_installation': 'not_implemented',
        'can_start_asset_dependent_features': False,
        'note': '目前僅比較版本；遠端 Manifest URL 已核實，仍需另外驗證、解析並下載所需資源',
    }


def save_snapshot(value, path=None):
    """Atomically persist *only* version metadata to user application data."""
    validate_snapshot(value)
    target = Path(path) if path is not None else snapshot_path()
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise OfficialSyncError('官方版本快取超過儲存上限')
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.official_sync_',
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
