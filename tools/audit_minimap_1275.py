"""Compare extracted official 1275 minimaps with LaLa's existing cache.

Use this for coverage diagnostics, not as a launcher import or packet permit.
An official 1275 runtime independently verifies ScenesData_C before using it.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile

from wlre.paths import RESOURCE_ROOT
from wlre.services.world.bundle_runtime_1275 import _PINNED_MANIFEST_SHA256


PREFIX = 'output_1275/'
FIELDS = {
    'model_id': 'model_id',
    'map_width': 'map_width',
    'map_height': 'map_height',
    'small_map_offset_x': 'small_offset_x',
    'small_map_offset_y': 'small_offset_y',
}


def _read_csv(archive, name):
    entry = PREFIX + name
    if archive.getinfo(entry).file_size > 4 * 1024 * 1024:
        raise ValueError('1275 對照資料過大：' + name)
    return list(csv.DictReader(io.StringIO(archive.read(entry).decode('utf-8-sig'))))


def audit(archive_path, *, pixel_audit=False,
          resources=RESOURCE_ROOT):
    """Return exact gaps; never mutates LaLa, game files or official ZIP."""
    import re
    from PIL import Image

    archive_path = Path(archive_path)
    resources = Path(resources)
    with ZipFile(archive_path) as official:
        manifest = json.loads(official.read(PREFIX + 'manifest_inventory.json'))
        actual = {x['name']: x['manifest_sha256']
                  for x in manifest['packages']}
        if manifest.get('version') != '1275' or actual != _PINNED_MANIFEST_SHA256:
            raise ValueError('這不是 LaLa 固定的 1275 MainPackage／DataPackage 對照資料')
        official_scenes = {}
        for row in _read_csv(official, 'scenes_1275.csv'):
            sid = int(row['scene_id'])
            if not 0 < sid <= 65535 or sid in official_scenes:
                raise ValueError('1275 官方場景 ID 有重複或異常')
            official_scenes[sid] = row
        assets = set()
        for row in manifest['map_image_assets']:
            name = row['address']
            if re.fullmatch(r'SmallMap2D_[0-9]+', name):
                assets.add(name)
        if not assets:
            raise ValueError('1275 Manifest 未列出 SmallMap2D')
        with ZipFile(resources / 'smallmaps.zip') as installed:
            existing = json.loads(installed.read('image_index.json'))
            existing_by_name = {r['name']: r['entry'] for r in existing}
            if len(existing_by_name) != len(existing):
                raise ValueError('LaLa 小地圖圖片索引重複')
            legacy = json.loads((resources / 'stage_coordinates.json').read_text(
                encoding='utf-8'))['stages']
            old_scenes = {int(key): value for key, value in legacy.items()}
            only_official = sorted(set(official_scenes) - set(old_scenes))
            only_old = sorted(set(old_scenes) - set(official_scenes))
            changes = []
            for sid in sorted(set(official_scenes) & set(old_scenes)):
                row, old = official_scenes[sid], old_scenes[sid]
                differences = {new_key: {'old': old[old_key],
                                          'official_1275': int(row[new_key])}
                               for new_key, old_key in FIELDS.items()
                               if old[old_key] != int(row[new_key])}
                if differences:
                    model = int(row['model_id'])
                    changes.append({'scene_id': sid, 'scene_name': row['scene_name'],
                                    'has_official_smallmap': f'SmallMap2D_{model}' in assets,
                                    'differences': differences})
            new_scenes = [
                {'scene_id': sid,
                 'name': official_scenes[sid]['scene_name'],
                 'model_id': int(official_scenes[sid]['model_id']),
                 'has_image': ('SmallMap2D_' + official_scenes[sid]['model_id']) in assets}
                for sid in only_official]
            missing_images = sorted(assets - set(existing_by_name))
            obsolete_images = sorted(set(existing_by_name) - assets)
            image_changes = []
            unknown_export = []
            if pixel_audit:
                # Compare rendered RGBA, not the different PNG/WebP encodings.
                for name in sorted(assets & set(existing_by_name)):
                    official_name = PREFIX + 'images/' + name + '.png'
                    if official_name not in official.namelist():
                        unknown_export.append(name)
                        continue
                    with Image.open(io.BytesIO(official.read(official_name))) as a, \
                            Image.open(io.BytesIO(installed.read(existing_by_name[name]))) as b:
                        if a.size != b.size or a.convert('RGBA').tobytes() != b.convert('RGBA').tobytes():
                            image_changes.append(name)
            return {
                'version': '1275',
                'official_scene_count': len(official_scenes),
                'legacy_scene_count': len(old_scenes),
                'official_only_scenes': new_scenes,
                'legacy_only_scene_count': len(only_old),
                'changed_scene_geometry': changes,
                'official_smallmap_count': len(assets),
                'legacy_smallmap_count': len(existing_by_name),
                'missing_image_models': missing_images,
                'obsolete_image_models': obsolete_images,
                'pixel_audit_performed': pixel_audit,
                'changed_image_pixels': image_changes if pixel_audit else None,
                'not_exported_for_pixel_check': unknown_export if pixel_audit else None,
                'notes': ('只有原始官方 1275 資料的 Scene/Model/尺寸可供新版 Runtime 使用；'
                          '缺圖場景不能引用其他圖片代替。')
            }


def main(argv=None):
    parser = argparse.ArgumentParser(description='比對 LaLa 與官方 1275 小地圖缺口（唯讀）')
    parser.add_argument('archive', help='官方提取器產生的 output_1275.zip')
    parser.add_argument('--pixel-audit', action='store_true',
                        help='逐張解碼比較 550 張 PNG/WebP RGBA 像素，約需十幾秒')
    args = parser.parse_args(argv)
    report = audit(args.archive, pixel_audit=args.pixel_audit)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
