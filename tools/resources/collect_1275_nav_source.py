"""Collect the installed 1275 Unity navigation backing resources, read-only.

These two files are Unity global resources only; the origin of the old
offline A* graph has NOT been proven. A byte-identical match is insufficient
to establish 1275 walkable graphs, scene obstacles or trigger compatibility.
For cross-version comparison, use audit_1275_nav_sources.py.
Never copy files into the game folder or public GitHub.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED

EXPECTED_MANIFESTS = {
    'DataPackage': 'DataPackage_1275_2026_10_21_18_27_33_84.bytes',
    'MainPackage': 'MainPackage_1275_2026_10_21_18_29_38_49.bytes',
}
NAV_SOURCES = ('resources.assets', 'resources.resource')


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def collect(yoo_root, output, *, check_only=False):
    root = Path(yoo_root).resolve(strict=True)
    if root.name.casefold() != 'yoo':
        raise ValueError('請提供官方 _Data/yoo 目錄')
    game_data = root.parent
    pinned = {}
    for package, manifest in EXPECTED_MANIFESTS.items():
        path = root / package / 'ManifestFiles' / manifest
        if not path.is_file():
            raise FileNotFoundError('官方1275 Manifest不存在：' + str(path))
        pinned[package] = {'manifest': manifest, 'sha256': digest(path)}
    resources = {}
    for name in NAV_SOURCES:
        path = game_data / name
        if not path.is_file():
            raise FileNotFoundError('缺少1275原始導航來源：' + str(path))
        resources[name] = {'size': path.stat().st_size, 'sha256': digest(path)}
    report = {
        'revision':1275, 'purpose':'navigation_source_evidence',
        'unity_files': resources, 'yoo_manifests': pinned,
        'live_navigation_verified': False,
        'astar_graph_extracted': False,
        'navigation_source_proven': False,
        'warning': ('resources.assets 與 resources.resource 僅供來源比對，'
                    '不能證明1262 A*網格可在1275重用'),
    }
    if check_only:
        return report
    destination = Path(output).resolve()
    if destination == game_data or game_data in destination.parents:
        raise ValueError('禁止把輸出 ZIP 寫到官方遊戲目錄')
    if destination.suffix.lower() != '.zip':
        raise ValueError('輸出必須為 .zip')
    if destination.exists():
        raise FileExistsError('已有輸出檔案，不覆寫：' + str(destination))
    created = False
    try:
        with ZipFile(destination, mode='x', compression=ZIP_STORED, allowZip64=True) as z:
            created = True
            z.writestr('source_fingerprints.json',
                       json.dumps(report, ensure_ascii=False, indent=2))
            for name in NAV_SOURCES:
                z.write(game_data / name, 'source/' + name)
        with ZipFile(destination) as z:
            if z.testzip() is not None:
                raise ValueError('導航來源 ZIP CRC 不符')
            for name, record in resources.items():
                member = 'source/' + name
                if z.getinfo(member).file_size != record['size']:
                    raise ValueError('導航來源 ZIP 大小不符：' + name)
                h = hashlib.sha256()
                with z.open(member) as stream:
                    for chunk in iter(lambda: stream.read(1024*1024), b''):
                        h.update(chunk)
                if h.hexdigest() != record['sha256']:
                    raise ValueError('導航來源 ZIP SHA-256 不符：' + name)
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return dict(report, archive=str(destination))


def main(argv=None):
    parser = argparse.ArgumentParser(description='提取1275導航原始Unity資源，唯讀驗證')
    parser.add_argument('yoo_root', type=Path)
    parser.add_argument('--output', type=Path,
                        default=Path('LaLa_1275_導航原始來源.zip'))
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(collect(args.yoo_root,args.output,
                             check_only=args.check_only),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
