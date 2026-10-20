"""NPC catalogue for scene UI; do not confuse a map marker with an event NPC index.

Official 1262 EventData.NewNpc has an index (u16), id (u32),
coordinates (u32/u32) and eventCount. MapActionNpcData instead belongs
to extra NPCs using C195-3, *not* ordinary C20-1 interaction.

The optional npc_event_index_1262.json must be independently extracted and
verified against EventData.NewNpc. Never infer indices from list position,
NPC ID, MapActionNpcData, or portal IDs.
"""
import json
from pathlib import Path
from wlre.paths import RESOURCE_ROOT


SOURCE = 'EventData.NewNpc'
FORMAT_VERSION = 1262


def _valid_index(row):
    return (isinstance(row, dict)
            and type(row.get('index')) is int and 0 <= row['index'] <= 65535
            and type(row.get('npc_id')) is int and 0 < row['npc_id'] <= 4294967295
            and type(row.get('x')) is int and 0 <= row['x'] <= 4294967295
            and type(row.get('y')) is int and 0 <= row['y'] <= 4294967295
            and type(row.get('event_count')) is int and 0 < row['event_count'] <= 255)


class NPCIndex:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else RESOURCE_ROOT/'npc_event_index_1262.json'
        self.scenes = {}
        if not self.path.is_file():
            return
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('version') != FORMAT_VERSION
                or data.get('source') != SOURCE or not isinstance(data.get('scenes'), dict)):
            raise ValueError('NPC 索引表不是官方 1262 EventData.NewNpc 格式')
        for scene, records in data['scenes'].items():
            if not scene.isdecimal() or not 0 <= int(scene) <= 65535 or not isinstance(records, list):
                raise ValueError('NPC 場景索引資料格式錯誤')
            if len(records) > 4096:
                raise ValueError('單一場景 NPC 數量超過安全上限')
            indices = set()
            for record in records:
                if not _valid_index(record) or record['index'] in indices:
                    raise ValueError('NPC 資料無效或索引重複')
                indices.add(record['index'])
            self.scenes[scene] = [dict(record) for record in records]

    def for_scene(self, scene):
        return list(self.scenes.get(str(scene), []))


def scene_npcs(scene, entities, index=None):
    """Merge positional references with verified EventData rows, without guessing IDs.

    Every record carries explicit provenance and may be presented even when no
    verified binary index exists. Actual C20-1 remains disabled until dialogue
    handling is implemented and authority can be checked on the network thread.
    """
    verified = index.for_scene(scene) if index is not None else []
    rows = []
    for e in entities:
        if not isinstance(e, dict) or e.get('kind') != 0:
            continue
        x, y = e.get('x'), e.get('y')
        if type(x) is not int or type(y) is not int or not 0 <= x <= 4294967295 or not 0 <= y <= 4294967295:
            x = y = None
        npc_id = e.get('npc_id')
        if type(npc_id) is not int:
            npc_id = None
        # A name match is never identity proof; only exact scene/position and
        # an independent NPC ID can reconcile an old map marker.
        matches = [r for r in verified if npc_id is not None
                   and r['npc_id'] == npc_id and r['x'] == x and r['y'] == y]
        match = matches[0] if len(matches) == 1 else None
        rows.append({
            'name': str(e.get('name') or '未命名 NPC')[:100],
            'scene': scene, 'x': x, 'y': y, 'npc_id': npc_id,
            'npc_index': match['index'] if match else None,
            'event_count': match['event_count'] if match else None,
            'verified': match is not None,
            'source': SOURCE if match else 'map_position_reference',
        })
    # Some verified NPCs are not covered by the old marker file. Preserve them
    # as a separate, authoritative roster without inventing map markers.
    known = {(r['npc_index'], r['npc_id']) for r in rows if r['verified']}
    for v in verified:
        if (v['index'], v['npc_id']) in known:
            continue
        rows.append({
            'name': str(v.get('name') or f'NPC #{v["npc_id"]}')[:100],
            'scene': scene, 'x': v['x'], 'y': v['y'], 'npc_id': v['npc_id'],
            'npc_index': v['index'], 'event_count': v['event_count'],
            'verified': True, 'source': SOURCE,
        })
    return rows


def npc_detail(row):
    coords = (f'({row["x"]}, {row["y"]})' if row.get('x') is not None
              and row.get('y') is not None else '位置未確認')
    if row.get('verified'):
        return (f'{row["name"]}｜{coords}｜事件 NPC 索引 {row["npc_index"]} 已核對；'
                'NPC 對話及商店請待第二階段開放')
    return f'{row["name"]}｜{coords}｜僅位置參考，尚未核對事件 NPC 索引；不會送出對話封包'
