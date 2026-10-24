"""Inspect/promote reviewed, complete 1275 archives after Launcher verification.

Usage:
  py -m tools.reviewed_1275_handoff           # check only
  py -m tools.reviewed_1275_handoff --install # explicitly install

The required full 1275_DataCatalog.zip and 1275_EveNpcIndex.zip must be placed
in the private official_sync/reviewed_full_1275 directory. A pair of
DataPackage_1275.zip / MainPackage_1275.zip Manifest-only files does NOT work.
"""
import argparse
import json
import sys

from wlre.services.world.launcher_catalog import read_launcher_status
from wlre.services.world.formal_candidate_bridge import promote_reviewed_archives


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--install', action='store_true',
                   help='Publish both reviewed ZIPs only if ALL checks pass')
    args = p.parse_args(argv)
    receipt = read_launcher_status()
    if (receipt is None or receipt.get('status') != 'review_required'
            or receipt.get('data_compatibility') != 'compatible'
            or not receipt.get('catalog_key')):
        print('拒絕：Launcher 尚未建立四類資料格式相容的版本化候選。', file=sys.stderr)
        return 2
    try:
        result = promote_reviewed_archives(
            receipt['catalog_key'], check_only=not args.install)
    except (ValueError, OSError, KeyError) as exc:
        print('正式資源銜接安全拒絕：' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['status'] == 'awaiting_complete_reviewed_archives':
        print('仍缺完整且固定雜湊的 1275 正式雙 ZIP；不是 Manifest-only .bytes/.hash ZIP。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
