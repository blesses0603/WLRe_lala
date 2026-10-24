"""No-network diagnosis of LaLa 1275 runtime's missing or damaged sources.

Run from project root: py -m tools.diagnose_lala_resources
For machine-readable details: py -m tools.diagnose_lala_resources --json
"""
from __future__ import annotations

import argparse
import json
from wlre.services.world.resource_gap_diagnostics import (
    ARCHIVES, REQUIRED_GROUPS, diagnose_resources, summarize,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true',
                        help='Output machine-readable read-only inventory')
    args = parser.parse_args(argv)
    report = diagnose_resources()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print('LaLa 1275 正式資源自動診斷：' + summarize(report))
    for name in ARCHIVES:
        row = report['formal_sources'][name]
        print('  ' + name + '：' +
              {'missing':'缺少整包', 'verified':'固定 SHA／Schema 校驗通過',
               'invalid':'損壞／缺項／內容不相符'}[row['state']])
        if row['state'] == 'missing':
            print('    此包應包含：' + '、'.join(REQUIRED_GROUPS[name]))
        for member in row['missing']:
            print('    缺少 ZIP 內資料：' + member)
        for member in row['invalid']:
            print('    無法校驗：' + member)
    print('資料格式檢查不等於伺服器協定驗收；此診斷不會解除登入限制。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
