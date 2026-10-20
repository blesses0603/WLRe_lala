"""NPC catalogue for scene UI; do not confuse a map marker with an event NPC index.

Official 1262 EventData.NewNpc has an index (u16), id (u32),
coordinates (u32/u32) and eventCount. MapActionNpcData instead belongs
to extra NPCs using C195-3, *not* ordinary C20-1 interaction.

The bundled npc_event_index_1262.json.gz is extracted from official Eve 1262.
An explicit .json path remains supported for test fixtures or independent
verification. Never infer indices from list position, NPC ID, MapActionNpcData,
or portal IDs.
"""
import gzip
import json
from pathlib import Path
from wlre.paths import RESOURCE_ROOT
from wlre.services.items.catalog import CAT


SOURCE = 'EventData.NewNpc'
FORMAT_VERSION = 1262


def _valid_index(row):
    return (isinstance(row, dict)
            and type(row.get('index')) is int and 0 <= row['index'] <= 65535
            and type(row.get('npc_id')) is int and 0 < row['npc_id'] <= 4294967295
            and type(row.get('x')) is int and 0 <= row['x'] <= 4294967295
            and type(row.get('y')) is int and 0 <= row['y'] <= 4294967295
            and type(row.get('event_count')) is int and 0 <= row['event_count'] <= 255
            and (('event_ids' not in row) or (isinstance(row['event_ids'], list)
                 and len(row['event_ids']) == row['event_count']
                 and all(type(v) is int and 0 <= v <= 255 for v in row['event_ids']))))


class NPCIndex:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else RESOURCE_ROOT/'npc_event_index_1262.json.gz'
        self.scenes = {}
        if not self.path.is_file():
            if path is None:
                raise FileNotFoundError('官方 NPC 資料尚未隨套件安裝')
            return
        if self.path.suffix == '.gz':
            # Bound decompression before JSON parsing to reject corrupt or
            # maliciously expanded resource data.
            with gzip.open(self.path, 'rb') as stream:
                raw = stream.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError('NPC 索引檔超過安全上限')
            data = json.loads(raw.decode('utf-8'))
        else:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('version') != FORMAT_VERSION
                or data.get('source') != SOURCE or not isinstance(data.get('scenes'), dict)):
            raise ValueError('NPC 索引表不是官方 1262 EventData.NewNpc 格式')
        if path is None:
            if (data.get('scene_count') != 1256 or data.get('npc_count') != 10879
                    or data.get('bundle_md5') != '81af690395d5e6a233afa9a664e2c555'):
                raise ValueError('預裝 NPC 資料來源或數量不符官方 Eve 1262')
            if len(data['scenes']) != data['scene_count']:
                raise ValueError('NPC 場景數量不符')
        total = 0
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
            total += len(records)
            self.scenes[scene] = [dict(record) for record in records]
        if path is None and total != data['npc_count']:
            raise ValueError('NPC 索引資料總數不符')

    def for_scene(self, scene):
        return list(self.scenes.get(str(scene), []))


def display_name(npc_id, event_name=''):
    official=CAT.get('npcs', {}).get(str(npc_id), {}).get('name', '')
    if official: return str(official)[:100]
    if event_name and event_name not in ('Npc', 'NPC'): return str(event_name)[:100]
    return f'NPC #{npc_id}'


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
            'verified': match is not None, 'event_ids': list(match.get('event_ids', [])) if match else [],
            'buy_kind': match.get('buy_kind', 0) if match else 0,
            'base_define': match.get('base_define') if match else None,
            'source': SOURCE if match else 'map_position_reference',
        })
    # Some verified NPCs are not covered by the old marker file. Preserve them
    # as a separate, authoritative roster without inventing map markers.
    known = {(r['npc_index'], r['npc_id']) for r in rows if r['verified']}
    for v in verified:
        if (v['index'], v['npc_id']) in known:
            continue
        rows.append({
            'name': display_name(v['npc_id'], v.get('name')),
            'scene': scene, 'x': v['x'], 'y': v['y'], 'npc_id': v['npc_id'],
            'npc_index': v['index'], 'event_count': v['event_count'],
            'verified': True, 'source': SOURCE, 'event_ids': list(v.get('event_ids', [])),
            'buy_kind': v.get('buy_kind', 0), 'base_define': v.get('base_define'),
        })
    return rows


def npc_detail(row):
    coords = (f'({row["x"]}, {row["y"]})' if row.get('x') is not None
              and row.get('y') is not None else '位置未確認')
    if row.get('verified'):
        return (f'{coords}｜事件索引 {row["npc_index"]} 已核對，'
                + ('無互動事件' if row.get('event_count') == 0 else '手動事件可嘗試（選項／商店未開放）'))
    return f'{coords}｜索引未核對，不會送出對話封包'
