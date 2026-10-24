"""Package the pinned official startup snapshots for private installation."""
import argparse
import json
from pathlib import Path
from wlre.services.world.official_navigation import package, install


def main():
    parser = argparse.ArgumentParser(description='封裝官方快取；只接受固定 SHA 原始快取，不接受重建候選')
    parser.add_argument('--source-dir', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--install', action='store_true', help='校驗後安裝到目前使用者資料目錄，不覆寫')
    args = parser.parse_args()
    output = package(args.source_dir, args.output)
    print(json.dumps(install(output) if args.install else {'archive': str(output), 'can_send_packets': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
