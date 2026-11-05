"""Official portal references and physical door bindings.

EveDoorLinks ordinals and StageMap display IDs are independent of Eve.NewDoor
container IDs. Actionable mappings require physical identity from current Eve
and scene geometry; display-only names have a separate API. A source binding
never proves that the live server accepted a transfer.
"""
from __future__ import annotations

from wlre.services.parser_diagnostics import diagnosed, checkpoint

import re
import struct


class PortalLinkSourceError(ValueError):
    pass


@diagnosed('stage-map-v1')
def parse_stage_map_portals(raw):
    """StageMapData.New: Kind 2 normal portal, Kind 3 hidden portal."""
    if type(raw) is not bytes or len(raw) < 4:
        raise PortalLinkSourceError('1275 StageMapData_C 來源無效')
    count = struct.unpack_from('<i', raw)[0]
    if count < 0 or count > 100000 or len(raw) != 4 + count * 18:
        raise PortalLinkSourceError('1275 StageMapData_C 筆數或長度不符')
    entries = {}
    for pos in range(4, len(raw), 18):
        checkpoint(offset=pos, field='marker', record=(pos - 4) // 18 + 1)
        scene, kind, cross_scene, event_id, x, y, name_id, sorting = (
            struct.unpack_from('<HBHIHHIB', raw, pos))
        if kind > 5:
            raise PortalLinkSourceError('1275 StageMapData_C 未知標記種類')
        if kind not in (2, 3):
            continue
        # 1262 Lua defines PositionX/Y as unsigned fields but does not
        # require either to be nonzero for NameID lookup. A portal label
        # must not disappear merely because its *display* position is 0.
        # Rendering/transfer positions are independently validated later.
        if not scene or not event_id:
            continue
        key = (scene, event_id)
        if key in entries:
            # Duplicate references to a portal cannot prove a unique route.
            entries[key] = None
            continue
        entries[key] = {'scene': scene, 'index': event_id, 'kind': kind,
                        'x': x, 'y': y,
                        'name_id': name_id, 'sorting': sorting,
                        'cross_scene': cross_scene}
    return {key: value for key, value in entries.items() if value is not None}


def verified_portal_names(stage_raw, scene_ids, texts):
    """1275 minimap labels are independent of destination/packet approval.

    Lua/UIMain.GetMapName uses StageMapData.NameID first. Its (SceneID,
    EvtID) key can name a portal even when EveDoorLinks is unavailable.
    Only a nonempty TextData entry tied to an unambiguous StageMap record
    is displayed. NameID=0 is an intentional absence, not a scene name.
    """
    rows = parse_stage_map_portals(stage_raw)
    result = {}
    scenes = set(scene_ids)
    for key, row in rows.items():
        scene, idx = key
        name_id = row.get('name_id')
        if scene not in scenes or type(idx) is not int or idx <= 0:
            continue
        if type(name_id) is not int or name_id <= 0:
            continue
        name = texts.get(name_id) if isinstance(texts, dict) else None
        if (type(name) is not str or not name.strip()
                or len(name) > 160 or any(ord(ch) < 32 for ch in name)):
            continue
        result[key] = name.strip()
    return result


_POINT = re.compile(r'^\s*[^:：\[\],]+[:：]\s*(\d+)\s*,\s*'
                    r'[^:：\[\],]+[:：]\s*(\d+)\s*$')
# Data.LoadEveDoorLinks locates 事件ID then reads the value after '='.
# Preserve both explicit header spellings; do not search arbitrary offsets.
_HEADER = re.compile(r'^\s*(?:事件ID|\[事件ID\])\s*=\s*(\d+)\s*$')


@diagnosed('eve-links-utf16-v1')
def parse_eve_door_links(raw):
    """EveDoorLinks is a UTF-16LE scene heading followed by 3 bracket fields."""
    if type(raw) is not bytes or not raw or len(raw) % 2 or len(raw) > 4 * 1024 * 1024:
        raise PortalLinkSourceError('1275 EveDoorLinks 長度不合法')
    try:
        text = raw.decode('utf-16-le').lstrip('\ufeff')
    except UnicodeDecodeError as exc:
        raise PortalLinkSourceError('1275 EveDoorLinks 文字編碼無效') from exc
    results, scene = {}, None
    for lineno, line in enumerate(text.splitlines(), 1):
        checkpoint(field='line', record=lineno)
        line = line.strip()
        if not line:
            continue
        header = _HEADER.fullmatch(line)
        if header:
            scene = int(header[1])
            if not 0 < scene <= 65535 or scene in results:
                raise PortalLinkSourceError('1275 EveDoorLinks 場景 ID 重複或無效')
            results[scene] = []
            continue
        if scene is None:
            raise PortalLinkSourceError('1275 EveDoorLinks 缺少場景標頭')
        parts = re.findall(r'\[([^\[\]]*)\]', line)
        if len(parts) != 3 or not line.startswith('原場景位置'):
            raise PortalLinkSourceError('1275 EveDoorLinks 連線格式未知')
        source, destination, arrival = parts
        origin_point, arrival_point = _POINT.fullmatch(source), _POINT.fullmatch(arrival)
        if not origin_point or not arrival_point or not destination.isdecimal():
            raise PortalLinkSourceError('1275 EveDoorLinks 座標或目的地不合法')
        dest = int(destination)
        if not 0 < dest <= 65535:
            raise PortalLinkSourceError('1275 EveDoorLinks 目的地超出範圍')
        coords = [int(origin_point[1]), int(origin_point[2]),
                  int(arrival_point[1]), int(arrival_point[2])]
        if any(not 0 <= value <= 65535 for value in coords):
            raise PortalLinkSourceError('1275 EveDoorLinks 座標超出範圍')
        results[scene].append({'scene': scene, 'index': len(results[scene]) + 1,
                               'x': coords[0], 'y': coords[1],
                               'destination': dest,
                               'arrival_x': coords[2], 'arrival_y': coords[3]})
    return results



def verified_portal_positions(stage_raw, link_raw, doors, stages):
    """Match physical doors; equal marker/link/container numbers prove nothing."""
    from wlre.services.world.boundary_portals import boundary_portal_bindings
    return boundary_portal_bindings(stage_raw,link_raw,doors,stages)[0]


def read_only_portal_destinations(stage_raw, link_raw, doors, scene_ids):
    """Map an official StageMap EvtID to EveDoorLinks target for UI labels.

    Original 1262 Lua indexes EveDoorLinks by (SceneID, EvtID); grid and
    event-space positions are different and must NOT be compared as equality.
    This supports a destination NAME only, not pathfinding, C20-8 or packet
    authorization. The stricter transfer verification stays independent.
    """
    markers = parse_stage_map_portals(stage_raw)
    links = parse_eve_door_links(link_raw)
    allowed_scenes = set(scene_ids)
    result = {}
    for scene, entries in doors.items():
        if type(scene) is not int or scene not in allowed_scenes:
            continue
        link_rows = links.get(scene, ())
        seen = set()
        for row in entries:
            if not isinstance(row, dict):
                continue
            index = row.get('index')
            if (type(index) is not int or not 1 <= index <= len(link_rows)
                    or (scene, index) not in markers
                    or markers[(scene, index)]['kind'] != 2
                    or index in seen):
                continue
            seen.add(index)
            link = link_rows[index - 1]
            if (link['scene'] == scene and link['index'] == index
                    and link['destination'] in allowed_scenes):
                result[(scene, index)] = link['destination']
    return result


def verified_portal_destinations(stage_raw, link_raw, doors, scene_ids):
    """Resolve actual doors using current scene geometry, never ordinal joins.

    A bare set of scene IDs supplies no physical identity evidence and cannot
    authorize a destination binding. Read-only labels use their separate API.
    """
    from wlre.services.world.boundary_portals import boundary_portal_bindings
    if not isinstance(scene_ids,dict):return {}
    return boundary_portal_bindings(stage_raw,link_raw,doors,scene_ids)[1]
