"""Versioned exits from EveDoorLinks, StageMapData and DoorLinkData."""
from wlre.paths import RESOURCE_ROOT
import json
import math
from pathlib import Path


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
                door_count = 0
                try:
                    verified = active_runtime()
                    door_count = sum(len(rows) for rows in verified.doors.values())
                    for scene, entries in verified.doors.items():
                        if (type(scene) is int and 0 <= scene <= 65535):
                            scene_id = scene
                        elif (isinstance(scene, str) and scene.isdecimal()
                              and 0 <= int(scene) <= 65535):
                            scene_id = int(scene)
                        else:
                            continue
                        visible = []
                        for row in entries:
                            if not isinstance(row, dict):
                                continue
                            index, x, y = (row.get('index'), row.get('x'),
                                           row.get('y'))
                            if type(index) is not int or not 0 <= index <= 65535:
                                continue
                            valid_xy = (type(x) is int and type(y) is int
                                        and 0 <= x <= 65535 and 0 <= y <= 65535)
                            visible.append({
                                'id': f'1275:{scene_id}:{index}',
                                'scene': scene_id, 'index': index,
                                'name': f'1275 門事件 #{index}',
                                'kind': 'door',
                                'source_revision': 1275,
                                'coordinate_valid': valid_xy,
                                'x': x if valid_xy else None,
                                'y': y if valid_xy else None,
                                'event_ids': tuple(row.get('event_ids') or ()),
                                'destination': None,
                                'destination_verified': False,
                                'direct_eligible': False,
                                'direct_door_index': None,
                                'door_index': None,
                                'navigation_status': 'unverified',
                                'direct_note': (
                                    '1275 官方門事件座標已讀取；目的地與觸碰條件'
                                    '尚未驗證，僅供定位，不會送出換圖封包'),
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
        kind={'normal':'出口','event':'事件入口','link':'地圖連結'}[portal['kind']]
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


def nearest_marker(rows,projection,screen,event_x,event_y,radius=12):
    hits=[]
    for p in rows:
        if not p['coordinate_valid']:continue
        x,y=screen(*projection.packet_to_pixel(p['x'],p['y']))
        distance=math.hypot(x-event_x,y-event_y)
        if distance<=radius:hits.append((distance,p))
    return min(hits,key=lambda h:h[0])[1] if hits else None
