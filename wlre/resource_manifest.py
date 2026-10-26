"""Shared required assets and package-data rules for runtime and native builds."""
import gzip
import json
from pathlib import Path
import zipfile

DATA_SUFFIXES={'.json','.zip','.gz','.png','.ico'}
REQUIRED_RESOURCES=(
    'alchemy_catalog.json','combat_catalog.json','crafting_catalog.json','default_profile.json',
    'lala_supported_resources.json',
    'emoji_catalog.json','emoji_images.zip','enums.json','expedition_catalog.json','instance_catalog_1262.json','graph_origins.json',
    'item_icon_coverage.json','item_icon_map.json','item_icons.zip','item_stackable.json',
    'map_names.json','navigation_data.zip','normal_attack_data.json','npc_event_index_1262.json.gz','npc_battle_talk_1262.json.gz',
    'npc_talk_1262.json.gz','npc_text_1262.json.gz','npc_interact_1262.json.gz',
    'portals.json',
    'server_list.json','smallmaps.zip','stage_coordinates.json',
    'assets/app.ico','assets/exp_background.png',
    *('assets/buttons/'+name+'.png' for name in (
        'Btn_004','Btn_014','Btn_016','Btn_Bag','Btn_CategoryAISetting003','Btn_Close04','Btn_Setting')),
    *('assets/function-icons/'+name+'.png' for name in (
        'Btn_AI','MainIcon_001','MainIcon_005','MainIcon_007','MainIcon_010',
        'MainIcon_011','MainIcon_020','MainIcon_038','MainIcon_041')),
)


def require_resources(root):
    root=Path(root)
    missing=[name for name in REQUIRED_RESOURCES if not (root/name).is_file()]
    if missing:raise RuntimeError('Missing resources: '+', '.join(missing))


def data_files(package_root):
    package_root=Path(package_root)
    require_resources(package_root/'resources')
    return sorted(p for p in package_root.rglob('*')
                  if p.is_file() and p.suffix.lower() in DATA_SUFFIXES
                  and not any(part.startswith('.') or part=='__pycache__' for part in p.relative_to(package_root).parts))


def validate_resources(root):
    """Validate all shipped data, including nested button/function-icon images."""
    from PIL import Image
    root=Path(root);require_resources(root)
    for path in root.rglob('*'):
        if not path.is_file():continue
        if path.suffix=='.json':
            with path.open(encoding='utf8') as stream:json.load(stream)
            if path.name == 'lala_supported_resources.json':
                # A syntactically valid JSON is not sufficient: reject a
                # mismatched revision/Manifest before packaging or startup.
                from wlre.services.resource_compatibility import load_supported_resources
                load_supported_resources(path)
        elif path.suffix=='.gz':
            if path.name in ('npc_talk_1262.json.gz','npc_text_1262.json.gz',
                             'npc_battle_talk_1262.json.gz'):
                import hashlib
                from wlre.services.world.npc_asset_install import ASSETS
                expected_sha, expected_size, _, _, _ = ASSETS[path.name]
                if (path.stat().st_size != expected_size
                        or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha):
                    raise RuntimeError('1262 NPC 原始文字檔案雜湊不符：'+path.name)
            if path.name == 'npc_interact_1262.json.gz':
                import hashlib
                from wlre.features.npc.domain.npc_interact import EXPECTED_SHA256
                if (path.stat().st_size != 19914
                        or hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED_SHA256):
                    raise RuntimeError('官方 1262 NPC 選項索引 SHA-256 或大小不符')
            with gzip.open(path,'rb') as stream:
                raw=stream.read(16*1024*1024+1)
            if len(raw)>16*1024*1024:
                raise RuntimeError('Compressed resource exceeds size limit: '+path.name)
            json.loads(raw.decode('utf8'))
        elif path.suffix=='.zip':
            with zipfile.ZipFile(path) as archive:
                bad=archive.testzip()
                if bad:raise RuntimeError(f'Corrupt resource: {path.name}/{bad}')
        elif path.suffix.lower() in ('.png','.ico'):
            with Image.open(path) as image:image.verify()
