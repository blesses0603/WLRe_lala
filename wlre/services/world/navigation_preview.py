"""Official database route previews. Never authorizes live movement."""
from wlre.services.world.navigation import Mesh, NavigationError, finite
from wlre.services.world.navigation_database import database_path, load_cache


REVIEWED_COORDINATE_CATALOGS=frozenset({'b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6'})


class PreviewMesh(Mesh):
    def __init__(self, result):
        super().__init__(result['mesh'])
        if len(self.faces)!=len(result['connections']):
            raise NavigationError('Degenerate official geometry requires separate review')
        # Native GraphNode.get_Walkable reads bit zero; deserialization preserves it.
        self.walkable={i for i,metadata in enumerate(self.metadata) if metadata[1]&1}
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
        result=super().route(*args,**kwargs)
        result.update(connectivity='official_serialized_connections',
                      original_walkability_applied=True,serialized_costs_applied=False,
                      can_send_packets=False,live_movement_verified=False,
                      navigation_source='official_versioned_database_preview')
        return result


class PreviewRepository:
    """Exact runtime version only; fetching is explicit per selected model."""
    def __init__(self,identity,stages,*,root=None):
        self.identity=identity
        self.stages={int(k):dict(v) for k,v in stages.items()}
        self.root=root

    def load(self,model,*,download=False):
        model=int(str(model).removeprefix('M'))
        if download:
            from wlre.services.world.navigation_sync import sync_model
            sync_model(self.identity,model,root=self.root)
        result=load_cache(database_path(self.root),self.identity.key,model)
        if result is None:raise NavigationError('此版本官方導航尚未同步，未使用舊版幾何。')
        mesh=PreviewMesh(result);mesh.scene_id=f'M{model:05d}'
        return mesh,result['origin']

    def route(self,logical_map,start,end,*,download=False,start_height=None,end_height=None):
        if self.identity.key not in REVIEWED_COORDINATE_CATALOGS:
            raise NavigationError('此版本的官方座標邏輯尚未完成驗證。')
        stage=self.stages.get(int(logical_map))
        # Dynamic player houses require Room.floorSize/floorIndex. Do not guess.
        if stage is None:raise NavigationError('官方場景表沒有此 ID；動態房屋須先確認樓層模型。')
        mesh,origin=self.load(stage['model_id'],download=download)
        height=stage['map_height']
        if type(height) is not int or not 0<=height<=65535:raise NavigationError('無效的官方場景高度')
        offset=6992 if height==65535 else height
        def convert(point):
            finite(*point)
            return float(point[0])*10-origin[0],(offset-float(point[1]))*10-origin[2]
        result=mesh.route(convert(start),convert(end),start_height,end_height)
        result.update(logical_map=int(logical_map),catalog_key=self.identity.key,
                      packet_points_xy_float=[[(p[0]+origin[0])/10,offset-(p[2]+origin[2])/10] for p in result['points']])
        return result
