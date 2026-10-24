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
                rows = {}
                try:
                    topology = verified.topology
                    for kind in ('binary_links', 'eve_links'):
                        for scene, links in topology[kind].items():
                            for index, link in enumerate(links, 1):
                                destination = link['destination']
                                stage = verified.stages.get(destination)
                                position = link['source_scaled_xy']
                                if stage is None or not position:
                                    continue
                                label = verified.texts.get(stage['name_id']) or str(destination)
                                rows.setdefault(str(scene), []).append({
                                    'id': f'1275:{scene}:{kind}:{index}',
                                    'scene': scene, 'index': index,
                                    'name': f'{label}（1275 唯讀）',
                                    'kind': 'link', 'destination': destination,
                                    'x': position[0], 'y': position[1],
                                    'coordinate_valid': all(
                                        type(v) is int and 0 <= v <= 65535 for v in position),
                                    'navigation_status': 'unverified_1275_navmesh',
                                    'navigation_note': '1275 A* 網格尚未驗證',
                                    'direct_eligible': False,
                                    'direct_door_index': None,
                                    'direct_note': '1275 來源只證明場景連結，未驗證門編號及伺服器條件',
                                    'transition_note': '1275 不允許觸發傳送',
                                    'source_revision': 1275,
                                })
                except (NameError, AttributeError, KeyError, TypeError):
                    # Missing/offline 1275 archives must not turn into 1262 portals.
                    rows = {}
                self.data = {'portals': rows, 'audit': [], 'entities': {},
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
