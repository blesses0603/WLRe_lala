"""離線將既有 DataPackage/MainPackage Manifest 分類成私人 JSON 索引。

範例：
py -m tools.classify_existing_resources --data DataPackage_1275.zip ^
  --main MainPackage_1275.zip --output-dir %LOCALAPPDATA%\LaLa-Indexes

只讀 Manifest，不下載 Bundle、不碰登入或封包。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from tools.resources.lala_manifest_full_index import (
    load_index, validate_private_output,
)
from wlre.services.world.resource_classification import (
    build_classification, MAX_OUTPUT_BYTES,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description='LaLa 既有官方資料索引分類')
    parser.add_argument('--data', type=Path, required=True,
                        help='DataPackage Manifest ZIP 或 RAR')
    parser.add_argument('--main', type=Path, required=True,
                        help='MainPackage Manifest ZIP 或 RAR')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='Git 工作樹以外的私人資料夾')
    args = parser.parse_args(argv)
    indexes = {
        'DataPackage': load_index(args.data, 'DataPackage'),
        'MainPackage': load_index(args.main, 'MainPackage'),
    }
    versions = {p: index['header']['package_version'].split('_')[0]
                for p, index in indexes.items()}
    if len(set(versions.values())) != 1:
        raise ValueError('DataPackage／MainPackage 的資源版號不同，不得混合')
    # Offline CLI key is a deterministic local index identifier, NOT the
    # Launcher OfficialCatalogIdentity and never used to authorize gameplay.
    identity = '|'.join(
        p + ':' + indexes[p]['header']['package_version']
        + ':' + indexes[p]['source']['manifest_sha256']
        for p in ('DataPackage', 'MainPackage'))
    catalog_key = hashlib.sha256(identity.encode('utf-8')).hexdigest()
    report = build_classification(indexes, catalog_key)
    report['index_kind'] = 'offline_manifest_only'
    body = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
            + '\n').encode('utf-8')
    if len(body) > MAX_OUTPUT_BYTES:
        raise ValueError('索引檔超過安全上限')
    target = validate_private_output(args.output_dir)
    target.mkdir(parents=True, exist_ok=True)
    output = target / ('LaLa_' + versions['DataPackage'] + '_manifest_classification.json')
    output.write_bytes(body)
    for package in ('DataPackage', 'MainPackage'):
        print(package, report['packages'][package]['asset_total'],
              'Assets,', report['packages'][package]['bundle_total'], 'Bundles')
    print('分類索引：', output)
    print('備註：Manifest 目錄索引，不代表 Bundle 已下載或資料已經解包。')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print('[ERROR]', exc, file=sys.stderr)
        raise SystemExit(2)
