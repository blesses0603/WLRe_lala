"""1262 packet XY <-> cached graph-space Int3 XZ.

Stage.lua supplies scale 0.01 and the per-map mapHeight Y inversion.
All 724 caches have zero rotation. Their paired vertex arrays independently
support A = B + (boundsCenter - boundsSize/2)*1000 (rounding <= 0.5 Int3).
Live movement and dynamic obstacle geometry are not verified by these formulas.
"""
from wlre.paths import RESOURCE_ROOT
import json
from wlre.services.world.navigation import NavigationError, finite
from wlre.services.world.map_names import parse_map_id, map_label


class Coordinates:
    def __init__(self):
        from wlre.services.world.runtime_1275 import baseline_revision
        if baseline_revision() == '1275':
            self.stages = {}
            self.origins = {}
            return
        base = RESOURCE_ROOT
        self.stages = json.loads((base/'stage_coordinates.json').read_text(encoding='utf8'))['stages']
        self.origins = json.loads((base/'graph_origins.json').read_text(encoding='utf8'))

    def mapping(self, logical_map):
        from wlre.services.world.runtime_1275 import baseline_revision
        if baseline_revision() == '1275':
            raise NavigationError(
                '1275 已改用官方啟動快取供離線預覽；封包座標、節點連線與動態障礙尚未驗收，自動導航仍停用')
        try:
            stage = self.stages[str(parse_map_id(logical_map))]
        except (KeyError,TypeError,ValueError):
            raise NavigationError('地圖表沒有這個邏輯地圖 ID。')
        scene = 'M'+str(stage['model_id']).zfill(5)
        if scene not in self.origins:
            raise NavigationError('此地圖模型尚無已解碼的導航圖：'+scene)
        return stage,scene,self.origins[scene]

    def to_navigation(self, logical_map, x, y):
        finite(x,y)
        stage,_,origin = self.mapping(logical_map)
        return float(x)*10-origin[0], (stage['offset_y']-float(y))*10-origin[2]

    def to_packet(self, logical_map, x, z):
        finite(x,z)
        stage,_,origin = self.mapping(logical_map)
        return (float(x)+origin[0])/10, stage['offset_y']-(float(z)+origin[2])/10

    def route(self, repository, logical_map, start, end, start_height=None,end_height=None):
        stage,scene,_ = self.mapping(logical_map)
        mesh = repository.load(scene)
        result = mesh.route(self.to_navigation(logical_map,*start),self.to_navigation(logical_map,*end),
                            start_height,end_height)
        result['logical_map'] = parse_map_id(logical_map)
        result['map_label'] = map_label(logical_map)
        result['packet_points_xy_float'] = [self.to_packet(logical_map,p[0],p[2]) for p in result['points']]
        result['coordinate_formula_source_checked'] = True
        result['map_height'] = stage['map_height']
        result['live_movement_verified'] = False
        # Keep the v0.3 flag false: a source/capture check is not a live movement test.
        return result
