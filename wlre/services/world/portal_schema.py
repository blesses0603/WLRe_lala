"""Version-independent portal table shape recognition from audited 1262 Lua.

These are DATA layouts, not transport protocols or release approvals.
A future verified TextAsset can reuse one of these readers only when all
record-size, type and encoding checks pass. No heuristic byte-offset search,
partial parsing or 1262 scene/door/coordinate fallback is allowed.
"""
from __future__ import annotations

import struct

# Verified against Lua/Data/StageMapData.lua and
# Lua/Logic/Data.lua (Data.LoadEveDoorLinks / Data.LoadDoorLinkData).
STAGE_MAP_LAYOUT = 'stage-map-le-v1'
EVE_LINKS_LAYOUT = 'eve-door-links-utf16le-v1'
DOOR_LINK_LAYOUT = 'door-link-data-le-v1'
_STAGE_MAP = struct.Struct('<HBHIHHIB')
_DOOR_LINK = struct.Struct('<HHHHHH')
_MAX_ROWS = 100_000
_MAX_BYTES = 8 * 1024 * 1024


class PortalSchemaUnrecognized(ValueError):
    """Source does not match any approved read-only 1262-derived layout."""


def _record_count(raw, layout, name):
    if type(raw) is not bytes or not 4 <= len(raw) <= _MAX_BYTES:
        raise PortalSchemaUnrecognized(name + ' 資料長度或型別無效')
    count = struct.unpack_from('<i', raw, 0)[0]
    if count < 0 or count > _MAX_ROWS or len(raw) != 4 + count * layout.size:
        raise PortalSchemaUnrecognized(name + ' 筆數與記錄長度不符')
    return count


def inspect_stage_map(raw):
    """Check the complete 18-byte binary table, not merely its portal rows."""
    count = _record_count(raw, _STAGE_MAP, 'StageMapData_C')
    kinds = {kind: 0 for kind in range(6)}
    for offset in range(4, len(raw), _STAGE_MAP.size):
        scene, kind, cross, evt, x, y, name, sorting = (
            _STAGE_MAP.unpack_from(raw, offset))
        if kind not in kinds or not scene:
            raise PortalSchemaUnrecognized('StageMapData_C 場景或標記類型不符')
        kinds[kind] += 1
    return {'source': 'StageMapData_C', 'schema': STAGE_MAP_LAYOUT,
            'status': 'recognized', 'record_count': count,
            'portal_records': kinds[2] + kinds[3],
            'kind_counts': kinds, 'can_send_packets': False}


def inspect_eve_door_links(raw):
    """Only the explicit UTF-16LE event-header format is recognized."""
    from wlre.services.world.portal_links_1275 import (
        parse_eve_door_links, PortalLinkSourceError)
    try:
        scenes = parse_eve_door_links(raw)
    except (PortalLinkSourceError, UnicodeError, ValueError, TypeError) as exc:
        raise PortalSchemaUnrecognized('EveDoorLinks UTF-16LE 資料結構不符') from exc
    return {'source': 'EveDoorLinks', 'schema': EVE_LINKS_LAYOUT,
            'status': 'recognized', 'scene_count': len(scenes),
            'link_count': sum(len(rows) for rows in scenes.values()),
            'can_send_packets': False}


def parse_door_link_data(raw):
    """Read-only 12-byte routing edges, NOT EveDoorLinks event indices.

    Each entry: sourceScene/u16, sourceX/u16, sourceY/u16,
    destinationScene/u16, destinationX/u16, destinationY/u16.
    Do NOT derive a portal EvtID or actionable C20-8 trigger from this.
    """
    count = _record_count(raw, _DOOR_LINK, 'DoorLinkData_C')
    rows = []
    for offset in range(4, len(raw), _DOOR_LINK.size):
        source, x, y, destination, arrival_x, arrival_y = (
            _DOOR_LINK.unpack_from(raw, offset))
        if not source or not destination:
            raise PortalSchemaUnrecognized(
                'DoorLinkData_C 來源或目的地場景為零')
        rows.append({'source_scene': source, 'source_x': x, 'source_y': y,
                     'destination_scene': destination,
                     'arrival_x': arrival_x, 'arrival_y': arrival_y})
    return rows


def inspect_door_link_data(raw):
    rows = parse_door_link_data(raw)
    return {'source': 'DoorLinkData_C', 'schema': DOOR_LINK_LAYOUT,
            'status': 'recognized', 'record_count': len(rows),
            'can_send_packets': False}


_READERS = {
    'StageMapData_C': inspect_stage_map,
    'EveDoorLinks': inspect_eve_door_links,
    'DoorLinkData_C': inspect_door_link_data,
}


def _failure_detail(error):
    """Only emit fixed diagnostic codes/text; never raw source or exception data."""
    reasons = (
        ('缺少場景標頭', 'scene_header_unrecognized', '未辨識場景標頭；應為事件ID=編號或[事件ID]=編號'),
        ('場景 ID 重複或無效', 'scene_header_invalid', '場景標頭重複或編號超出範圍'),
        ('連線格式未知', 'link_fields_unrecognized', '門連線行缺少原場景位置或三組方括號欄位'),
        ('座標或目的地不合法', 'link_value_invalid', '門連線座標或目的地欄位未通過數字格式驗證'),
        ('超出範圍', 'value_out_of_range', '門連線編號或座標超出已審核範圍'),
        ('文字編碼無效', 'encoding_invalid', '門連線文字不是有效的 UTF-16LE'),
        ('筆數與記錄長度不符', 'record_length_mismatch', '表頭筆數與完整檔案的記錄長度不符'),
        ('長度不合法', 'source_length_invalid', '門連線資料長度或型別不符'),
        ('資料長度或型別無效', 'source_length_invalid', '表格資料長度或型別不符'),
    )
    current = error
    for _ in range(4):
        if current is None: break
        for marker, code, hint in reasons:
            if marker in str(current):
                return {'reason_code': code, 'parse_hint': hint}
        current = current.__cause__
    return {'reason_code': 'unrecognized_layout', 'parse_hint': '資料未通過已審核結構；需核對實際來源'}


def recognize_portal_source(source, raw):
    """Return a bounded, JSON-friendly verdict without guessing a new schema.

    Only call on bytes from an independently verified official source.
    Layout recognition means *read-only decoding compatible*, not a
    validated release manifest or server navigation protocol.
    """
    if source not in _READERS:
        return {'source': str(source)[:64], 'status': 'unsupported_table',
                'schema': None, 'can_send_packets': False}
    try:
        return _READERS[source](raw)
    except PortalSchemaUnrecognized as exc:
        return {'source': source, 'schema': None,
                'status': 'layout_unrecognized', 'can_send_packets': False,
                **_failure_detail(exc)}
