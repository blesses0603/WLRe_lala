"""LaLa B-only phase-1 bootstrap: inspect official versions without game files."""

import argparse
import json
import sys

from wlre.services.official_resource_sync import (
    OfficialSyncError, compare_snapshot, observe_official_versions,
    read_snapshot, save_snapshot,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description='LaLa 官方直連同步初始化（版本資訊階段）')
    parser.add_argument('--save', action='store_true',
                        help='確認後只寫入版本快照；不下載任何遊戲檔案')
    args = parser.parse_args(argv)
    try:
        before = read_snapshot()
        current = observe_official_versions()
        delta = compare_snapshot(current, before)
        if args.save:
            save_snapshot(current)
    except OfficialSyncError as exc:
        print('官方同步初始化失敗：' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({'official': current, 'difference': delta,
                      'saved': bool(args.save)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
