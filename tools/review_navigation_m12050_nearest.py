"""Complete-graph native hierarchy/BBTree/GetNearest fixtures; no client startup claim."""
import argparse
import hashlib
import io
import json
import math
import time
import zipfile
from pathlib import Path
from tools.review_navigation_corner_following import CATALOG
from tools.review_navigation_groups import oracle as group_oracle
from tools.review_navigation_nearest import oracle,reference_triangle
from tools.review_navigation_outer import compare
from wlre.services.world.navigation_database import load_cache,database_path,REVIEWED_MODELS


def check_components(adjacency,walkable,out):
    allowed={i for i,w in enumerate(walkable) if w};components=[]
    while allowed:
        pending=[min(allowed)];component=set();allowed.remove(pending[0])
        while pending:
            i=pending.pop();component.add(i)
            for n in adjacency[i]:
                if n in allowed:allowed.remove(n);pending.append(n)
        components.append(component)
    actual={}
    for i,area in enumerate(out['native_node_areas']):
        if walkable[i]:actual.setdefault(area,set()).add(i)
        elif area!=0:raise AssertionError('Unwalkable node got Area')
    if 0 in actual or {frozenset(c) for c in components}!={frozenset(c) for c in actual.values()}:
        raise AssertionError('Native Area differs from independent components')
    if out['queue_remaining']!=0:raise AssertionError('Initialization queue not drained')



def capacity_controls(path):
    from tools.review_navigation_bbtree import oracle as tree
    n=1024
    rects=[[i*100,0,i*100+10,10] for i in range(n)]
    centers=[[i*100+3,0,3] for i in range(n)]
    t=tree(path,capacity=1024)(rects,centers)
    g=group_oracle(path,multiple=True,capacity=1024)([[] for _ in range(n)],[True]*n)
    if len(g['groups'])!=n or len(set(g['native_node_areas']))!=n:raise AssertionError('Truncated hierarchy')
    vertices=[];faces=[]
    for i in range(n):
        vertices.extend([[i*100,0,0],[i*100+10,0,0],[i*100,0,10]]);faces.append([3*i,3*i+1,3*i+2])
    q=oracle(path,capacity=1024)(vertices,faces,[.001,0,.001],outer=True,full_search=True)
    if q['node']!=0:raise AssertionError('Wrong full-capacity nearest node')
    return dict(tree_boxes=len(t['boxes']),tree_references=sum(x is not None for x in t['leaf_references']),groups=len(g['groups']),nearest=q)


