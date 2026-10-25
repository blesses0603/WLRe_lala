"""Verified 1275 data source for read-only LaLa desktop previews.

Requires two independently validated user-provided ZIPs. Does not change the
supported 1262 baseline, register network commands, or emit any packets.
"""
from __future__ import annotations

import gzip
from copy import deepcopy
import io
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from zipfile import ZipFile

from wlre.services.world.game_data_1275 import read_manifest, verify_archive
from wlre.services.world.npc_1275_eve import read_verified_zip
from wlre.services.world.doors_1275 import parse_doors_1275
from wlre.services.world.portal_links_1275 import (verified_portal_destinations,
                                                    verified_portal_names,
                                                    verified_portal_positions,
                                                    PortalLinkSourceError)

MAX_UNCOMPRESSED = 16 * 1024 * 1024


class PreviewError(ValueError):
    """1275 data source was incomplete, invalid, or incompatible."""


def _catalog(archive, manifest, filename, source):
    name = 'indexes/' + filename
    info = manifest['files'].get(name)
    if info is None or info.get('kind') != 'read_only_index':
        raise PreviewError('1275 唯讀索引不存在：' + filename)
    with ZipFile(archive) as z:
        raw = z.read(name)
    if len(raw) != info['bytes']:
        raise PreviewError('1275 唯讀索引大小錯誤')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        payload = stream.read(MAX_UNCOMPRESSED + 1)
    if len(payload) > MAX_UNCOMPRESSED:
        raise PreviewError('1275 索引超過解壓縮上限')
    doc = json.loads(payload.decode('utf-8'))
    if (type(doc) is not dict or doc.get('version') != 1275
            or doc.get('source') != source
            or type(doc.get('records')) is not dict
            or doc.get('record_count') != len(doc['records'])):
        raise PreviewError('1275 索引版本／來源／筆數不符')
    return doc['records']


def _table(archive, manifest, table):
    matches = [name for name, info in manifest['files'].items()
               if info.get('kind') == 'raw_table' and info.get('table') == table]
    if len(matches) != 1:
        raise PreviewError('1275 資料表不存在或名稱重複：' + table)
    with ZipFile(archive) as z:
        return z.read(matches[0])


def parse_smith_1275(data):
    """Parse official SmithData.New 33-byte records into LaLa recipe shape.

    Validation is for local catalog rendering only, never live craft commands.
    """
    if type(data) is not bytes or len(data) < 4:
        raise PreviewError('1275 製作配方資料無效')
    count = struct.unpack_from('<i', data, 0)[0]
    if not 0 <= count <= 20000 or len(data) != 4 + 33 * count:
        raise PreviewError('1275 配方筆數或長度不符')
    result = {}
    for order in range(1, count + 1):
        pos = 4 + (order - 1) * 33
        item_id, design = struct.unpack_from('<HH', data, pos)
        skill = data[pos + 4]
        tool = struct.unpack_from('<H', data, pos + 5)[0]
        output = data[pos + 7]
        materials = []
        for idx in range(5):
            mid, amount = struct.unpack_from('<HB', data, pos + 8 + 3 * idx)
            if mid:
                materials.append({'item_id': mid, 'count': amount})
        material_count = data[pos + 23]
        seconds = struct.unpack_from('<H', data, pos + 24)[0]
        skill_level, suggest = struct.unpack_from('<BB', data, pos + 26)
        time_id = struct.unpack_from('<H', data, pos + 28)[0]
        limit_kind, mark_id, limit_times = struct.unpack_from('<BBB', data, pos + 30)
        if not item_id or item_id in result or material_count > 5:
            raise PreviewError('1275 配方 ID 重複或材料數異常')
        result[item_id] = {
            'item_id': item_id, 'design_id': design, 'skill': skill,
            'tool_id': tool, 'output': output, 'materials': materials,
            'seconds': seconds, 'skill_level': skill_level, 'suggest': suggest,
            'time_id': time_id, 'limit_kind': limit_kind, 'mark_id': mark_id,
            'limit_times': limit_times, 'order': order,
        }
    return result


class PreviewNPCIndex:
    """NPCIndex.for_scene-compatible source; results are snapshots."""
    def __init__(self, doc):
        self.scenes = doc['scenes']

    def for_scene(self, scene):
        return deepcopy(self.scenes.get(str(scene), ()))


class PreviewInteractIndex:
    """NPCInteractIndex.get/choices-compatible read-only source."""
    def __init__(self, doc):
        self.scenes = {int(key): {row['index']: row for row in rows}
                       for key, rows in doc['scenes'].items()}

    def get(self, scene, interact_index):
        if type(scene) is not int or type(interact_index) is not int:
            return None
        row = self.scenes.get(scene, {}).get(interact_index)
        return None if row is None else deepcopy(row)

    def choices(self, scene, interact_index, talks):
        from wlre.services.world.npc_interact import NPCInteractIndex
        return NPCInteractIndex.choices(self, scene, interact_index, talks)


