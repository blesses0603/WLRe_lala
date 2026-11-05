"""Inspect official parser diagnostics without logging in or sending packets."""
import argparse
import json
from pathlib import Path

from wlre.services.parser_diagnostics import MAX_REPORT_BYTES
from wlre.storage.paths import data_root


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sync', action='store_true', help='依既有配額同步官方資源並重新檢查')
    parser.add_argument('--root', type=Path, help='官方資源快取根目錄')
    args = parser.parse_args(argv)
    root = args.root if args.root is not None else data_root() / 'official_sync'
    if args.sync:
        from wlre.services.world.dynamic_bundle_runtime import prepare_dynamic_runtime
        try:
            prepare_dynamic_runtime(sync=True, sync_root=root)
        except (OSError, ValueError, RuntimeError):
            pass  # Print sanitized parser events, never raw remote exceptions.
    target = root / 'parser_diagnostics' / 'latest.json'
    try:
        with target.open('rb') as stream:
            raw = stream.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError('oversized report')
        report = json.loads(raw)
        if (type(report) is not dict or report.get('schema_version') != 1
                or type(report.get('parsers')) is not list
                or len(report['parsers']) > 128
                or type(report.get('coverage')) is not dict):
            raise ValueError('invalid report')
    except (OSError, ValueError):
        print('尚無可讀的解析器診斷報告；可執行 --sync 重新檢查。')
        return 2
    # Only show code-owned parser IDs and numeric location metadata generated
    # by this process. The JSON file is never used to decide compatibility.
    print('解析器診斷報告：' + str(target))
    failures = [row for row in report.get('parsers', [])
                if type(row) is dict and row.get('status') == 'failed']
    for row in failures:
        name = row.get('parser', '')
        if type(name) is not str or len(name) > 200 or not all(c.isascii() and (c.isalnum() or c in '._') for c in name):
            continue
        location = row.get('location', {})
        if type(location) is not dict:
            location = {}
        numeric = {k: v for k, v in location.items()
                   if k in ('offset', 'record', 'expected', 'actual', 'expected_max',
                            'requested_bytes', 'available_bytes') and type(v) is int}
        print(name + '：解析失敗 ' + json.dumps(numeric, ensure_ascii=False))
    coverage = report['coverage']
    passed = sum(value == 'passed' for value in coverage.values())
    failed = sum(value == 'failed' for value in coverage.values())
    missing = sum(value == 'not_available' for value in coverage.values())
    print(f'資料類別：{passed} 類通過解析、{failed} 類失敗、{missing} 類尚未取得。')
    print('此報告僅供診斷；登入及 Runtime 仍須通過原有驗證。')
    if failures or failed:
        return 1
    return 0 if passed == 16 and not missing else 2


if __name__ == '__main__':
    raise SystemExit(main())
