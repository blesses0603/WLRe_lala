"""Full M12050 same-VM Prepare/GetNearest/Area/search; bounded offline fixture."""
import argparse
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path
from tools.review_navigation_prepare import oracle
from tools.review_navigation_corner_following import CATALOG
from wlre.services.world.navigation_database import load_cache,database_path,REVIEWED_MODELS


def trace_empty_mode(path,limit=1000000):
    """Bounded instruction witness on the same full geometry; not elapsed-time proof."""
    from unicorn import UC_HOOK_CODE
    from tools.review_navigation_nearest import oracle as nearest
    decoded=load_cache(database_path(),CATALOG,12050);tile=decoded['mesh']['tiles'][0]
    state={};call=nearest(path,capacity=1024,_state=state,_outer_instruction_limit=limit)
    active=[False];instructions=[0];vertex_calls=[0]
    def hook(vm,address,size,user):
        if address==0x1a7a794:active[0]=True
        if active[0]:
            instructions[0]+=1
            if address==0x27a12ec:vertex_calls[0]+=1
    state['vm'].hook_add(UC_HOOK_CODE,hook)
    try:
        output=call(tile['vertices_a_int3'],tile['triangles'],[19.037,10,15.2436666667],outer=True,full_search=True,
                    node_flags=[f for _,f in tile['node_metadata']],tag_mask=4)
        if output['node'] is not None:raise AssertionError('Empty mode returned a node')
        result=dict(status='completed_no_candidate',output=output)
    except ValueError as error:result=dict(status='failed',error=str(error))
    return dict(**result,budget=limit,instructions=instructions[0],vertex_calls=vertex_calls[0],can_send_packets=False)


def review(path,cache,*,evaluator=None):
    started=time.monotonic();raw=Path(cache).read_bytes()
    if len(raw)>32*1024*1024 or hashlib.sha256(raw).hexdigest()!=REVIEWED_MODELS[12050]:raise ValueError('Unreviewed official cache')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:settings=json.loads(z.read('graph0.json'))
    decoded=load_cache(database_path(),CATALOG,12050);tile=decoded['mesh']['tiles'][0]
    if len(tile['triangles'])!=844 or settings['nearestSearchOnlyXZ']:raise ValueError('Unexpected graph profile')
    call=evaluator if evaluator is not None else oracle(path,capacity=1024)
    base=dict(vertices=tile['vertices_a_int3'],faces=tile['triangles'],
        connections=[[[n,c] for n,c,e in row] for row in decoded['connections']],
        flags=[f for p,f in tile['node_metadata']],penalties=[p for p,f in tile['node_metadata']],
        origin=[v/1000 for v in decoded['origin']],cell_size=settings['cellSize'],tile_cells=(settings['tileSizeX'],settings['tileSizeZ']))
    def point(face,dy):
        p=[sum(base['vertices'][j][i] for j in base['faces'][face])/3000 for i in range(3)]
        return [p[0]+.037,p[1]+dy,p[2]-.023]
    cases=[]
    for mode,mask,pairs in (('land',9,[(43,438),(43,794),(438,43),(438,794),(794,43),(794,438)]),
                            ('sky',15,[(0,843),(422,843),(843,0),(843,422)])):
        for a,b in pairs:cases.append(dict(name=f'{mode}_{a}_{b}',mode=mode,tag_mask=mask,start_point=point(a,2),end_point=point(b,-2)))
    cases.extend([dict(name='vertex_to_outside',mode='land',tag_mask=9,start_point=[v/1000 for v in base['vertices'][0]],end_point=[-1,12,-1]),
                  dict(name='offcenter_to_far',mode='land',tag_mask=9,start_point=point(43,.0003),end_point=[100,30,100]),
                  dict(name='empty_sea',mode='sea',tag_mask=4,start_point=point(43,2),end_point=point(794,-2)),
                  dict(name='empty_mask',mode='none',tag_mask=0,start_point=point(43,2),end_point=point(794,-2)),
                  dict(name='disabled_walkability',mode='negative_control',tag_mask=9,start_point=point(43,2),end_point=point(794,-2)),
                  dict(name='disconnected_edges',mode='negative_control',tag_mask=15,start_point=point(43,2),end_point=point(794,-2))])
    rows=[]
    for case in cases:
        fixture={**base,**{k:case[k] for k in ('start_point','end_point','tag_mask')}}
        if case['name']=='disabled_walkability':fixture['flags']=[f&~1 for f in base['flags']]
        if case['name']=='disconnected_edges':fixture['connections']=[[] for _ in base['connections']]
        result=call(**fixture)
        failed=case['name'] in ('empty_sea','empty_mask','disabled_walkability')
        if failed and (result['status']!='native_no_route_error_boundary' or result.get('prepare_completed') is not False):raise AssertionError('Expected native Prepare failure')
        if not failed and result['status']!='complete_prepared_search':raise AssertionError('Unexpected Prepare/search failure')
        if case['name']=='disconnected_edges' and len(result['path_nodes'])!=1:raise AssertionError('Area restriction crossed disconnected components')
        rows.append(dict(input=case,result=result))
        print(json.dumps(dict(case=case['name'],status=result['status'],nodes=result.get('prepared',{}).get('nodes'))),flush=True)
    return dict(catalog_key=CATALOG,nodes=844,rows=rows,elapsed_seconds=time.monotonic()-started,
        can_send_packets=False,official_runtime_verified=False,
        limits=dict(capacity=1024,nearest_instructions=1000000,prepare_instructions=1000000,search_instructions=2000000),
        limitations=['Native hierarchy constructed in a separate VM and copied into shared Prepare/search state.',
        'Prepared objects/root order and modeled modf/clock/monitor/TLS; not client deserialization/startup.',
        'Zero heuristic/tag penalties; final Funnel/player modifier dispatch and collision not included.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('libil2cpp','cache','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();r=review(a.libil2cpp,a.cache);Path(a.output).write_text(json.dumps(r,indent=2))
    print(json.dumps({k:v for k,v in r.items() if k!='rows'}))