@dataclass(frozen=True)
class Preview1275:
    npc_index: PreviewNPCIndex
    interact_index: PreviewInteractIndex
    items: dict
    talks: dict
    texts: dict
    recipes: dict
    scene_ids: frozenset
    doors: dict = field(default_factory=dict)
    scene_names: dict = field(default_factory=dict)
    portal_destinations: dict = field(default_factory=dict)
    portal_names: dict = field(default_factory=dict)
    portal_positions: dict = field(default_factory=dict)
    portal_metadata_status: str = 'missing_stage_map'
    expedition: dict | None = None
    revision: int = 1275
    can_send_packets: bool = False

    def npc_for_scene(self, scene):
        return self.npc_index.for_scene(scene)

    def shop_for_scene(self, scene, interact_index):
        from wlre.services.world.npc_shop import shop_catalog
        return shop_catalog(scene, interact_index, index=self.interact_index,
                            item_rows=self.items)

    def recipe(self, item_id):
        if type(item_id) is not int:
            return None
        row = self.recipes.get(item_id)
        return None if row is None else deepcopy(row)

    def portal_status(self, scene, door_index=None):
        """1275 actual NewDoor positions; never authorize a transfer packet."""
        if type(scene) is not int or scene not in self.scene_ids:
            return {'scene': scene, 'exists': False, 'can_send_packets': False,
                    'reason': '新版場景資料沒有此 ID'}
        entries = self.doors.get(scene, ())
        result = {'scene': scene, 'exists': True, 'door_count': len(entries),
                  'can_send_packets': False}
        if door_index is None:
            result['reason'] = '1275 場景與門事件已讀取；尚未核對傳送目的地／條件'
            return result
        if type(door_index) is not int:
            raise ValueError('門事件索引必須是整數')
        found = [row for row in entries if row['index'] == door_index]
        result['door'] = dict(found[0]) if len(found) == 1 else None
        result['reason'] = ('1275 門事件存在，但傳送目的地及正式服回覆尚未驗證'
                            if found else '1275 找不到原有門事件 index，禁止觸發')
        return result


def load_preview(data_archive, eve_archive):
    """Fail closed unless both verified 1275 archives are supplied together."""
    data_archive, eve_archive = Path(data_archive), Path(eve_archive)
    verify_archive(data_archive)
    with ZipFile(data_archive) as z:
        manifest = read_manifest(z)
    eve = read_verified_zip(eve_archive)

    from wlre.services.instance_catalog import parse_stages
    from wlre.services.world.scene_names_1275 import bind_scene_names
    stages = parse_stages(_table(data_archive, manifest, 'ScenesData_C'))
    texts = {int(k): v for k, v in _catalog(
        data_archive, manifest, 'npc_text_1275.json.gz', 'TextData_C').items()}
    doors = parse_doors_1275(_table(data_archive, manifest, 'Eve'))
    portal_names, portal_destinations, portal_positions = {}, {}, {}
    portal_metadata_status = 'missing_stage_map'
    try:
        stage_map = _table(data_archive, manifest, 'StageMapData_C')
        # StageMapData.NameID is independently useful, even when links are
        # absent. Do not drop its official labels with the destination map.
        portal_names = verified_portal_names(stage_map, stages, texts)
        portal_metadata_status = 'stage_map_ready'
        try:
            link_table = _table(data_archive, manifest, 'EveDoorLinks')
            portal_positions = verified_portal_positions(
                stage_map, link_table, doors, stages)
            portal_destinations = verified_portal_destinations(
                stage_map, link_table, doors, stages)
            portal_metadata_status = 'destination_links_loaded'
        except (ValueError, KeyError, TypeError, PortalLinkSourceError):
            portal_metadata_status = 'destination_links_missing_or_invalid'
    except (ValueError, KeyError, TypeError, PortalLinkSourceError):
        # Optional source problems do not prevent the core verified runtime.
        pass
    return Preview1275(
        npc_index=PreviewNPCIndex(eve['npc_event_index_1275.json.gz']),
        interact_index=PreviewInteractIndex(eve['npc_interact_1275.json.gz']),
        items={int(k): v for k, v in _catalog(data_archive, manifest,
              'npc_item_data_1275.json.gz', 'ItemData_C').items()},
        talks={int(k): v['text'] for k, v in _catalog(data_archive, manifest,
              'npc_talk_1275.json.gz', 'TalkData_C').items()},
        texts=texts,
        recipes=parse_smith_1275(_table(data_archive, manifest, 'SmithData_C')),
        scene_ids=frozenset(stages),
        scene_names=bind_scene_names(stages, texts),
        portal_destinations=portal_destinations,
        portal_names=portal_names,
        portal_positions=portal_positions,
        portal_metadata_status=portal_metadata_status,
        doors=doors,
    )
