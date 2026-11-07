"""Complete 844-node prepared ABPath search; no native Prepare or collision claim."""
import argparse
import json
import time
from pathlib import Path
from tools.review_navigation_search import oracle,compare
from tools.review_navigation_vertices import oracle as center_oracle
from tools.review_navigation_corner_following import CATALOG
from wlre.services.world.navigation_database import load_cache,database_path


def capacity_controls(path):
    small=oracle(path);large=oracle(path,capacity=1024);rows=[]
    for n in (4,256,844,1024):
        f=dict(positions=[[i*100,0,0] for i in range(n)],
            connections=[[[j,100] for j in (i-1,i+1) if 0<=j<n] for i in range(n)],
            flags=[1]*n,penalties=[0]*n,start=0,end=n-1,tag_mask=9)
        result=large(**f);compare(f,result)
        if n<=256 and result!=small(**f):raise AssertionError('Relocated arena changes existing results')
        if len(result['path_nodes'])!=n:raise AssertionError('Truncated boundary trace')
        rows.append(dict(nodes=n,status=result['status'],trace_nodes=len(result['path_nodes'])))
        if n==844:
            f['flags'][n//2]=0;blocked=large(**f);compare(f,blocked)
            if blocked['status']!='native_no_route_error_boundary':raise AssertionError('Blocked path completed')
            rows.append(dict(nodes=n,blocked=True,status=blocked['status']))
    return rows


def review(path):
    started=time.monotonic();controls=capacity_controls(path);decoded=load_cache(database_path(),CATALOG,12050)
    if decoded is None or len(decoded['mesh']['tiles'])!=1:raise ValueError('Missing complete same-version tile')
    tile=decoded['mesh']['tiles'][0]
    if len(tile['triangles'])!=844:raise ValueError('Unexpected complete graph size')
    center=center_oracle(path,modeled_center=True)
    positions=[center(tile['vertices_a_int3'],face)['center'] for face in tile['triangles']]
    flags=[f for p,f in tile['node_metadata']];penalties=[p for p,f in tile['node_metadata']]
    connections=[[[n,c] for n,c,e in row] for row in decoded['connections']]
    call=oracle(path,capacity=1024);rows=[]
    pairs={'land':[(43,438),(43,794),(438,43),(438,794),(794,43),(794,438)],
           'sky':[(0,843),(422,843),(843,0),(843,422)]}
    for mode,queries in pairs.items():
        for start,end in queries:
            fixture=dict(positions=positions,connections=connections,flags=flags,penalties=penalties,
                start=start,end=end,tag_mask={'land':9,'sky':15}[mode])
            out=call(**fixture);compare(fixture,out)
            if out['status']!='complete_prepared_search':raise ValueError('Original query did not complete')
            rows.append(dict(mode=mode,source=start,target=end,result=out))
            print(json.dumps(dict(mode=mode,source=start,target=end,path_nodes=len(out['path_nodes']),cost=out['total_cost'])),flush=True)
    return dict(catalog_key=CATALOG,nodes=len(positions),directed_edges=sum(map(len,connections)),
                sea_eligible_nodes=sum(bool(f&1 and 4&(1<<((f>>19)&31))) for f in flags),
                capacity_controls=controls,rows=rows,can_send_packets=False,official_runtime_verified=False,
                elapsed_seconds=time.monotonic()-started,scope=__doc__,
                limits=dict(node_capacity=1024,instructions_per_call=2000000,guarded_arena_bytes=1650688),
                modeled_dependencies=['finite modf','single-thread monitor','deterministic external clock'],
                limitations=['Endpoints are native node centers, supplied explicitly.',
                'No native full-graph Prepare/GetNearest/hierarchy/Area initialization.',
                'Zero heuristic/tag penalties; runtime settings and collision not verified.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--libil2cpp',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();r=review(a.libil2cpp);Path(a.output).write_text(json.dumps(r,indent=2))
    print(json.dumps({k:v for k,v in r.items() if k!='rows'}))
