"""1275 official scene markers and inter-scene graph, read-only.

Layouts follow the original StageMapData, EveDoorLinksData and Data.LoadDoorLinkData
Lua functions. Never infer a door event index, destination permission, waypoint
mesh or movement packet from a text-link position.
"""
from __future__ import annotations
import re
import struct
from collections import deque


class Topology1275Error(ValueError):
    pass


def _rows(raw, width, limit):
    if type(raw) is not bytes or len(raw) < 4:
        raise Topology1275Error('1275 拓樸資料不是完整二進位')
    count = struct.unpack_from('<i', raw)[0]
    if not 0 <= count <= limit or len(raw) != 4 + width * count:
        raise Topology1275Error('1275 拓樸資料筆數或記錄寬度不正確')
    return count


def parse_stage_markers(raw, stages):
    """18-byte StageMapData.New, including all kinds 0..5."""
    count = _rows(raw, 18, 100000)
    result = {}
    for i in range(count):
        stage, kind, cross, event, x, y, name, order = struct.unpack_from(
            '<HBHIHHIB', raw, 4 + i * 18)
        if not stage or not 0 <= kind <= 5:
            raise Topology1275Error('1275 地圖標記 ID 或種類無效')
        info = stages.get(stage)
        result.setdefault(stage, []).append({
            'scene': stage, 'kind': kind, 'event_id': event,
            'cross_scene': cross, 'x': x, 'y': y, 'name_id': name,
            'order': order, 'source_revision': 1275,
            'scaled_xy': ([x * info['pos_x_ratio'], y * info['pos_y_ratio']]
                          if info else None),
            'can_send_packets': False,
        })
    return result


def parse_binary_links(raw, stages):
    """6 UInt16 per DoorLinkData.NewDoorLinkData; source and target are scenes."""
    count = _rows(raw, 12, 100000)
    result = {}
    for i in range(count):
        stage, x, y, target, tx, ty = struct.unpack_from(
            '<HHHHHH', raw, 4 + i * 12)
        if not stage or not target:
            raise Topology1275Error('1275 門連結場景 ID 無效')
        src, dst = stages.get(stage), stages.get(target)
        result.setdefault(stage, []).append({
            'scene': stage, 'destination': target,
            'source_xy': [x, y], 'destination_xy': [tx, ty],
            'source_scaled_xy': ([x * src['pos_x_ratio'], y * src['pos_y_ratio']]
                                 if src else None),
            'destination_scaled_xy': ([tx * dst['pos_x_ratio'], ty * dst['pos_y_ratio']]
                                      if dst else None),
            'kind': 'binary_door_link', 'source_revision': 1275,
            'can_send_packets': False,
        })
    return result


_HEADER = re.compile(r'^\[事件ID\]=(\d+)$')
_LINK = re.compile(
    r'^原場景位置\[X:\s*(\d+),Y:\s*(\d+)\]\s*'
    r'目標場景:\[(\d+)\],位置\[X:\s*(\d+),Y:\s*(\d+)\]$')


def parse_eve_links(raw, stages):
    """The real 1275 EveDoorLinks UTF-16 file, not cached 1262 portals.json."""
    if type(raw) is not bytes:
        raise Topology1275Error('1275 EveDoorLinks 類型無效')
    try:
        text = raw.decode('utf-16')
    except UnicodeError as exc:
        raise Topology1275Error('1275 EveDoorLinks 編碼錯誤') from exc
    result, stage = {}, None
    for lineno, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        match = _HEADER.fullmatch(line)
        if match:
            stage = int(match[1])
            if not stage or stage in result:
                raise Topology1275Error('1275 門事件場景表頭無效／重複')
            result[stage] = []
            continue
        match = _LINK.fullmatch(line)
        if match is None or stage is None:
            raise Topology1275Error('1275 門事件連結第 %d 行格式錯誤' % lineno)
        x, y, target, tx, ty = map(int, match.groups())
        if not 0 < target <= 65535:
            raise Topology1275Error('1275 門連結目的地無效')
        src, dst = stages.get(stage), stages.get(target)
        result[stage].append({
            'scene': stage, 'destination': target,
            'source_xy': [x, y], 'destination_xy': [tx, ty],
            'source_scaled_xy': ([x * src['pos_x_ratio'], y * src['pos_y_ratio']]
                                 if src else None),
            'destination_scaled_xy': ([tx * dst['pos_x_ratio'], ty * dst['pos_y_ratio']]
                                      if dst else None),
            'kind': 'eve_door_link', 'source_revision': 1275,
            'can_send_packets': False,
        })
    if not result or not any(result.values()):
        raise Topology1275Error('1275 EveDoorLinks 沒有連結')
    return result


