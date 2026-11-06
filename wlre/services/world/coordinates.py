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
        base = RESOURCE_ROOT
        from wlre.storage.bundled_database import load_bundled_json
        self.stages = load_bundled_json('stage_coordinates.json', root=base)['stages']
        self.origins = load_bundled_json('graph_origins.json', root=base)

    def mapping(self, logical_map):
        try:
            stage = self.stages[str(parse_map_id(logical_map))]
        except (KeyError,TypeError,ValueError):
            raise NavigationError('地圖表沒有這個邏輯地圖 ID。')
        from wlre.services.world.dynamic_bundle_runtime import current_runtime, dynamic_attempted
        runtime=current_runtime()
        if runtime is not None:
            current=runtime.stages.get(parse_map_id(logical_map))
            if not isinstance(current,dict):
                raise NavigationError('目前官方資料沒有此場景，無法規劃移動。')
            fields=('model_id','map_width','map_height','small_offset_x','small_offset_y')
            if any(current.get(key)!=stage.get(key) for key in fields):
                raise NavigationError('官方場景與資料庫導航的模型／尺寸不一致，請更新導航資料。')
            stage={**current,'offset_y':stage['offset_y']}
        elif dynamic_attempted():
            raise NavigationError('目前官方 Runtime 尚未就緒，請先完成資料同步。')
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
        from wlre.services.world.house_navigation import require_general_navigation
        require_general_navigation(scene=parse_map_id(logical_map))
        stage,scene,_ = self.mapping(logical_map)
        require_general_navigation(model=stage['model_id'])
        mesh = repository.load(scene)
        result = mesh.route(self.to_navigation(logical_map,*start),self.to_navigation(logical_map,*end),
                            start_height,end_height)
        result['logical_map'] = parse_map_id(logical_map)
        result['navigation_source'] = 'database_geometry_scene_matched'
        result['map_label'] = map_label(logical_map)
        result['packet_points_xy_float'] = [self.to_packet(logical_map,p[0],p[2]) for p in result['points']]
        result['coordinate_formula_source_checked'] = True
        result['map_height'] = stage['map_height']
        result['live_movement_verified'] = False
        # Keep the v0.3 flag false: a source/capture check is not a live movement test.
        return result
