"""Browse source-verified current-version dungeon and co-op catalog.

Static records never imply that a server has an open room or that a reward
is claimable. No packet is emitted by this module.
"""
import json
from functools import lru_cache

from wlre.paths import RESOURCE_ROOT

CATALOG_FILE = RESOURCE_ROOT / "instance_catalog_1262.json"


def _catalog_1275():
    from wlre.services.world.runtime_1275 import active_runtime
    source = active_runtime()
    coops = {v['id']: v for v in source.cooperative_records}
    rows = []
    for dungeon in source.dungeon_records:
        scene = source.stages.get(dungeon['map_id'])
        if not scene:
            raise ValueError('1275 副本場景不存在，拒絕使用舊版場景資料')
        name_id = (coops[dungeon['npc_id']]['text_id']
                   if dungeon['kind'] == 2 and dungeon['npc_id'] in coops
                   else scene['name_id'] if dungeon['kind'] != 2 else None)
        name = source.texts.get(name_id) if name_id is not None else None
        if dungeon['kind'] == 2 and name_id is None:
            name = '協力活動 #' + str(dungeon['id'])
        if not isinstance(name, str) or not name.strip():
            raise ValueError('1275 副本缺少官方文字，拒絕回退舊版名稱')
        awards = [
            [slot, v['kind'], v['id'], v['value']]
            for slot, v in enumerate(dungeon['awards'], 1)
            if v['kind'] and v['id'] and v['value']
        ]
        rows.append({
            'id': dungeon['id'], 'kind': dungeon['kind'],
            'variant': dungeon['para_kind'], 'map_id': dungeon['map_id'],
            'name': name, 'min_level': scene['min_level'],
            'min_members': scene['min_members'],
            'max_members': scene['max_members'],
            'time_minutes': scene['time_minutes'],
            'room_count': scene['room_capacity'],
            'is_open': scene['is_open'], 'npc_id': dungeon['npc_id'],
            'awards': awards,
        })
    return {
        'version': 1275, 'verified_source': True,
        'source': '1275 verified DungeonData_C / CooperateEventData_C / ScenesData_C / TextData_C',
        'counts': {'dungeon_records': len(rows), 'scenes': len(source.stages),
                   'cooperative_events': len(source.cooperative_records),
                   'traditional_chinese_texts': len(source.texts),
                   'unique_dungeon_ids': len({row['id'] for row in rows})},
        'records': rows,
    }


@lru_cache(maxsize=1)
def official_catalog():
    from wlre.services.world.runtime_1275 import baseline_revision
    if baseline_revision() == '1275':
        from wlre.services.world.runtime_1275 import Runtime1275Unavailable
        try:
            value = _catalog_1275()
        except Runtime1275Unavailable:
            # Pre-login UI stays available; never use a legacy dungeon ID.
            return {'version': 1275, 'verified_source': False, 'records': [],
                    'counts': {}, 'source_status': 'unavailable'}
    else:
        value = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    records = value.get("records")
    counts = value.get("counts", {})
    if (value.get("version") not in (1262, 1275)
            or not value.get("verified_source")):
        raise ValueError("未經官方版本校驗的副本資料表")
    if not isinstance(records, list) or len(records) != 30:
        raise ValueError("副本資料筆數不符")
    if counts.get("dungeon_records") != len(records):
        raise ValueError("副本資料紀錄數不符")
    if (sum(row["kind"] == 1 for row in records),
        sum(row["kind"] == 2 for row in records),
        sum(row["kind"] == 3 for row in records)) != (26, 3, 1):
        raise ValueError("副本種類筆數不符")
    seen = set()
    for row in records:
        key = (row["id"], row["variant"])
        if key in seen or not isinstance(row.get("name"), str) or not row["name"].strip():
            raise ValueError("副本重複或缺少官方中文名稱")
        seen.add(key)
        if not isinstance(row.get("awards"), list) or len(row["awards"]) > 16:
            raise ValueError("副本獎勵資料不完整")
        if any(len(award) != 4 or not (1 <= award[0] <= 16)
               for award in row["awards"]):
            raise ValueError("副本獎勵欄位異常")
    return value


def entries_for(mode):
    if mode not in ("main", "coop"):
        raise ValueError("未知副本分類")
    rows = official_catalog()["records"]
    return tuple(row for row in rows if (row["kind"] == 2) == (mode == "coop"))
