"""Versioned exits from EveDoorLinks, StageMapData and DoorLinkData."""
from wlre.paths import RESOURCE_ROOT
import json
import math
from pathlib import Path
from wlre.services.world.scene_names_1275 import source_scene_label


class Portals:
    def __init__(self,path=None):
        if path is None:
            from wlre.services.world.runtime_1275 import baseline_revision, active_runtime
            if baseline_revision() == '1275':
                # The verified 1275 Eve table includes a door index and its
                # local coordinates, but not an audited destination or proof
                # that C20-8 is safe on this server. Expose the original
                # positions as read-only map markers; NEVER reuse 1262 routes.
                source_ready = False
                doors = {}
                scene_names = {}
                door_count = 0
                try:
                    verified = active_runtime()
                    # Only names bound to this exact verified 1275 runtime are
                    # permitted. Legacy map_names.json is NOT a name fallback.
                    scene_names = getattr(verified, 'scene_names', {})
                    if not isinstance(scene_names, dict):
                        scene_names = {}
                    linked = getattr(verified, 'portal_destinations', {})
                    if not isinstance(linked, dict):
                        linked = {}
                    portal_names = getattr(verified, 'portal_names', {})
                    if not isinstance(portal_names, dict):
                        portal_names = {}
                    portal_positions = getattr(verified, 'portal_positions', {})
                    if not isinstance(portal_positions, dict):
                        portal_positions = {}
                    portal_metadata_status = getattr(
                        verified, 'portal_metadata_status', 'missing_stage_map')
                    door_count = sum(len(rows) for rows in verified.doors.values())
                    for scene, entries in verified.doors.items():
                        if (type(scene) is int and 0 <= scene <= 65535):
                            scene_id = scene
                        elif (isinstance(scene, str) and scene.isdecimal()
                              and 0 <= int(scene) <= 65535):
                            scene_id = int(scene)
                        else:
                            continue
                        scene_label = source_scene_label(scene_id, scene_names)
                        visible = []
                        for row in entries:
                            if not isinstance(row, dict):
                                continue
                            index, x, y = (row.get('index'), row.get('x'),
                                           row.get('y'))
                            if (type(index) is not int or not 0 <= index <= 65535
                                    or type(x) is not int or type(y) is not int
                                    or not 0 <= x <= 4294967295
                                    or not 0 <= y <= 4294967295):
                                continue
                            # Eve.NewDoor's common x/y are EVENT GRID data,
                            # not the position used in official UIMain
                            # _SetPortalPosition. Rendering them as packet XY
                            # previously placed portals on the wrong part of
                            # the minimap. Only EveDoorLinks + StageData ratios
                            # may supply an actionable projection.
                            position = portal_positions.get((scene_id, index))
                            if not isinstance(position, dict):
                                position = {}
                            map_x, map_y = position.get('x'), position.get('y')
                            valid_xy = (
                                position.get('position_verified') is True
                                and position.get('source_kind')
                                == '1275_eve_door_links_grid_scaled'
                                and position.get('scene') == scene_id
                                and position.get('index') == index
                                and type(map_x) is int and type(map_y) is int
                                and 0 <= map_x <= 65535 and 0 <= map_y <= 65535)
                            link = linked.get((scene_id, index), {})
                            if not isinstance(link, dict):
                                link = {}
                            destination = link.get('destination')
                            verified_target = (
                                link.get('matched_stage_map') is True
                                and link.get('destination_verified') is True
                                and link.get('trigger_verified') is False
                                and type(destination) is int
                                and 0 < destination <= 65535
                                and link.get('x') == x and link.get('y') == y)
                            destination = destination if verified_target else None
                            target_label = (source_scene_label(destination, scene_names)
                                            if verified_target else '目的地未確認')
                            # Door indices are internal event IDs, not
                            # geographical or destination names. Never present
                            # an event label as the name of a scene.
                            # Lua/UIMain first uses StageMapData.NameID and
                            # only falls back to the destination stage's name.
                            # A verified marker label is useful even when the
                            # separate EveDoorLinks route cannot be resolved.
                            official_name = portal_names.get((scene_id, index))
                            if (type(official_name) is not str
                                    or not official_name.strip()):
                                official_name = None
                            label = (official_name or
                                     f'前往 {target_label}' if verified_target
                                     else official_name or
                                     f'傳點 #{index}（官方名稱未取得）')
                            visible.append({
                                'id': f'1275:{scene_id}:{index}',
                                'scene': scene_id, 'index': index,
                                'name': label,
                                'official_name': official_name,
                                'source_scene_label': scene_label,
                                'source_scene_name_known': scene_id in scene_names,
                                'destination_label': target_label,
                                'kind': 'door',
                                'source_revision': 1275,
                                'coordinate_valid': valid_xy,
                                'coordinate_source': (
                                    'verified_eve_door_links_scaled' if valid_xy
                                    else 'unverified_event_grid'),
                                'projection_guard': (
                                    position.get('projection_guard') if valid_xy
                                    else None),
                                'x': map_x if valid_xy else None,
                                'y': map_y if valid_xy else None,
                                'event_grid_x': x,
                                'event_grid_y': y,
                                'event_ids': tuple(row.get('event_ids') or ()),
                                'destination': destination,
                                'destination_verified': verified_target,
                                'direct_eligible': bool(verified_target and valid_xy and 1 <= index <= 65535),
                                'direct_door_index': index if verified_target and valid_xy and 1 <= index <= 65535 else None,
                                'door_index': index if verified_target and valid_xy and 1 <= index <= 65535 else None,
                                'navigation_status': 'unverified',
                                'direct_note': (
                                    '1275 門編號／位置／目的地已交叉核對；可在手動確認後單次試傳，'
                                    '成功與否完全以伺服器回覆為準'
                                    if verified_target else
                                    '1275 傳點資料可列出，但來源格座標不可直接'
                                    '當成小地圖點位；需官方門連線和場景倍率核對，'
                                    '未驗證時不畫點也不送出換圖封包'),
                            })
                        doors[str(scene_id)] = visible
                    source_ready = True
                except ValueError:
                    # During pre-login, verified files may not yet be installed.
                    # Retry from the UI when the map/scene is next refreshed.
                    pass
                self.data = {
                    'portals': doors, 'audit': [], 'entities': {},
                    'source_revision': 1275,
                    'door_count': door_count,
                    'scene_names': scene_names,
                    'portal_metadata_status': (
                        portal_metadata_status if source_ready
                        else 'core_runtime_unavailable'),
                    'portal_name_count': sum(
                        bool(item.get('official_name')) for row in doors.values()
                        for item in row),
                    'destination_count': sum(
                        bool(item.get('destination_verified')) for row in doors.values()
                        for item in row),
                    'source_ready': source_ready,
                }
                self.audit = {}
                return
        self.data=json.loads((Path(path) if path else RESOURCE_ROOT.joinpath('portals.json')).read_text(encoding='utf8'))
        self.audit={r['scene']:r for r in self.data['audit']}

    def for_scene(self,scene):
        return self.data['portals'].get(str(scene),[])

    @staticmethod
    def label(portal):
        kind={'normal':'出口','event':'事件入口','link':'地圖連結',
              'door':'1275 傳點'}[portal['kind']]
        xy=f"({portal['x']}, {portal['y']})" if portal['coordinate_valid'] else '座標未確認'
        status='' if portal.get('navigation_status')=='endpoint_valid' else '｜無可用導航'
        return f"{portal['index']}. {portal['name']}｜{kind} {xy}{status}"

    @staticmethod
    def direct_target(portal,current_scene):
        if current_scene is None or current_scene != portal.get('scene'):
            raise ValueError('請切回角色目前地圖，才能直接觸發此出口。')
        index = portal.get('direct_door_index')
        if not portal.get('direct_eligible') or type(index) is not int or not 1 <= index <= 65535:
            raise ValueError(portal.get('direct_note','尚未確認此傳點的實際觸碰事件，未送出指令。'))
        return index

    @staticmethod
    def target(portal,current_scene):
        if current_scene!=portal['scene']:raise ValueError('請切回角色目前地圖，才能前往此傳送點。')
        if not portal['coordinate_valid']:raise ValueError('傳送點座標尚未確認。')
        if portal.get('navigation_status')!='endpoint_valid':raise ValueError(portal.get('navigation_note','此傳點沒有可用導航。'))
        points = portal.get('approach_points')
        x,y = points[0] if points else (portal['x'],portal['y'])
        return portal['scene'],x,y



