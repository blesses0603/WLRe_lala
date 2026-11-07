"""Official database route previews. Never authorizes live movement."""
import heapq
import math
from wlre.services.world.navigation import Mesh, NavigationError, finite
from wlre.services.world.navigation_database import database_path, load_cache


REVIEWED_COORDINATE_CATALOGS=frozenset({'b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6'})


class NoPreviewRoute(NavigationError):
    """Search exhausted the reviewed, mode-filtered preview graph."""
    def __init__(self, source, target, reached, travel_mode):
        super().__init__('官方連線與通行標籤沒有允許的路徑。')
        self.details = dict(source_node=source, target_node=target,
                            reachable_nodes=reached, travel_mode=travel_mode)


class PreviewMesh(Mesh):
    def __init__(self, result, *, travel_mode='land'):
        masks={'land':9,'sea':4,'sky':15}
        if travel_mode not in masks:raise NavigationError('未驗證的通行模式。')
        self.travel_mode=travel_mode
        mask=masks[travel_mode]
        super().__init__(result['mesh'])
        if len(self.faces)!=len(result['connections']):
            raise NavigationError('Degenerate official geometry requires separate review')
        # Native GraphNode.get_Walkable reads bit zero; deserialization preserves it.
        self.walkable={i for i,metadata in enumerate(self.metadata) if metadata[1]&1 and mask & (1 << ((metadata[1] >> 19) & 31))}
        self.serialized_connections=result['connections']
        for i,connections in enumerate(result['connections']):
            allowed={target for target,cost,edge in connections if target in self.walkable}
            self.adjacency[i]={target:midpoint for target,midpoint in self.adjacency[i].items()
                               if i in self.walkable and target in allowed}

    def locate(self,*args,**kwargs):
        node,point=super().locate(*args,**kwargs)
        if node not in self.walkable:raise NavigationError('Official node is not walkable')
        return node,point

    def route(self,*args,**kwargs):
        return self._route(*args,**kwargs)

    def _route(self,start,end,start_height=None,end_height=None,*,smooth=False):
        source,sp=self.locate(*start,height=start_height)
        target,tp=self.locate(*end,height=end_height)
        costs={source:0};parents={};queue=[(0,source)]
        while queue:
            cost,node=heapq.heappop(queue)
            if cost!=costs[node]:continue
            if node==target:break
            for neighbor,arc_cost,edge in self.serialized_connections[node]:
                if neighbor not in self.adjacency[node]:continue
                # Native Path.GetTraversalCost adds target node penalty and tag
                # penalty. Reviewed Seeker construction initializes tag penalties
                # to zero; custom traversal providers are not supported here.
                value=cost+arc_cost+self.metadata[neighbor][0]
                if value>0xffffffff:raise NavigationError('路徑成本超出已驗證範圍。')
                if value<costs.get(neighbor,float('inf')):
                    costs[neighbor]=value;parents[neighbor]=node
                    heapq.heappush(queue,(value,neighbor))
        else:raise NoPreviewRoute(source, target, len(costs), self.travel_mode)
        faces=[target]
        while faces[-1]!=source:faces.append(parents[faces[-1]])
        faces.reverse();points=[sp]
        for a,b in zip(faces,faces[1:]):
            midpoint=self.adjacency[a][b]
            if midpoint!=points[-1]:points.append(midpoint)
        if tp!=points[-1]:points.append(tp)
        if smooth:
            from wlre.services.world.navigation_funnel import smooth_corridor
            points=smooth_corridor([self.faces[i] for i in faces],sp,tp)
        return dict(scene_resource=self.scene_id,coordinate_space='navcache_vertices_b_int3',
                    network_coordinates_verified=False,connectivity='official_serialized_connections',
                    runtime_obstacles_applied=False,original_node_flags_applied=False,
                    original_walkability_applied=True,original_tags_applied=True,
                    travel_mode=self.travel_mode,serialized_costs_applied=True,
                    cost=costs[target],cost_policy='arcs_plus_target_penalties_zero_tag_penalties',
                    smoothing_applied=bool(smooth),points=points,faces=faces,
                    length=sum(math.dist(a,b) for a,b in zip(points,points[1:])),
                    can_send_packets=False,live_movement_verified=False,
                    navigation_source='official_versioned_database_preview')


class PreviewRepository:
    """Exact runtime version only; fetching is explicit per selected model."""
    def __init__(self,identity,stages,*,root=None):
        self.identity=identity
        self.stages={int(k):dict(v) for k,v in stages.items()}
        self.root=root

    def load(self,model,*,download=False,travel_mode='land'):
        model=int(str(model).removeprefix('M'))
        from wlre.services.world.house_navigation import require_general_navigation
        require_general_navigation(model=model)
        if download:
            from wlre.services.world.navigation_sync import sync_model
            sync_model(self.identity,model,root=self.root)
        result=load_cache(database_path(self.root),self.identity.key,model)
        if result is None:raise NavigationError('此版本官方導航尚未同步，未使用舊版幾何。')
        mesh=PreviewMesh(result,travel_mode=travel_mode);mesh.scene_id=f'M{model:05d}'
        return mesh,result['origin']

    def route(self,logical_map,start,end,*,download=False,start_height=None,end_height=None,navigation_state=None,travel_mode='land',smooth=False):
        if self.identity.key not in REVIEWED_COORDINATE_CATALOGS:
            raise NavigationError('此版本的官方座標邏輯尚未完成驗證。')
        logical_map=int(logical_map)
        from wlre.services.world.house_navigation import require_general_navigation
        require_general_navigation(scene=logical_map)
        state=navigation_state or {}
        if state.get('scene')==logical_map and state.get('stale'):
            raise NavigationError('場景障礙已變更，尚未完成官方動態幾何重建。')
        stage_id=logical_map
        stage=self.stages.get(stage_id)
        if stage is None and 61501<=logical_map<=62000:
            from wlre.services.world.house_navigation import instance_aliases
            stage_id=instance_aliases(self.stages).get(logical_map)
            stage=self.stages.get(stage_id)
        if stage is None:raise NavigationError('官方場景表沒有此 ID；副本別名尚未確認。')
        mesh,origin=self.load(stage['model_id'],download=download,travel_mode=travel_mode)
        height=stage['map_height']
        if type(height) is not int or not 0<=height<=65535:raise NavigationError('無效的官方場景高度')
        offset=6992 if height==65535 else height
        def convert(point):
            finite(*point)
            return float(point[0])*10-origin[0],(offset-float(point[1]))*10-origin[2]
        result=mesh.route(convert(start),convert(end),start_height,end_height,smooth=smooth)
        result.update(logical_map=int(logical_map),catalog_key=self.identity.key,
                      source_label='官方資料 '+getattr(self.identity,'data_ver','（已校驗）'),
                      packet_points_xy_float=[[(p[0]+origin[0])/10,offset-(p[2]+origin[2])/10] for p in result['points']])
        return result
