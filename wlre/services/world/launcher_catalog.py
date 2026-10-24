"""Launcher-owned official resource preparation, never the login view.

Both the source-code bootstrapper and the compiled desktop entry point call
this service BEFORE starting Tk. Candidate catalogs are read-only and cannot
approve game versions, login, navigation or network packet sending.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from wlre.storage.paths import data_root

STATUS_SCHEMA = 1
STATUS_FILENAME = 'launcher_catalog_status.json'
MAX_STATUS_BYTES = 4096
STATES = frozenset(('review_required', 'downloaded_unparsed',
                   'preview', 'error'))


def status_path(root=None):
    base = Path(root) if root is not None else data_root() / 'official_sync'
    return base / STATUS_FILENAME


def read_launcher_status(*, root=None):
    """Untrusted display-only status. Never authorizes runtime assets."""
    path = status_path(root)
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_STATUS_BYTES + 1)
        if not 0 < len(raw) <= MAX_STATUS_BYTES:
            return None
        report = json.loads(raw.decode('utf-8'))
        if (type(report) is not dict
                or set(report) != {'schema_version', 'status', 'checked_at_utc',
                                   'catalog_key', 'assets_ready', 'can_send_packets'}
                or report['schema_version'] != STATUS_SCHEMA
                or report['status'] not in STATES
                or report['assets_ready'] is not False
                or report['can_send_packets'] is not False
                or type(report['checked_at_utc']) is not str
                or len(report['checked_at_utc']) > 40):
            return None
        key = report['catalog_key']
        if key is not None and (type(key) is not str or len(key) != 64 or
                                any(c not in '0123456789abcdef' for c in key)):
            return None
        return report
    except (OSError, UnicodeError, ValueError, TypeError):
        return None


def _store_status(report, *, root=None):
    target = status_path(root)
    payload = (json.dumps(report, ensure_ascii=True, sort_keys=True,
                          separators=(',', ':')) + '\n').encode('utf-8')
    if len(payload) > MAX_STATUS_BYTES:
        raise ValueError('Launcher report too large')
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.launcher_',
                                         suffix='.partial', delete=False) as fd:
            pending = Path(fd.name)
            fd.write(payload)
            fd.flush()
            os.fsync(fd.fileno())
        os.replace(pending, target)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def prepare_on_launch(*, runner=None, root=None, environ=None, progress=None):
    """Synchronously prepare a candidate before Tk starts.

    Failure is reported without blocking LaLa's own official login check.
    Callers must not treat any return value or the private receipt as approval.
    All downloads occur inside run_auto_catalog's verified, bounded pipeline.
    """
    if progress is not None and not callable(progress):
        raise ValueError('Invalid launcher progress callback')
    env = os.environ if environ is None else environ
    if env.get('WLRE_DISABLE_AUTO_CATALOG') == '1':
        return {'status': 'skipped', 'assets_ready': False,
                'can_send_packets': False}
    if runner is None:
        from wlre.services.world.auto_catalog import run_auto_catalog
        runner = run_auto_catalog
    key = None
    try:
        kwargs = {'download': True, 'parse': True}
        if progress is not None:
            kwargs['progress'] = progress
        result = runner(**kwargs)
        if result['status'] != 'review_required':
            raise ValueError('Launcher auto catalog did not produce a reviewed-schema candidate')
        key = result['catalog_key']
        if type(key) is not str or len(key) != 64 or any(
                c not in '0123456789abcdef' for c in key):
            raise ValueError('Invalid launcher catalog identity')
        status = 'review_required'
    except Exception:
        # Keep reason out of local receipts; failures can include file paths,
        # remote exceptions, or implementation details.
        status = 'error'
    receipt = {
        'schema_version': STATUS_SCHEMA,
        'status': status,
        'checked_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'catalog_key': key,
        'assets_ready': False,
        'can_send_packets': False,
    }
    try:
        _store_status(receipt, root=root)
    except OSError:
        # No readable status must never be confused with an approved Catalog.
        pass
    return receipt


def main():
    result = prepare_on_launch()
    status = result['status']
    print('LaLa Launcher 官方資源候選：' +
          ('已建立，尚待相容性審核' if status == 'review_required'
           else '未完成；仍維持原有登入安全檢查' if status == 'error'
           else '已略過'), flush=True)
    # Failure to build a *candidate* must not suppress the real login gate.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
