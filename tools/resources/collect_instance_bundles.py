"""Collect four YooAsset DataPackage bundles identified by the 1262 manifest.

No game assets are modified; each file is copied into a ZIP with SHA-256.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

BUNDLES = {
    'datapackage_data_c.bundle': ('e600b2b2ef3044fc5e5a7ff3641d1df8', 4732,
                                  ['CooperateEventData_C']),
    'datapackage_data_d.bundle': ('014e88153786c77eaed00d04ec29f8a3', 39020,
                                  ['DungeonData_C', 'DungeonRewardData_C']),
    'datapackage_data_s.bundle': ('b470fcf69d58da6ac1a7c899068b2bf4', 428919,
                                  ['ScenesData_C', 'StageMapData_C']),
    'datapackage_data_t.bundle': ('277be57613f8b1306fc645c63835b2ee', 3619162,
                                  ['TextData_C', 'TextData_SC_C']),
}
DEFAULT_YOO = r'D:\Program Files\D\wlre\飄流幻境Re_星之方舟_Data\yoo'


def collect(yoo_root, output):
    data_dir = Path(yoo_root).expanduser() / 'DataPackage' / 'BundleFiles'
    if not data_dir.is_dir():
        raise FileNotFoundError('找不到 DataPackage/BundleFiles：%s' % data_dir)
    files = {}
    missing = []
    for name, (digest, expected_size, assets) in BUNDLES.items():
        source = data_dir / digest[:2] / digest / '__data'
        if not source.is_file():
            missing.append(str(source))
            continue
        contents = source.read_bytes()
        if len(contents) != expected_size:
            raise ValueError(
                '%s 大小不符（預期 %d / 實際 %d bytes），請核對 1262 版本' %
                (name, expected_size, len(contents)))
        files[name] = {'content': contents, 'digest': digest, 'assets': assets}
    if missing:
        raise FileNotFoundError('缺少官方 BundleFiles:\n' + '\n'.join(missing))
    inventory = {
        'manifest': 'DataPackage_1262_2026_10_14_15_00_34_84',
        'files': [
            {'name': name, 'manifest_hash': item['digest'], 'assets': item['assets'],
             'size': len(item['content']),
             'sha256': hashlib.sha256(item['content']).hexdigest()}
            for name, item in files.items()
        ],
    }
    out = Path(output).expanduser()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, item in files.items():
            archive.writestr(name, item['content'])
        archive.writestr(
            'manifest_inventory.json',
            json.dumps(inventory, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(out) as archive:
        if archive.testzip() is not None:
            raise IOError('ZIP CRC 驗證失敗')
    return out


def main():
    parser = argparse.ArgumentParser(description='從安裝目錄收集 1262 副本 Bundle')
    parser.add_argument('--yoo-root', default=DEFAULT_YOO)
    parser.add_argument('--output', default='WLRE_1262_Instance_Bundles.zip')
    args = parser.parse_args()
    try:
        output = collect(args.yoo_root, args.output)
    except (OSError, ValueError) as exc:
        print('收集失敗：%s' % exc, file=sys.stderr)
        return 1
    print('完成：%s' % output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