def build_topology(stages, raw_markers, raw_binary_links, raw_eve_links):
    """Only call after DataCatalog ZIP manifest and files are verified."""
    if not isinstance(stages, dict) or not stages:
        raise Topology1275Error('缺少已驗證的1275場景幾何來源')
    markers = parse_stage_markers(raw_markers, stages)
    binary = parse_binary_links(raw_binary_links, stages)
    eve = parse_eve_links(raw_eve_links, stages)
    return {
        'source_revision': 1275, 'stages': stages,
        'markers': markers, 'binary_links': binary, 'eve_links': eve,
        'navmesh_verified': False, 'portal_trigger_verified': False,
        'network_coordinates_verified': False, 'can_send_packets': False,
        'counts': {
            'stages': len(stages),
            'markers': sum(map(len, markers.values())),
            'binary_links': sum(map(len, binary.values())),
            'eve_links': sum(map(len, eve.values())),
        },
    }


def packet_to_world_xz(stage, x, y):
    """Stage.TransferPosition conversion in world meters, not A* graph Int3."""
    import math
    if any(type(v) not in (int, float) or not math.isfinite(v) or
           not 0 <= v <= 65535 for v in (x, y)):
        raise Topology1275Error('1275 封包座標不合法')
    return (x * .01, (stage['offset_y'] - y) * .01)


def world_to_packet_xy(stage, x, z):
    import math
    if any(type(v) not in (int, float) or not math.isfinite(v)
           for v in (x, z)):
        raise Topology1275Error('1275 世界座標不合法')
    packet = (x * 100, stage['offset_y'] - z * 100)
    if not all(0 <= v <= 65535 for v in packet):
        raise Topology1275Error('1275 世界座標超出封包範圍')
    return packet


def read_only_route(topology, start, goal, *, max_hops=40):
    """Breadth-first stage *reference*, not a valid movement route or trigger."""
    if (topology.get('source_revision') != 1275 or
            topology.get('can_send_packets') is not False or
            type(start) is not int or type(goal) is not int or
            type(max_hops) is not int or not 1 <= max_hops <= 100):
        raise Topology1275Error('1275 路線請求不合法')
    stages = topology['stages']
    if start not in stages or goal not in stages:
        raise Topology1275Error('1275 起終點場景未列於官方表')
    if not stages[start]['is_open'] or not stages[goal]['is_open']:
        raise Topology1275Error('1275 場景官方開放旗標為關閉，不可規劃')
    previous, queue = {start: None}, deque([start])
    while queue:
        current = queue.popleft()
        if current == goal:
            break
        chain = []
        node = current
        while node is not None:
            chain.append(node)
            node = previous[node]
        if len(chain) > max_hops:
            continue
        for key in ('binary_links', 'eve_links'):
            for link in topology[key].get(current, ()):
                destination = link['destination']
                if (destination in stages and stages[destination]['is_open']
                        and destination not in previous):
                    previous[destination] = current
                    queue.append(destination)
    if goal not in previous:
        return {'source_revision': 1275, 'start': start, 'goal': goal,
                'found': False, 'stages': [], 'can_send_packets': False,
                'reason': '無可核對的1275場景連結路徑'}
    result = []
    node = goal
    while node is not None:
        result.append(node)
        node = previous[node]
    result.reverse()
    return {'source_revision': 1275, 'start': start, 'goal': goal,
            'found': True, 'stages': result,
            'can_send_packets': False, 'navmesh_verified': False,
            'reason': '唯讀場景拓樸，尚未驗證路徑網格、門觸發或伺服器條件'}
