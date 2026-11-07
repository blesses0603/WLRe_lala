"""Pinned M12050 supplied-corridor native Apply; NOT full-graph native search."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
from tools.review_navigation_corner_following import CATALOG
from tools.review_navigation_funnel_apply import oracle
from wlre.services.world.navigation_database import load_cache,database_path
from wlre.services.world.navigation_preview import PreviewMesh
from wlre.services.world.navigation_surface_3d import segment_on_surface


def review(il2cpp,unity):
    decoded=load_cache(database_path(),CATALOG,12050)
    if decoded is None or len(decoded['mesh']['tiles'])!=1:raise ValueError('Missing reviewed single tile')
    tile=decoded['mesh']['tiles'][0];a=tile['vertices_a_int3'];b=tile['vertices_b_int3'];origin=decoded['origin']
    if len(a)!=len(b) or any(abs(x-y-o)>1e-7 for p,q in zip(a,b) for x,y,o in zip(p,q,origin)):
        raise ValueError('A/B coordinate relation differs')
    slopes=[]
    for face in tile['triangles']:
        p,q,r=(a[i] for i in face);u=[q[i]-p[i] for i in range(3)];v=[r[i]-p[i] for i in range(3)]
        n=(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
        length=math.sqrt(sum(x*x for x in n))
        if not length:raise ValueError('Degenerate official face')
        slopes.append(math.degrees(math.acos(min(1,abs(n[1])/length))))
    native=oracle(il2cpp,unity);rows=[]
    cases={'land':[(43,438),(43,794),(438,43),(438,794),(794,43),(794,438)],
           'sky':[(0,843),(422,843),(843,0),(843,422)]}
    for mode,pairs in cases.items():
        mesh=PreviewMesh(decoded,travel_mode=mode)
        for start,end in pairs:
            sp,tp=mesh.centers[start],mesh.centers[end]
            raw=mesh.route((sp[0],sp[2]),(tp[0],tp[2]),sp[1],tp[1]);ids=raw['faces']
            mapping={n:j for j,n in enumerate(ids)};used=sorted({v for n in ids for v in tile['triangles'][n]});remap={v:j for j,v in enumerate(used)}
            if len(ids)>128 or len(used)>256:raise ValueError('Supplied corridor exceeds existing native bound')
            vertices=[a[v] for v in used];faces=[[remap[v] for v in tile['triangles'][n]] for n in ids]
            connections=[[(mapping[t],cost,edge) for t,cost,edge in decoded['connections'][n] if t in mapping] for n in ids]
            def world(p):return [(p[i]+origin[i])/1000 for i in range(3)]
            triangles=[[world(v) for v in mesh.faces[n]] for n in ids]
            fallback=[world(p) for p in raw['points']]
            if not all(segment_on_surface(x,y,triangles) for x,y in zip(fallback,fallback[1:])):
                raise AssertionError('Unsmoothed 3-D corridor fallback leaves surface')
            row=dict(mode=mode,source=start,target=end,corridor_faces=len(ids),vertices=len(used),
                     fallback_points=len(fallback),fallback_surface_verified=True,
                     fallback=dict(points_world=fallback,policy='unsmoothed_3d_portal_midpoint_preview',can_send_packets=False,live_movement_verified=False),native_profiles=[])
            for split in (False,True):
                out=native(vertices,faces,connections,list(range(len(ids))),[world(sp),world(tp)],split=split)
                path=out['vector_path'];bad=[i for i,(x,y) in enumerate(zip(path,path[1:])) if not segment_on_surface(x,y,triangles)]
                row['native_profiles'].append(dict(split=split,points=path,surface_rejected_segments=bad,
                    endpoint_error_world=max(math.dist(path[0],world(sp)),math.dist(path[-1],world(tp))),
                    can_send_packets=False))
            rows.append(row)
    return dict(catalog_key=CATALOG,model=12050,nodes=len(tile['triangles']),origin=origin,
        max_face_slope_degrees=max(slopes),height_counts=dict(Counter(p[1] for p in a)),nonflat_faces=sum(len({a[v][1] for v in f})>1 for f in tile['triangles']),
        rows=rows,can_send_packets=False,official_runtime_verified=False,
        scope=__doc__,limitations=['Python selected corridors; native subset has no full graph search authority.',
        'Prepared native VM objects/math bridge, not Unity runtime or device.',
        '3-D surface point checks do not establish actor clearance or collision.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('libil2cpp','libunity','output'):p.add_argument('--'+name,required=True)
    v=p.parse_args();r=review(v.libil2cpp,v.libunity);Path(v.output).write_text(json.dumps(r,indent=2))
    print(json.dumps({k:v for k,v in r.items() if k!='rows'}))
    print(json.dumps([dict(mode=x['mode'],source=x['source'],target=x['target'],faces=x['corridor_faces'],profiles=[dict(split=p['split'],points=len(p['points']),bad=len(p['surface_rejected_segments']),endpoint_error=p['endpoint_error_world']) for p in x['native_profiles']]) for x in r['rows']]))
