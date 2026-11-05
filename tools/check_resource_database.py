"""Read normalized import/recovery status; never download, activate or repair."""
import argparse
import json
from pathlib import Path
import sqlite3

from wlre.storage.paths import data_root
from wlre.storage.normalized_resources import inspect_database


def main(argv=None):
    parser = argparse.ArgumentParser(description='官方規範資料庫來源與修復狀態（唯讀）')
    parser.add_argument('--database', type=Path, default=data_root() / 'official_sync' /
                        'derived_catalogs' / 'resource_inventory.sqlite3')
    args = parser.parse_args(argv)
    try:
        report = inspect_database(args.database)
    except (OSError, ValueError, sqlite3.Error):
        print(json.dumps({'status': 'database_unreadable', 'can_send_packets': False}))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(any(row['status'] != 'verified_checksum' for row in report['snapshots']))


if __name__ == '__main__':
    raise SystemExit(main())
