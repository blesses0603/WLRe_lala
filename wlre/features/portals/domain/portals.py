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
                # 1275 doors are parsed, but door destinations and live trigger
                # conditions have not been independently authenticated. Never
                # send an unverified 1262 C20-8 door index.
                try:
                    verified = active_runtime()
                    door_count = sum(len(v) for v in verified.doors.values())
                except ValueError:
                    # The version gate will block login until both ZIPs validate;
                    # constructing the pre-login UI must not crash.
                    door_count = 0
                self.data = {'portals': {}, 'audit': [], 'entities': {},
                             'source_revision': 1275,
                             'door_count': door_count}
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
