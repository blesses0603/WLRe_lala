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
    """StageMapData.New: int32 count, 18-byte records; Kind=2 is a portal."""
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
        if kind != 2:
            continue
        if not scene or not event_id or not x or not y:
            continue
        key = (scene, event_id)
        if key in entries:
            # Duplicate references to a portal cannot prove a unique route.
            entries[key] = None
            continue
        entries[key] = {'scene': scene, 'index': event_id, 'x': x, 'y': y,
                        'name_id': name_id, 'sorting': sorting,
                        'cross_scene': cross_scene}
    return {key: value for key, value in entries.items() if value is not None}


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
            if not marker:
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
