"""Bounded static official-land adapter; not live-server or dynamic-collision proof.

The preview remains explicitly unverified. A consumer may accept this adapter's
checked execution contract, never a boolean copied into an arbitrary route.
"""
import copy
import math
from wlre.services.world.dynamic_bundle_runtime import current_runtime
from wlre.services.world.house_navigation import require_general_navigation
from wlre.services.world.navigation import NavigationError, finite
from wlre.services.world.navigation_funnel import covered, area, EPS
from wlre.services.world import navigation_preview

MAX_CORRIDOR_FACES = 512
MAX_ROUTE_POINTS = 1024
MAX_MESH_FACES = 10000
MAX_GEOMETRY_CHECKS = 2_000_000


def _point(value):
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise NavigationError('無效的官方導航三維座標。')
    finite(*value)
    return tuple(float(v) for v in value)


def _overlap(a, b, triangle):
    """Closed segment/triangle clipping, including intersections inside a step."""
    orientation = 1 if area(*triangle) > 0 else -1
    lo, hi = 0., 1.
    for p, q in zip(triangle, triangle[1:] + triangle[:1]):
        start = orientation * area(p, q, a)
        end = orientation * area(p, q, b)
        if start < -EPS and end < -EPS:
            return None
        delta = end - start
        if delta > EPS:
            lo = max(lo, (-EPS - start) / delta)
        elif delta < -EPS:
            hi = min(hi, (-EPS - start) / delta)
        if lo > hi + EPS:
            return None
    return max(0., lo), min(1., hi)


def _surface_height(point, triangle):
    a, b, c = triangle
    total = area(a, b, c)
    u, v = area(point, b, c) / total, area(a, point, c) / total
    return u * a[1] + v * b[1] + (1 - u - v) * c[1]


