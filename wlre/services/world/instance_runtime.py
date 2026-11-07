"""Verified current dungeon/cooperative tables, normalized into local SQLite."""
from pathlib import Path
import hashlib

TABLES = ('DungeonData_C', 'CooperateEventData_C')


def build_catalog(payloads, catalog_key, package_version):
    from wlre.services.instance_catalog import parse_dungeons, parse_cooperative_events, parse_stages
    from wlre.services.expedition.data import parse_text_data
    from wlre.services.world.itemdata_v1 import parse_itemdata
    stages = parse_stages(payloads['ScenesData_C'])
    texts = parse_text_data(payloads['TextData_C'])
    items = parse_itemdata(payloads['ItemData_C'], package_version=package_version)
    events = {}
    for event in parse_cooperative_events(payloads['CooperateEventData_C']):
        if not event['id'] or event['id'] in events:
            raise ValueError('協力事件 ID 重複或為零')
        events[event['id']] = event
    records, seen, maps = [], set(), set()
    for dungeon in parse_dungeons(payloads['DungeonData_C']):
        key = dungeon['id'], dungeon['para_kind']
        if not key[0] or key in seen:
            raise ValueError('副本複合識別碼重複或無效')
        seen.add(key)
        stage = stages.get(dungeon['map_id'])
        if stage is None:
            raise ValueError('副本缺少同版場景')
        if dungeon['kind'] == 1:
            if dungeon['map_id'] in maps:
                raise ValueError('一般副本場景無法唯一識別')
            maps.add(dungeon['map_id'])
        event = events.get(dungeon['npc_id']) if dungeon['kind'] == 2 else None
        if dungeon['kind'] == 2 and dungeon['para_kind'] == 2 and event is None:
            raise ValueError('具名協力副本缺少同版事件')
        name_id = event['text_id'] if event else stage['name_id']
        name = texts.get(name_id)
        if not isinstance(name, str) or not name.strip():
            raise ValueError('副本缺少同版官方名稱')
        minimum, maximum = stage['min_members'], stage['max_members']
        if not 0 <= minimum <= maximum <= 255:
            raise ValueError('副本人數範圍無效')
        awards = []
        for slot, award in enumerate(dungeon['awards'], 1):
            if award['kind'] == 0:
                if award['id'] or award['value']:
                    raise ValueError('空獎勵槽位含有未知資料')
                continue
            if award['kind'] in (10, 11) and award['id'] not in items:
                raise ValueError('副本獎勵缺少同版道具')
            awards.append([slot, award['kind'], award['id'], award['value']])
        supported = (dungeon['kind'] == 1 and minimum > 0 or
                     dungeon['kind'] == 2 and dungeon['para_kind'] in (1, 2)
                     and 1 <= minimum <= maximum <= 8
                     and (dungeon['para_kind'] != 1 or dungeon['npc_id'] == 0))
        records.append({**dungeon, 'variant': dungeon['para_kind'],
            'name': name, 'min_level': stage['min_level'],
            'min_members': minimum, 'max_members': maximum,
            'time_minutes': stage['time_minutes'], 'room_count': stage['room_capacity'],
            'is_open': None, 'awards': awards, 'cooperative_event': event,
            'creation_supported': supported, 'catalog_key': catalog_key})
    if not records:
        raise ValueError('官方副本資料為空')
    return {'catalog_key': catalog_key, 'package_version': package_version,
            'source': 'verified_official_bundle', 'records': records,
            'cooperative_events': list(events.values()),
            'source_sha256': {k: hashlib.sha256(v).hexdigest() for k, v in payloads.items()},
            'counts': {'dungeon_records': len(records), 'scenes': len(stages),
                       'traditional_chinese_texts': len(texts)}}


def load_verified_catalog(manifest, bundle_root, loader, root, identity, core_sources):
    from wlre.services.official_incremental_sync import build_update_plan
    from wlre.services.official_bundle_download import _verified_file
    from wlre.services.world.catalog_adapters import SourceContract
    from wlre.services.world.official_catalog_pipeline import AssetBinding
    from wlre.services.world.unity_textasset import extract_textasset
    from wlre.storage.normalized_resources import load_parsed
    payloads = {name: core_sources[name] for name in ('ScenesData_C', 'TextData_C', 'ItemData_C')}
    for table in TABLES:
        asset = 'Assets/ResourcesBuild/Data/' + table + '.bytes'
        plan = build_update_plan(manifest, asset_paths=(asset,), cache_root=bundle_root)
        if not plan.entries or any(row.action != 'cached' for row in plan.entries):
            raise ValueError('副本官方資料尚未快取：' + table)
        paths = tuple(row.spec.cache_path(bundle_root) for row in plan.entries)
        if any(not _verified_file(path, row.spec) for path, row in zip(paths, plan.entries)):
            raise ValueError('副本 Bundle 校驗失敗：' + table)
        binding = AssetBinding(asset, SourceContract('scenes', table, 'stage-new-76-v1',
            '0' * 64, 'DataPackage', manifest.spec.package_version))
        payloads[table] = extract_textasset(binding, paths, loader=loader)
    return load_parsed(Path(root) / 'derived_catalogs' / 'resource_inventory.sqlite3',
        identity.key, 'instances', 'instances-v1', payloads,
        lambda: build_catalog(payloads, identity.key, manifest.spec.package_version))