def portal_map_pixel(portal, projection):
    """Only return portal position inside the matching 1024px map image.

    The verified flag represents a packet-space coordinate, not a raw
    Eve grid event. A stale/off-map marker is neither drawn nor clickable.
    """
    if not portal.get('coordinate_valid') or projection is None:
        return None
    x, y = portal.get('x'), portal.get('y')
    if (type(x) is not int or type(y) is not int
            or not 0 <= x <= 65535 or not 0 <= y <= 65535):
        return None
    expected = portal.get('projection_guard')
    if isinstance(expected, dict):
        # Do not project a 1275 position onto mismatched 1262 image geometry.
        for attr in ('rate', 'offset_x', 'offset_y', 'height'):
            value = expected.get(attr)
            actual = getattr(projection, attr, None)
            if (not isinstance(value, (int, float))
                    or not isinstance(actual, (int, float))
                    or not math.isfinite(value)
                    or not math.isfinite(actual)
                    or not math.isclose(value, actual, abs_tol=1e-6)):
                return None
    u, v = projection.packet_to_pixel(x, y)
    if not (math.isfinite(u) and math.isfinite(v)
            and 0 <= u <= 1024 and 0 <= v <= 1024):
        return None
    return (u, v)


def nearest_marker(rows,projection,screen,event_x,event_y,radius=12):
    hits=[]
    for p in rows:
        point = portal_map_pixel(p, projection)
        if point is None:
            continue
        x, y = screen(*point)
        distance=math.hypot(x-event_x,y-event_y)
        if distance<=radius:hits.append((distance,p))
    return min(hits,key=lambda h:h[0])[1] if hits else None
