"""只讀官方 AssetPath 分類索引；檔名分類不代表已解包或遊戲協定相容。"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from zipfile import BadZipFile, ZipFile

from wlre.storage.paths import data_root

MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_INVENTORY_BYTES = 128 * 1024 * 1024
OUTPUT = 'asset_classification.json'
LABELS = {
    'npc': 'NPC／夥伴', 'items': '物品／裝備', 'shops': '商店／交易',
    'crafting': '製作／配方', 'maps': '地圖／傳送', 'quests': '任務／活動',
    'battle': '戰鬥／技能', 'talk': '對話／文字', 'characters': '角色／能力',
    'expedition': '遠征／駐紮所',
    'other_data': '其他資料', 'audio': '音效／音樂', 'sprites': '圖示／圖片',
    'scenes': '場景資源', 'npc_models': 'NPC 模型', 'role_models': '角色模型',
    'housing': '房屋／帳篷', 'weapon_models': '武器模型',
    'models': '其他模型／動畫', 'materials': '材質／Shader',
    'fonts': '字型', 'effects': '粒子／特效', 'timelines': '動畫時間軸',
    'video': '影片', 'spine': '2D 骨骼動畫', 'other': '尚未分類',
}


class ResourceClassificationError(ValueError):
    pass


def classify_asset_path(package, path):
    """Return (category, basis). Classification is intentionally heuristic."""
    if (package not in ('DataPackage', 'MainPackage')
            or type(path) is not str
            or not path.startswith('Assets/ResourcesBuild/')
            or len(path) > 1024 or '\\' in path or '\x00' in path
            or any(part in ('', '.', '..') for part in path.split('/'))):
        raise ResourceClassificationError('無效官方 AssetPath')
    if package == 'DataPackage':
        if not path.startswith('Assets/ResourcesBuild/Data/') or not path.endswith('.bytes'):
            raise ResourceClassificationError('無效 DataPackage 資料表')
        name = PurePosixPath(path).stem.lower()
        groups = (
            ('talk', ('talk', 'text', 'language', 'word', 'dirtyword')),
            ('expedition', ('adventure', 'expedition', 'outpost')),
            ('quests', ('task', 'quest', 'mission', 'adventure', 'journal', 'dungeon')),
            ('shops', ('shop', 'store', 'mall', 'sale', 'sell', 'currency', 'trade')),
            ('crafting', ('smith', 'recipe', 'alchemy', 'creation', 'compose', 'cook')),
            ('maps', ('scene', 'map', 'door', 'teleport', 'convey', 'traffic')),
            ('npc', ('npc', 'eve', 'pet', 'partner')),
            ('items', ('item', 'equip', 'weapon', 'tool', 'prop')),
            ('battle', ('battle', 'fight', 'skill', 'monster', 'boss')),
            ('characters', ('role', 'character', 'exp', 'ability', 'attribute')),
            ('quests', ('event', 'reward', 'benefit', 'award', 'activity')),
        )
        for category, words in groups:
            if any(word in name for word in words):
                return category, 'filename_rule'
        return 'other_data', 'unclassified_filename'
    parts = path.split('/')
    folder = parts[2].lower()
    section = parts[3].lower() if len(parts) > 3 else ''
    if folder == 'audio':
        return 'audio', 'directory_rule'
    if folder in ('sprite', 'texture', 'cg2d', 'ui'):
        return 'sprites', 'directory_rule'
    if folder == 'scenes':
        return 'scenes', 'directory_rule'
    if folder == 'model':
        if section == 'house':
            return 'housing', 'directory_rule'
        if section == 'role':
            return 'role_models', 'directory_rule'
        if section == 'others' and len(parts) > 4:
            if parts[4].lower() in ('npc', 'npc2d'):
                return 'npc_models', 'directory_rule'
            if parts[4].lower() == 'weapon':
                return 'weapon_models', 'directory_rule'
        return 'models', 'directory_rule'
    simple = {
        'particle': 'effects', 'timeline': 'timelines', 'video': 'video',
        'spine2d': 'spine', 'shader': 'materials', 'textmeshprosetting': 'materials',
    }
    if folder in simple:
        return simple[folder], 'directory_rule'
    if folder == 'other':
        return ('fonts' if section == 'font' else 'materials'), 'directory_rule'
    return 'other', 'unclassified_directory'


def _read_existing_inventory(path, catalog_key):
    """Verify every local entry SHA before exposing it as locally present.

    A self-consistent local ZIP is not an independent official approval.
    """
    if (not path.is_file() or path.is_symlink()
            or path.stat().st_size > MAX_INVENTORY_BYTES):
        return {}, []
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) > 270 or len(names) != len(set(names)) or 'inventory.json' not in names:
                return {}, []
            info = archive.getinfo('inventory.json')
            if not 0 < info.file_size <= 128 * 1024:
                return {}, []
            meta = json.loads(archive.read(info))
            if (type(meta) is not dict or meta.get('schema_version') != 1
                    or meta.get('catalog_key') != catalog_key
                    or type(meta.get('entries')) is not dict
                    or set(names) != set(meta['entries']) | {'inventory.json'}):
                return {}, []
            raw, extra, total = {}, [], 0
            for member, record in sorted(meta['entries'].items()):
                info = archive.getinfo(member)
                size = record.get('size') if type(record) is dict else None
                sha = record.get('sha256') if type(record) is dict else None
                if (info.is_dir() or type(size) is not int or not 0 < size <= 32 * 1024 * 1024
                        or type(sha) is not str or len(sha) != 64
                        or info.file_size != size):
                    return {}, []
                total += size
                if total > MAX_INVENTORY_BYTES:
                    return {}, []
                digest = hashlib.sha256()
                with archive.open(info) as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                if digest.hexdigest() != sha:
                    return {}, []
                detail = {'size': size, 'sha256': sha,
                          'status': 'local_checksum_checked_not_approved'}
                if member.startswith('tables/') and member.endswith('.bytes'):
                    raw[member] = detail
                elif member.startswith(('indexes/', 'candidate_indexes/', 'npc_')):
                    extra.append({'member': member, **detail})
            return raw, extra
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, BadZipFile):
        return {}, []


def build_classification(indexes, catalog_key, *, local_raw=None, local_indexes=None):
    if (type(catalog_key) is not str or len(catalog_key) != 64
            or any(c not in '0123456789abcdef' for c in catalog_key)
            or type(indexes) is not dict
            or set(indexes) != {'DataPackage', 'MainPackage'}):
        raise ResourceClassificationError('官方版本身分不合法')
    local_raw = {} if local_raw is None else local_raw
    local_indexes = [] if local_indexes is None else local_indexes
    assets, packages, counts = [], {}, Counter()
    for package in ('DataPackage', 'MainPackage'):
        index = indexes[package]
        head = index.get('header', {})
        bundles = index.get('bundles', ())
        paths = index.get('assets', ())
        if (head.get('file_version') != '2.2.5' or head.get('package_name') != package
                or type(head.get('package_version')) is not str
                or type(bundles) is not list or type(paths) is not list
                or len(paths) > 100000):
            raise ResourceClassificationError('官方 Manifest 格式不符')
        bundle_names = {row['name'] for row in bundles}
        if len(bundle_names) != len(bundles):
            raise ResourceClassificationError('重複 Bundle')
        seen = set()
        packages[package] = {
            'revision': head['package_version'],
            'asset_total': len(paths), 'bundle_total': len(bundles),
        }
        for asset in sorted(paths, key=lambda row: row['path']):
            path, bundle = asset['path'], asset['bundle_name']
            if path in seen or bundle not in bundle_names:
                raise ResourceClassificationError('重複 AssetPath 或未知 Bundle')
            seen.add(path)
            category, basis = classify_asset_path(package, path)
            row = {
                'package': package, 'revision': head['package_version'],
                'asset_path': path, 'bundle': bundle, 'category': category,
                'category_zh': LABELS[category], 'basis': basis,
                'status': 'manifest_only',
            }
            if package == 'DataPackage':
                local_name = f'tables/{bundle}/{PurePosixPath(path).name}'
                available = local_raw.get(local_name)
                if available:
                    row.update(status='local_checksum_checked_not_approved',
                               local_bytes=available['size'],
                               local_sha256=available['sha256'])
            counts[(package, category, row['status'])] += 1
            assets.append(row)
    return {
        'schema_version': 1, 'catalog_key': catalog_key,
        'classification_basis': 'path_and_filename_only',
        'approved': False, 'assets_ready': False, 'can_send_packets': False,
        'packages': packages,
        'summary': [
            {'package': package, 'category': category, 'category_zh': LABELS[category],
             'status': status, 'count': count}
            for (package, category, status), count in sorted(counts.items())
        ],
        'assets': assets, 'existing_indexes': local_indexes,
    }


def write_verified_classification(identity, manifests, *, candidate_root=None):
    """Write private version-isolated index after both official Manifests validate."""
    from wlre.services.official_manifest_sync import VerifiedManifest
    from wlre.services.world.catalog_identity import OfficialCatalogIdentity
    if (not isinstance(identity, OfficialCatalogIdentity)
            or type(manifests) is not dict
            or set(manifests) != {'DataPackage', 'MainPackage'}):
        raise ResourceClassificationError('缺少雙 Package 官方版本資訊')
    revisions = {item.name: item.full_version for item in identity.packages}
    for package, manifest in manifests.items():
        if (not isinstance(manifest, VerifiedManifest)
                or manifest.spec.package != package
                or manifest.spec.package_version != revisions.get(package)):
            raise ResourceClassificationError('Manifest 版本不一致')
    root = (Path(candidate_root) if candidate_root is not None
            else data_root() / 'official_sync' / 'derived_catalogs')
    directory = identity.private_catalog_dir(root)
    local_raw, local_indexes = _read_existing_inventory(
        directory / 'verified_raw_inventory.zip', identity.key)
    doc = build_classification(
        {name: manifest.index for name, manifest in manifests.items()},
        identity.key, local_raw=local_raw, local_indexes=local_indexes)
    raw = (json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')) + '\n').encode('utf-8')
    if len(raw) > MAX_OUTPUT_BYTES:
        raise ResourceClassificationError('資源分類索引超過安全上限')
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                dir=directory, prefix='.resource_class_', suffix='.partial',
                delete=False) as fd:
            temporary = Path(fd.name)
            fd.write(raw)
            fd.flush()
            os.fsync(fd.fileno())
        os.replace(temporary, directory / OUTPUT)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        'asset_total': len(doc['assets']),
        'locally_indexed': sum(row['status'] != 'manifest_only' for row in doc['assets']),
        'existing_index_files': len(local_indexes),
        'approved': False, 'assets_ready': False, 'can_send_packets': False,
    }