class OfficialMovementAdapter:
    """Exact current official DB only, land tags, flat unambiguous corridors.

    No download, historical seed, game transport or movement authority flags.
    The caller still owns state changes, step budgets and server corrections.
    """
    def __init__(self, runtime_getter=current_runtime, root=None):
        self.runtime_getter = runtime_getter
        self.runtime = runtime_getter()
        if self.runtime is None:
            raise NavigationError('目前官方 Runtime 尚未就緒，不能規劃移動。')
        self.identity = copy.deepcopy(self.runtime.catalog_identity)
        self.stages = copy.deepcopy(self.runtime.stages)
        if self.identity.key not in navigation_preview.REVIEWED_COORDINATE_CATALOGS:
            raise NavigationError('此版本官方座標尚未完成格式核對。')
        self.repository = navigation_preview.PreviewRepository(self.identity, self.stages, root=root)
        self._models = {}
        self._route = self._route_snapshot = None
        self._mesh = self._corridor = self._height = None
        self._corridor_ids = ()
        self._navigation = self._navigation_snapshot = None
        self._require_current()

    def is_current(self):
        current = self.runtime_getter()
        return (current is self.runtime and current is not None
                and current.catalog_identity == self.identity
                and current.stages == self.stages)

    def _require_current(self):
        if not self.is_current():
            raise NavigationError('規劃途中官方來源已變更，請重新規劃。')
        if self._navigation is not None:
            if self._navigation.get('stale') or self._navigation != self._navigation_snapshot:
                raise NavigationError('場景障礙或導航狀態已改變，停止舊路徑。')

    def _stage(self, scene):
        self._require_current()
        if type(scene) is not int:
            raise NavigationError('官方場景 ID 必須是整數。')
        require_general_navigation(scene=scene)
        stage = self.stages.get(scene)
        if not isinstance(stage, dict) or type(stage.get('model_id')) is not int:
            raise NavigationError('官方場景表沒有此 ID，不使用歷史對應。')
        require_general_navigation(model=stage['model_id'])
        height = stage.get('map_height')
        if type(height) is not int or not 1 <= height <= 65535:
            raise NavigationError('無效的官方場景高度。')
        return {**stage, 'offset_y': 6992 if height == 65535 else height}

    def _load(self, model, *, refresh=False):
        if refresh or model not in self._models:
            self._models[model] = self.repository.load(model, download=False, travel_mode='land')
        self._require_current()
        mesh, _origin = self._models[model]
        if len(mesh.faces) > MAX_MESH_FACES:
            raise NavigationError('官方移動網格超出有界面數配額。')
        return self._models[model]

    def mapping(self, scene):
        stage = self._stage(scene)
        mesh, origin = self._load(stage['model_id'])
        return stage, mesh.scene_id, tuple(origin)

    def to_navigation(self, scene, x, y):
        finite(x, y)
        if not 0 <= x <= 65535 or not 0 <= y <= 65535:
            raise NavigationError('目的地超出 UInt16 座標範圍。')
        stage, _, origin = self.mapping(scene)
        return float(x) * 10 - origin[0], (stage['offset_y'] - float(y)) * 10 - origin[2]

    def to_packet(self, scene, x, z):
        finite(x, z)
        stage, _, origin = self.mapping(scene)
        return (float(x) + origin[0]) / 10, stage['offset_y'] - (float(z) + origin[2]) / 10

    def route(self, repository_ignored, scene, start, end, start_height=None,
              end_height=None, navigation_state=None):
        # Any failed/repeated request invalidates the prior execution contract.
        self._route = self._route_snapshot = None
        self._mesh = self._corridor = self._height = None
        self._corridor_ids = ()
        self._navigation = self._navigation_snapshot = None
        self._require_current()
        if navigation_state is not None:
            if not isinstance(navigation_state, dict):
                raise NavigationError('無效的場景導航狀態。')
            if navigation_state.get('stale') or navigation_state.get('scene', scene) != scene:
                raise NavigationError('場景障礙或導航狀態不明，不能規劃。')
            self._navigation = navigation_state
            self._navigation_snapshot = copy.deepcopy(navigation_state)
        stage = self._stage(scene)
        mesh, origin = self._load(stage['model_id'], refresh=True)
        # Intentionally do not use supplied heights to choose an ambiguous floor.
        sp, ep = self.to_navigation(scene, *start), self.to_navigation(scene, *end)
        first, point_a = mesh.locate(*sp)
        last, point_b = mesh.locate(*ep)
        for supplied, actual in ((start_height, point_a[1]), (end_height, point_b[1])):
            if supplied is not None:
                finite(supplied)
                if abs(supplied - actual) > EPS:
                    raise NavigationError('已知高度與官方導航平面不同。')
        result = mesh.route(sp, ep, smooth=False)
        ids = result['faces']
        if not ids or len(ids) > MAX_CORRIDOR_FACES or len(result['points']) > MAX_ROUTE_POINTS:
            raise NavigationError('官方移動走廊超出有界上限。')
        if (len(result['points']) + 1) * len(mesh.faces) > MAX_GEOMETRY_CHECKS:
            raise NavigationError('官方移動幾何檢查超出有界運算配額。')
        if any(type(i) is not int or i not in mesh.walkable for i in ids):
            raise NavigationError('官方走廊包含不可步行節點。')
        corridor = [mesh.faces[i] for i in ids]
        heights = [v[1] for tri in corridor for v in tri]
        if max(heights) - min(heights) > EPS:
            raise NavigationError('目前僅支援平面陸地，坡面需要另外處理。')
        self._mesh, self._corridor, self._height = mesh, corridor, heights[0]
        self._corridor_ids = tuple(ids)
        try:
            points = [_point(p) for p in result['points']]
            # Point-only queries still require no overlapping floor.
            self._check_segment(points[0], points[0])
            for a, b in zip(points, points[1:]):
                self._check_segment(a, b)
            result.update(logical_map=scene, catalog_key=self.identity.key,
                          execution_policy='bounded_official_land',
                          static_corridor_contained=True, runtime_obstacles_applied=False,
                          live_movement_verified=False, can_send_packets=False,
                          packet_points_xy_float=[list(self.to_packet(scene, p[0], p[2])) for p in points])
            self._require_current()
        except Exception:
            self._mesh = self._corridor = self._height = None
            self._corridor_ids = ()
            raise
        self._route = result
        self._route_snapshot = copy.deepcopy(result)
        return result

    def validate_route(self, route):
        self._require_current()
        if self._route is None or route is not self._route or route != self._route_snapshot:
            raise NavigationError('路徑不是本次官方校驗結果或已被修改。')
        if route.get('can_send_packets') is not False or route.get('live_movement_verified') is not False:
            raise NavigationError('官方路徑不可冒充正式服驗證。')
        return True

    def _check_segment(self, start, end):
        a, b = _point(start), _point(end)
        if self._mesh is None or self._corridor is None:
            raise NavigationError('尚無已校驗的官方移動走廊。')
        if abs(a[1] - self._height) > EPS or abs(b[1] - self._height) > EPS:
            raise NavigationError('移動步驟離開官方平面。')
        if not covered(a, b, self._corridor):
            raise NavigationError('移動步驟離開官方可步行走廊。')
        if not self._directed_segment(a, b):
            raise NavigationError('移動步驟跨越未允許的官方連線方向。')
        # Look for another floor along the whole step, not only its endpoints.
        # This deliberately includes blocked triangles: a different height is
        # not evidence that the server selected this floor.
        for triangle in self._mesh.faces:
            overlap = _overlap(a, b, triangle)
            if overlap is None:
                continue
            for fraction in overlap:
                point = tuple(x + (y - x) * fraction for x, y in zip(a, b))
                if abs(_surface_height(point, triangle) - self._height) > EPS:
                    raise NavigationError('移動走廊有多層高度歧義，不能自行選樓層。')
        return True

    def _directed_segment(self, a, b):
        """Trace increasing segment parameters through allowed directed portals."""
        intervals = {i: overlap for i in self._corridor_ids
                     if (overlap := _overlap(a, b, self._mesh.faces[i])) is not None}
        reached = {i: 0. for i, (lo, hi) in intervals.items() if lo <= EPS and hi >= 0}
        pending = list(reached)
        while pending:
            node = pending.pop()
            entered = reached[node]
            lo, hi = intervals[node]
            if hi >= 1 - EPS:
                return True
            for neighbor in self._mesh.adjacency[node]:
                if neighbor not in intervals:
                    continue
                other_lo, other_hi = intervals[neighbor]
                transition = max(entered, lo, other_lo, 0.)
                if transition > min(hi, other_hi) + EPS:
                    continue
                if transition + EPS < reached.get(neighbor, float('inf')):
                    reached[neighbor] = transition
                    pending.append(neighbor)
        return False

    def validate_step(self, start_xyz, end_xyz):
        self._require_current()
        self.validate_route(self._route)
        return self._check_segment(start_xyz, end_xyz)
