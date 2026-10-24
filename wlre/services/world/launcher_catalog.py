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

STATUS_SCHEMA = 2
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
        legacy = {'schema_version', 'status', 'checked_at_utc',
                  'catalog_key', 'assets_ready', 'can_send_packets'}
        current = legacy | {'data_compatibility', 'protocol_compatibility'}
        if (type(report) is not dict
                or ((report.get('schema_version') == 1 and set(report) != legacy)
                    or (report.get('schema_version') == STATUS_SCHEMA
                        and set(report) != current)
                    or report.get('schema_version') not in (1, STATUS_SCHEMA))
                or (report['schema_version'] == STATUS_SCHEMA and
                    (report['data_compatibility'] not in ('compatible', 'unverified')
                     or report['protocol_compatibility'] != 'unverified'))
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
    real_launcher_run = runner is None and root is None
    if runner is None:
        from wlre.services.world.auto_catalog import run_auto_catalog
        runner = run_auto_catalog
    key = None
    data_compatibility = 'unverified'
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
        # A source can pass its schemas without its network protocol being
        # approved. Only advertise the data verdict when the Catalog pipeline
        # explicitly returned both independent statuses.
        if (result.get('data_compatibility') == 'compatible' and
                result.get('protocol_compatibility') == 'unverified' and
                result.get('assets_ready') is False and
                result.get('can_send_packets') is False and
                result.get('approved') is False):
            data_compatibility = 'compatible'
        # Automatic promotion is only eligible in a real Launcher run after
        # four independently validated sources and the full pinned archives
        # are available. Injected test runners/roots never touch live files.
        if (real_launcher_run and data_compatibility == 'compatible'):
            from wlre.services.world.formal_candidate_bridge import (
                promote_reviewed_archives)
            if progress is not None:
                progress('formal_check', {})
            bridge = promote_reviewed_archives(key)
            if progress is not None:
                progress('formal_checked', {'status': bridge['status']})
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
        'data_compatibility': data_compatibility,
        'protocol_compatibility': 'unverified',
        'assets_ready': False,
        'can_send_packets': False,
    }
    try:
        _store_status(receipt, root=root)
    except OSError:
        # No readable status must never be confused with an approved Catalog.
        pass
    # Every real Launcher iteration also records what the full formal runtime
    # still lacks. Tests with an injected root diagnose only that temporary
    # private directory. Neither report is an authorization token.
    try:
        from wlre.services.world.resource_gap_diagnostics import (
            diagnose_resources, save_report)
        gaps = diagnose_resources(base=root, checked_at_utc=receipt['checked_at_utc'])
        save_report(gaps, base=root)
    except Exception:
        # Optional gap diagnosis must not prevent LaLa from starting.
        # This report is informational, not login authorization.
        pass
    return receipt


def main(argv=None):
    import sys
    args = sys.argv[1:] if argv is None else list(argv)
    if args not in ([], ['--progress']):
        print('用法：python -m wlre.services.world.launcher_catalog [--progress]',
              file=sys.stderr)
        return 2
    if args == ['--progress']:
        from wlre.launcher_progress import run_with_progress
        result = run_with_progress(prepare_on_launch)
    else:
        result = prepare_on_launch()
    status = result['status']
    print('LaLa Launcher 官方資源候選：' +
          ('資料格式檢查通過，協定仍待審核'
           if status == 'review_required' and
           result.get('data_compatibility') == 'compatible'
           else '已建立，尚待相容性審核' if status == 'review_required'
           else '未完成；仍維持原有登入安全檢查' if status == 'error'
           else '已略過'), flush=True)
    # Failure to build a *candidate* must not suppress the real login gate.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
