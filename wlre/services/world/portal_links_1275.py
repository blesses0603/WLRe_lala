"""Strict 1275 read-only portal destinations, derived from official tables.

1275 Eve.NewDoor supplies source scene / door index / position. The game's
StageMapData_C marker references a source event index; EveDoorLinks supplies a
destination by ordinal. Bind only when all three sources agree exactly.

This module NEVER approves C20-8 packets. Only a successful server scene
snapshot can confirm an actual transfer.
"""
from __future__ import annotations

import re
import struct


class PortalLinkSourceError(ValueError):
    pass


def parse_stage_map_portals(raw):
    """StageMapData.New: Kind 2 normal portal, Kind 3 hidden portal."""
    if type(raw) is not bytes or len(raw) < 4:
        raise PortalLinkSourceError('1275 StageMapData_C 來源無效')
    count = struct.unpack_from('<i', raw)[0]
    if count < 0 or count > 100000 or len(raw) != 4 + count * 18:
        raise PortalLinkSourceError('1275 StageMapData_C 筆數或長度不符')
    entries = {}
    for pos in range(4, len(raw), 18):
        scene, kind, cross_scene, event_id, x, y, name_id, sorting = (
            struct.unpack_from('<HBHIHHIB', raw, pos))
        if kind > 5:
            raise PortalLinkSourceError('1275 StageMapData_C 未知標記種類')
        if kind not in (2, 3):
            continue
        if not scene or not event_id or not x or not y:
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
_HEADER = re.compile(r'^\s*事件ID\s*=\s*(\d+)\s*$')


def parse_eve_door_links(raw):
    """EveDoorLinks is a UTF-16LE scene heading followed by 3 bracket fields."""
    if type(raw) is not bytes or not raw or len(raw) % 2 or len(raw) > 4 * 1024 * 1024:
        raise PortalLinkSourceError('1275 EveDoorLinks 長度不合法')
    try:
        text = raw.decode('utf-16-le').lstrip('\ufeff')
    except UnicodeDecodeError as exc:
        raise PortalLinkSourceError('1275 EveDoorLinks 文字編碼無效') from exc
    results, scene = {}, None
    for line in text.splitlines():
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
    """Map the *actual* official minimap portal point into packet XY.

    UIMain._SetPortalPosition displays EveDoorLinks.mapPosition, not Eve
    NewDoor's common-event x/y. Lua multiplies EveDoorLinks' grid values
    by the source scene's PosXRatio / PosYRatio before TransferPosition.
    In packet XY, TEMP_OFFSET_X=0 and the mapHeight y-inversion cancels.
    StageMapData proves the (scene, EvtID) portal identity only; its
    PositionX/Y and Eve.NewDoor x/y are NOT screen coordinates.

    A missing/ambiguous entry, unknown scene ratios or impossible result
    is never silently projected or sent to the movement handler.
    """
    markers = parse_stage_map_portals(stage_raw)
    links = parse_eve_door_links(link_raw)
    result = {}
    for scene, entries in doors.items():
        if type(scene) is not int:
            continue
        stage = stages.get(scene)
        if not isinstance(stage, dict):
            continue
        rx, ry = stage.get('pos_x_ratio'), stage.get('pos_y_ratio')
        if (type(rx) is not int or type(ry) is not int
                or not 1 <= rx <= 255 or not 1 <= ry <= 255):
            continue
        linked = links.get(scene, ())
        for door in entries:
            if not isinstance(door, dict):
                continue
            index = door.get('index')
            if (type(index) is not int or not 1 <= index <= len(linked)
                    or (scene, index) not in markers
                    or markers[(scene, index)]['kind'] != 2):
                continue
            link = linked[index - 1]
            if link.get('scene') != scene or link.get('index') != index:
                continue
            x, y = link['x'] * rx, link['y'] * ry
            if not 0 <= x <= 65535 or not 0 <= y <= 65535:
                continue
            # Runtime minimap images are still sourced from the older
            # resource pack. When 1275 provides geometry, require it to
            # agree with the image projection before displaying a marker.
            known_geometry = all(type(stage.get(key)) is int for key in (
                'map_width', 'map_height', 'small_offset_x', 'small_offset_y'))
            geometry = None
            if known_geometry:
                width = (6992 if stage['map_width'] == 65535
                         else stage['map_width'])
                height = (6992 if stage['map_height'] == 65535
                          else stage['map_height'])
                if max(width, height) <= 0:
                    continue
                geometry = {
                    'rate': 100 * (1024 - 24) / max(width, height),
                    'offset_x': stage['small_offset_x'],
                    'offset_y': stage['small_offset_y'],
                    'height': height,
                }
            result[(scene, index)] = {
                'x': x, 'y': y, 'scene': scene, 'index': index,
                'projection_guard': geometry,
                'source_kind': '1275_eve_door_links_grid_scaled',
                'raw_link_x': link['x'], 'raw_link_y': link['y'],
                'pos_x_ratio': rx, 'pos_y_ratio': ry,
                'position_verified': True,
            }
    return result




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
    """Reconcile three independent official 1275 sources without packet approval.

    Only exact scene, event-index, XY and valid destination evidence is shown.
    An ambiguous or incomplete mapping remains unavailable to the UI.
    """
    markers = parse_stage_map_portals(stage_raw)
    links = parse_eve_door_links(link_raw)
    scenes = set(scene_ids)
    result = {}
    for scene, entries in doors.items():
        if type(scene) is not int or scene not in scenes:
            continue
        scene_links = links.get(scene, ())
        for row in entries:
            index = row.get('index')
            if type(index) is not int or index <= 0 or index > len(scene_links):
                continue
            marker = markers.get((scene, index))
            if not marker or marker['kind'] != 2:
                continue
            link = scene_links[index - 1]
            if (marker['x'] != row.get('x') or marker['y'] != row.get('y')
                    or link['x'] != marker['x'] or link['y'] != marker['y']
                    or link['destination'] not in scenes):
                continue
            result[(scene, index)] = dict(link, matched_stage_map=True,
                                         destination_verified=True,
                                         trigger_verified=False)
    return result
