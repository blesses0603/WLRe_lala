"""Pinned Bangkok observations versus geometry and source-derived corner following.

This is a fixed-input Python model, not execution of Unity, native motion or Lua.
FPS/speed/sender/collision are not observed in the supplied video.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from tools.review_navigation_player_points import SOURCE_SHA
from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision
from wlre.services.world.navigation import Mesh
from wlre.services.world.navigation_database import load_cache, database_path
from wlre.services.world.navigation_preview import PreviewRepository

CATALOG='b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6'
OBSERVATIONS=((8.2,2906,3990),(8.333,2870,4021),(8.4,2853,4036),
              (8.466667,2835,4052),(8.5,2826,4060),(8.533,2818,4067),
              (8.6,2800,4083),(8.8,2756,4121))


def distance_to_polyline(point, points):
    values=[]
    for a,b in zip(points,points[1:]):
        delta=[b[i]-a[i] for i in (0,1)];den=sum(v*v for v in delta)
        t=max(0,min(1,sum((point[i]-a[i])*delta[i] for i in (0,1))/den)) if den else 0
        values.append(math.dist(point,[a[i]+t*delta[i] for i in (0,1)]))
    if not values:raise ValueError('Need a polyline')
    return min(values)


def follow(points, fps, radius):
    if fps not in (30,60,120) or radius not in (10,40):raise ValueError('Unreviewed model settings')
    position=tuple(points[0]);pending=list(points[1:]);trace=[position];switches=[]
    for frame in range(20*fps):
        if not pending:break
        target=pending[0]
        while pending and math.dist(position,target)<radius:
            if len(pending)>1:switches.append(dict(position=position,skipped_target=target))
            target=pending[1] if len(pending)>1 else pending[0]
            pending.pop(0)
        length=math.dist(position,target)
        fraction=min(1,350/fps/length) if length else 0
        position=tuple(position[i]+fraction*(target[i]-position[i]) for i in (0,1))
        trace.append(position)
    else:raise ValueError('Motion model exceeded fixed 20-second budget')
    return trace,switches


def review(snapshot, move_source):
    source=Path(move_source).read_bytes()
    if hashlib.sha256(source).hexdigest()!=SOURCE_SHA:raise ValueError('MoveController source mismatch')
    # Preserve the actual < threshold, branch constants and CharacterController call evidence.
    for text in (b'AStarNextPathDistanceSquare = 0.01;',b'AStarNextPathDistanceSquare = 0.16;',
                 b'>= AStarNextPathDistanceSquare',b'self.characterController:Move(cachedVec3);'):
        if text not in source:raise ValueError('Pinned movement evidence unavailable')
    snapshot=Path(snapshot);v=json.loads((snapshot/'current-identity.json').read_text())
    identity=OfficialCatalogIdentity(v['data_ver'],v['exe_version'],tuple(PackageRevision(**p) for p in v['packages']))
    if identity.key!=CATALOG:raise ValueError('Case is pinned to the observed historical catalog')
    stages=json.loads((snapshot/'current-stages.json').read_text());repo=PreviewRepository(identity,stages)
    if stages['12600']['map_height']!=6000:raise ValueError('Case coordinate mapping differs')
    decoded=load_cache(database_path(),identity.key,12600);plain=Mesh(decoded['mesh'])
    mesh,origin=repo.load(12600,travel_mode='land')
    route=repo.route(12600,(4836,5154),(1850,4915),download=False,travel_mode='land',smooth=True)
    points=route['packet_points_xy_float'];observations=[]
    boundaries=[]
    for face in mesh.walkable:
        tri=[((p[0]+origin[0])/10,6000-(p[2]+origin[2])/10) for p in mesh.faces[face]]
        boundaries.extend((a,b) for a,b in zip(tri,tri[1:]+tri[:1]))
    for time,x,y in OBSERVATIONS:
        node,_=plain.locate(x*10-origin[0],(6000-y)*10-origin[2]);tag=(plain.metadata[node][1]>>19)&31
        allowed=node in mesh.walkable
        observations.append(dict(time=time,xy=[x,y],node=node,tag=tag,land_allowed=allowed,
            distance_to_ideal=distance_to_polyline((x,y),points),
            distance_to_land=0 if allowed else min(distance_to_polyline((x,y),edge) for edge in boundaries)))
    models=[]
    for radius in (10,40):
        for fps in (30,60,120):
            trace,switches=follow(points,fps,radius)
            distances=[distance_to_polyline((x,y),trace) for _,x,y in OBSERVATIONS]
            models.append(dict(fps=fps,radius_packet=radius,speed_packet_per_second=350,
                distances=distances,max_distance=max(distances),mean_distance=sum(distances)/len(distances),
                switches=switches,model_final_position=trace[-1]))
    return dict(catalog_key=identity.key,move_source_sha256=SOURCE_SHA,ideal_points=points,
        observations=observations,models=models,can_send_packets=False,runtime_verified=False,
        limitations=['Spatial comparison only; video timestamps are not synchronized to model frames.',
                     'Fixed sensitivity cases, not a fitted or measured FPS/speed/sender.',
                     'No CharacterController collisions, gravity or actual vectorPath observation.',
                     'Native full-graph harness bound is 256 nodes; Bangkok has 513, not run here.'])


def native_corridor(snapshot, il2cpp, unity):
    """Pinned native Apply on the supplied 24-face corridor, not graph search."""
    from tools.review_navigation_funnel_apply import oracle
    v=json.loads((Path(snapshot)/'current-identity.json').read_text())
    identity=OfficialCatalogIdentity(v['data_ver'],v['exe_version'],tuple(PackageRevision(**p) for p in v['packages']))
    if identity.key!=CATALOG:raise ValueError('Unexpected native-case catalog')
    repo=PreviewRepository(identity,json.loads((Path(snapshot)/'current-stages.json').read_text()))
    route=repo.route(12600,(4836,5154),(1850,4915),download=False,smooth=True)
    decoded=load_cache(database_path(),identity.key,12600);tile=decoded['mesh']['tiles'][0]
    ids=route['faces'];mapping={n:j for j,n in enumerate(ids)}
    vertices_used=sorted({v for n in ids for v in tile['triangles'][n]})
    remap={v:j for j,v in enumerate(vertices_used)}
    vertices=[tile['vertices_a_int3'][v] for v in vertices_used]
    faces=[[remap[v] for v in tile['triangles'][n]] for n in ids]
    connections=[[(mapping[t],cost,edge) for t,cost,edge in decoded['connections'][n] if t in mapping] for n in ids]
    result=oracle(il2cpp,unity)(vertices,faces,connections,list(range(len(ids))),
                              [[48.36,10,8.46],[18.5,10,10.85]],split=False)
    points=[[p[0]*100,6000-p[2]*100] for p in result['vector_path']]
    expected=route['packet_points_xy_float']
    if len(points)!=len(expected):raise AssertionError('Native corner count differs')
    error=max(math.dist(a,b) for a,b in zip(points,expected))
    if error>0.001:raise AssertionError('Native corridor funnel differs from planar result')
    return dict(supplied_corridor_faces=ids,vertices=len(vertices),packet_xy=points,
                max_packet_error=error,whole_graph_search_verified=False,
                runtime_verified=False,can_send_packets=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--move-source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--libil2cpp',type=Path);p.add_argument('--libunity',type=Path);a=p.parse_args()
    if bool(a.libil2cpp)!=bool(a.libunity):p.error('Provide both native libraries')
    result=review(a.snapshot,a.move_source)
    if a.libil2cpp:result['native_corridor']=native_corridor(a.snapshot,a.libil2cpp,a.libunity)
    a.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(observations=result['observations'],models=[{k:m[k] for k in ('fps','radius_packet','max_distance')} for m in result['models']])))


if __name__=='__main__':main()
