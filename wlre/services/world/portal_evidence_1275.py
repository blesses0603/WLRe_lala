"""Exhaustive read-only evidence for official 1275 EveDoorLinks.

Each EveDoorLinks entry has a one-based scene-local ordinal according to
EveDoorLinksData.GetDoorDataByIndex. Missing StageMapData entries must not
erase a correctly decoded source position or destination. This index never
authorizes C20-8, movement or a hidden-portal trigger.
"""
from __future__ import annotations

from collections import Counter

from wlre.services.world.portal_links_1275 import (
    parse_eve_door_links, parse_stage_map_portals)


def _packet_position(stage, x, y):
    if not isinstance(stage, dict):
        return None
    rx, ry = stage.get('pos_x_ratio'), stage.get('pos_y_ratio')
    if (type(rx) is not int or type(ry) is not int
            or not 1 <= rx <= 255 or not 1 <= ry <= 255
            or type(x) is not int or type(y) is not int):
        return None
    a, b = x * rx, y * ry
    return (a, b) if 0 <= a <= 65535 and 0 <= b <= 65535 else None


def _projection_guard(stage):
    """Require official current-version geometry before drawing old packed PNG."""
    if not isinstance(stage, dict):
        return None
    keys = ('map_width', 'map_height', 'small_offset_x', 'small_offset_y')
    if not all(type(stage.get(key)) is int for key in keys):
        return None
    width = 6992 if stage['map_width'] == 65535 else stage['map_width']
    height = 6992 if stage['map_height'] == 65535 else stage['map_height']
    if max(width, height) <= 0:
        return None
    return {'rate': 100 * (1024 - 24) / max(width, height),
            'offset_x': stage['small_offset_x'],
            'offset_y': stage['small_offset_y'],
            'height': height}


def read_only_portal_evidence(stage_raw, link_raw, doors, stages):
    """Preserve every official scene-local link, including unmarked entries.

    Inputs must already be pinned and authenticated official TextAssets. A
    matched name, location or destination is display evidence, never proof
    of a server-accepted door index. Unknown scenes/ratios remain unknown;
    their unscaled official grid coordinates are retained for diagnostics.
    """
    markers = parse_stage_map_portals(stage_raw)
    links = parse_eve_door_links(link_raw)
    if not isinstance(doors, dict) or not isinstance(stages, dict):
        raise TypeError('1275 傳點資料型別不符')
    answer = {}
    for scene, rows in links.items():
        counts = Counter(
            row['index'] for row in doors.get(scene, ())
            if isinstance(row, dict) and type(row.get('index')) is int)
        for link in rows:
            idx, target = link['index'], link['destination']
            marker = markers.get((scene, idx))
            src = _packet_position(stages.get(scene), link['x'], link['y'])
            dst = _packet_position(stages.get(target),
                                   link['arrival_x'], link['arrival_y'])
            event_unique = counts[idx] == 1
            marker_confirmed = bool(marker and marker['kind'] == 2)
            issues = []
            if not event_unique:
                issues.append('missing_eve_door' if counts[idx] == 0
                              else 'duplicate_eve_door')
            if not marker_confirmed:
                issues.append('missing_normal_stage_marker')
            if scene not in stages:
                issues.append('source_scene_undefined')
            if target not in stages:
                issues.append('destination_scene_undefined')
            if src is None:
                issues.append('source_coordinate_uncalibrated')
            if dst is None:
                issues.append('arrival_coordinate_uncalibrated')
            answer[(scene, idx)] = {
                'scene': scene, 'index': idx, 'destination': target,
                'source_grid_x': link['x'], 'source_grid_y': link['y'],
                'arrival_grid_x': link['arrival_x'],
                'arrival_grid_y': link['arrival_y'],
                'x': src[0] if src else None,
                'y': src[1] if src else None,
                'arrival_x': dst[0] if dst else None,
                'arrival_y': dst[1] if dst else None,
                'position_verified': src is not None,
                'projection_guard': _projection_guard(stages.get(scene)),
                'arrival_verified': dst is not None,
                'destination_defined': target in stages,
                'stage_marker_matched': marker_confirmed,
                'eve_event_matched': event_unique,
                'name_id': marker['name_id'] if marker_confirmed else None,
                'issues': tuple(issues),
                'source_kind': '1275_eve_door_links_reference',
                'can_send_packets': False,
            }
    return answer
