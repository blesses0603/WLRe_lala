"""Observe the official PC Lua path/MD5 list without downloading scripts."""

import argparse
import json
import sys

from wlre.services import official_version
from wlre.services.official_lua_index import (
    LuaIndexError, compare_lists, fetch_list, load_cache, save_cache,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description='LaLa 官方 Lua 清單唯讀差異檢查')
    parser.add_argument('--save', action='store_true',
                        help='在本機寫入路徑與 MD5 快取，不下載 Lua 原始檔')
    args = parser.parse_args(argv)
    try:
        path = official_version.parse_resource_path(
            official_version.fetch_bytes(official_version.RESOURCE_MAP_URL),
            exe_version=official_version.SUPPORTED_OFFICIAL_EXE_VERSION)
        data_ver = path['data_version']
        previous = load_cache(data_ver)
        current = fetch_list(data_ver)
        changes = compare_lists(current, previous)
        if args.save:
            save_cache(data_ver, current)
    except (LuaIndexError, OSError, ValueError) as exc:
        print('官方 Lua 清單查詢失敗：' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({'data_ver': data_ver, 'lua_count': len(current),
                      'difference': changes, 'saved': bool(args.save),
                      'scripts_downloaded': 0, 'scripts_executed': 0},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