def review(path,cache):
    started=time.monotonic();raw=Path(cache).read_bytes()
    if len(raw)>32*1024*1024 or hashlib.sha256(raw).hexdigest()!=REVIEWED_MODELS[12050]:raise ValueError('Unreviewed cache')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:settings=json.loads(z.read('graph0.json'))
    if settings['nearestSearchOnlyXZ']:raise ValueError('XZ-only setting unsupported')
    r=load_cache(database_path(),CATALOG,12050)
    if r is None or len(r['mesh']['tiles'])!=1:raise ValueError('Missing graph')
    tile=r['mesh']['tiles'][0];vertices=tile['vertices_a_int3'];faces=tile['triangles']
    if len(faces)!=844:raise ValueError('Unexpected graph size')
    adjacency=[[n for n,c,e in row] for row in r['connections']];walkable=[bool(f&1) for _,f in tile['node_metadata']]
    if any(i not in adjacency[j] for i,row in enumerate(adjacency) for j in row):raise ValueError('Directed hierarchy requires separate reference')
    groups=group_oracle(path,multiple=True,capacity=1024);hierarchy=groups(adjacency,walkable);check_components(adjacency,walkable,hierarchy)
    flags=[(old&~0x3fffe)|(new&0x3fffe) for (_,old),new in zip(tile['node_metadata'],hierarchy['flags'])]
    # Explicit negative initialization control, separate from unmodified official data.
    n=844;chain=[[j for j in (i-1,i+1) if 0<=j<n] for i in range(n)];walking=[i!=422 for i in range(n)]
    disconnected=groups(chain,walking);check_components(chain,walking,disconnected)
    query=oracle(path,capacity=1024)
    probes=[]
    for index in (43,438,794,next(i for i,f in enumerate(faces) if len({vertices[j][1] for j in f})>1)):
        center=[sum(vertices[j][k] for j in faces[index])/3000 for k in range(3)]
        for dy in (-2,.0003,2):probes.append([center[0]+.037,center[1]+dy,center[2]-.023])
    probes.extend([[x/1000 for x in vertices[0]],[-1,12,-1],[100,30,100]])
    rows=[];empty_attempted=set()
    for index,point in enumerate(probes):
        for mode,mask in (('land',9),('sea',4),('sky',15)):
            allowed=[bool(f&1 and mask&(1<<((f>>19)&31))) for f in flags]
            row=dict(probe=index,point=point,mode=mode);rows.append(row)
            if not any(allowed):
                if mode in empty_attempted:
                    row.update(status='not_run_empty_mode',reason='No eligible nodes; first native failure retained');continue
                empty_attempted.add(mode)
            try:
                output=query(vertices,faces,point,[v/1000 for v in r['origin']],outer=True,full_search=True,node_flags=flags,tag_mask=mask,
                             cell_size=settings['cellSize'],tile_cells=(settings['tileSizeX'],settings['tileSizeZ']))
                compare(vertices,faces,point,output,allowed)
                row.update(status='matched',output=output)
            except ValueError as error:row.update(status='failed',error=str(error))
        print(json.dumps(dict(probe=index,statuses=[x['status'] for x in rows[-3:]])),flush=True)
    # Distance limit must reject a distant point, without substituting a reachable target.
    point=[100,30,100]
    try:
        output=query(vertices,faces,point,outer=True,full_search=True,node_flags=flags,tag_mask=9,max_distance=.1)
        compare(vertices,faces,point,output,[False]*len(faces));limited=dict(status='matched',output=output)
    except ValueError as error:limited=dict(status='failed',error=str(error))
    # One bounded retry at the already-supported isolated 400k budget. Never
    # broaden this into shared Prepare/search pipelines or unlimited execution.
    extended=oracle(path,capacity=1024,_outer_instruction_limit=400000)
    try:
        output=extended(vertices,faces,probes[0],outer=True,full_search=True,node_flags=flags,tag_mask=4)
        compare(vertices,faces,probes[0],output,[False]*len(faces));empty_retry=dict(status='matched',output=output)
    except ValueError as error:empty_retry=dict(status='failed',error=str(error))
    return dict(empty_mode_400k_retry=empty_retry,catalog_key=CATALOG,nodes=844,hierarchy_groups=len(hierarchy['groups']),
        hierarchy_node_areas=hierarchy['native_node_areas'],disconnected_control_groups=len(disconnected['groups']),
        rows=rows,distance_limit_case=limited,elapsed_seconds=time.monotonic()-started,
        settings=settings,can_send_packets=False,official_runtime_verified=False,
        limitations=['Prepared native objects; grouping root order explicit, not client RecalculateAll.',
        '844-node Prepare and shared search-state integration not yet executed.',
        'Full 3-D nearest reference allows boundary ties; collision/grounding not included.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('libil2cpp','cache','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();r=review(a.libil2cpp,a.cache);Path(a.output).write_text(json.dumps(r,indent=2))
    print(json.dumps(dict(nodes=r['nodes'],groups=r['hierarchy_groups'],matched=sum(x['status']=='matched' for x in r['rows']),failed=[x for x in r['rows'] if x['status']!='matched'],limit=r['distance_limit_case'],empty_retry=r['empty_mode_400k_retry'],seconds=r['elapsed_seconds'])))
