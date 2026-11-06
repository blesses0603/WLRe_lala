"""Diagnostic native path pipeline for reviewed single-tile triangle maps.

Prepare/search, native edge portals and native nonplanar funnel are composed via
explicit data boundaries. Modifier registration/actor consumption
are not executed; outputs are candidate profiles, never movement authority.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile
from tools.review_navigation_prepare import oracle as prepare_oracle
from tools.review_navigation_parts import oracle as parts_oracle
from tools.review_navigation_funnel_wrapper import oracle as funnel_oracle
from tools.review_navigation_rotation import IL2CPP_SHA,UNITY_SHA


def oracle(il2cpp,unity,*,move_source=None):
    prepare=prepare_oracle(il2cpp);parts=parts_oracle(il2cpp);funnel=funnel_oracle(il2cpp,unity)
    if move_source is not None:
        from tools.review_navigation_player_points import oracle as player_oracle
        player=player_oracle(move_source)
    else:player=None
    def run(vertices,faces,connections,flags,penalties,start_point,end_point,tag_mask,**settings):
        result=prepare(vertices,faces,[[[t,c] for t,c,e in row] for row in connections],flags,penalties,start_point,end_point,tag_mask,**settings)
        if result['status']!='complete_prepared_search':return dict(search=result,can_send_packets=False)
        corridor=parts(vertices,faces,connections,result['path_nodes'],result['endpoint_modified_path'])
        left=corridor['left'];right=corridor['right']
        candidates=[]
        for split in (False,True):
            output=funnel(left,right,split=split)
            if player is not None:output['player_callback']=player(output['vector_path'])
            candidates.append(dict(profile=dict(start_end_modes=[3,3],unwrap=True,split_at_every_portal=split),funnel=output))
        return dict(search=result,portals=corridor,candidates=candidates,can_send_packets=False,
                    scope='Native calculations composed across bounded VMs; native single-navmesh part boundary and two explicit modifier profiles, not actual Seeker dispatch or player final path')
    return run


def official(il2cpp,unity,cache_dir,*,move_source=None):
    from wlre.services.world.astar_cache import review_cache,MAX_BYTES
    from wlre.services.world.navigation_database import REVIEWED_MODELS
    call=oracle(il2cpp,unity,move_source=move_source);rows=[];excluded=[]
    for model,digest in REVIEWED_MODELS.items():
        if model in (10000,10004,10005):continue
        with (Path(cache_dir)/f'M{model}-astar-cache.zip').open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Invalid official cache bytes')
        record=review_cache(raw);tile=record['mesh']['tiles'][0];faces=tile['triangles']
        if len(faces)>128:
            excluded.append(dict(model=model,nodes=len(faces),reason='Above 128-node bound; no truncation'));continue
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:settings=json.loads(archive.read('graph0.json'))
        if settings['nearestSearchOnlyXZ']:raise ValueError('Unsupported XZ-only graph')
        vertices=tile['vertices_a_int3'];cases=[]
        for mode,mask in (('land',9),('sea',4),('sky',15)):
            for a,b in ((0,len(faces)-1),(len(faces)-1,0),(0,len(faces)//2)):
                points=[[sum(vertices[j][k] for j in faces[i])/3000 for k in range(3)] for i in (a,b)]
                for point in points:point[1]+=1
                output=call(vertices,faces,record['connections'],[f for p,f in tile['node_metadata']],[p for p,f in tile['node_metadata']],
                            *points,mask,origin=[v/1000 for v in record['origin']],cell_size=settings['cellSize'],tile_cells=(settings['tileSizeX'],settings['tileSizeZ']))
                cases.append(dict(mode=mode,input_points=points,output=output))
        rows.append(dict(model=model,sha256=digest,nodes=len(faces),cases=cases))
    return dict(il2cpp_sha256=IL2CPP_SHA,unity_sha256=UNITY_SHA,models=rows,excluded=excluded,can_send_packets=False)


def synthetic(il2cpp,unity,*,move_source=None):
    call=oracle(il2cpp,unity,move_source=move_source);rows=[]
    for height in (0,3000,-3000):
        vertices=[[0,0,0],[10000,0,0],[0,height,10000],[10000,height,10000],[0,0,20000],[10000,0,20000]]
        faces=[[0,1,2],[1,3,2],[2,3,4],[3,5,4]]
        connections=[[[1,5000,1]],[[0,5000,2],[2,5000,1]],[[1,5000,0],[3,5000,1]],[[2,5000,2]]]
        for mode,mask in (('land',9),('sea',4),('sky',15),('none',0)):
            inputs=dict(vertices=vertices,faces=faces,connections=connections,flags=[1,1+(3<<19),1+(2<<19),1],penalties=[0]*4,
                        start_point=[1,2,1],end_point=[9,2,19],tag_mask=mask,tile_cells=(40,40))
            rows.append(dict(mode=mode,input=inputs,output=call(**inputs)))
    return dict(il2cpp_sha256=IL2CPP_SHA,unity_sha256=UNITY_SHA,cases=rows,can_send_packets=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--libunity',required=True);parser.add_argument('--cache-dir');parser.add_argument('--move-source');args=parser.parse_args()
    try:print(json.dumps(official(args.libil2cpp,args.libunity,args.cache_dir,move_source=args.move_source) if args.cache_dir else synthetic(args.libil2cpp,args.libunity,move_source=args.move_source),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
