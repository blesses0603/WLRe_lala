"""Offline native nearest-node checks using verified PC scene search settings.

Android ARM64 functions run in prepared VMs, not a Windows or Android player.
No callback overrides, complete paths or movement authority are established.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile
from tools.review_navigation_scene_settings import inspect
from tools.review_navigation_nearest import oracle
from tools.review_navigation_outer import compare


def review(libil2cpp,manifest_root,bundle_root,cache_dir):
    from wlre.services.world.astar_cache import review_cache,MAX_BYTES
    from wlre.services.world.navigation_database import REVIEWED_MODELS
    scenes=inspect(manifest_root,bundle_root)
    call=oracle(libil2cpp);rows=[];excluded=[]
    for scene in scenes['scenes']:
        model=scene['model'];profile=scene['astar']['settings']
        if profile['maxNearestNodeDistance']!=100 or profile['fullGetNearestSearch'] is not False:
            raise ValueError('Scene profile changed; review required')
        with (Path(cache_dir)/f'M{model}-astar-cache.zip').open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=REVIEWED_MODELS[model]:
            raise ValueError('Unverified graph cache')
        record=review_cache(raw);tile=record['mesh']['tiles'][0];faces=tile['triangles']
        if len(faces)>256:
            excluded.append(dict(model=model,nodes=len(faces),reason='Above research bound; no truncation'));continue
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:graph=json.loads(archive.read('graph0.json'))
        if graph['nearestSearchOnlyXZ']:raise ValueError('Unsupported XZ-only graph')
        vertices=tile['vertices_a_int3'];flags=[f for p,f in tile['node_metadata']]
        options=dict(origin=[v/1000 for v in record['origin']],outer=True,node_flags=flags,
                     cell_size=graph['cellSize'],tile_cells=(graph['tileSizeX'],graph['tileSizeZ']))
        cases=[]
        for mode,mask in (('land',9),('sea',4),('sky',15)):
            allowed=[bool(f&1 and mask&(1<<((f>>19)&31))) for f in flags]
            for index in (0,len(faces)//2,len(faces)-1):
                point=[sum(vertices[j][k] for j in faces[index])/3000 for k in range(3)];point[1]+=1
                # Independent closest-triangle check for the original unbounded profile.
                baseline=call(vertices,faces,point,tag_mask=mask,full_search=True,**options)
                compare(vertices,faces,point,baseline,allowed)
                actual=call(vertices,faces,point,tag_mask=mask,full_search=False,max_distance=100,**options)
                distance=None if baseline['point'] is None else sum((a-b)**2 for a,b in zip(point,baseline['point']))
                if distance is None or distance>10000:
                    if actual['node'] is not None:raise ValueError('Distance/tag rejection mismatch')
                else:compare(vertices,faces,point,actual,allowed)
                cases.append(dict(mode=mode,triangle=index,point=point,baseline=baseline,scene_profile_result=actual,
                                  differs=actual!=baseline))
        far=[0,max(v[1] for v in vertices)/1000+101,0]
        try:
            rejected=call(vertices,faces,far,tag_mask=9,full_search=False,max_distance=100,**options)
            if rejected['node'] is not None:raise ValueError('Far point not rejected')
            far_check=dict(status='verified_rejection',point=far,result=rejected)
        except ValueError as error:
            if str(error)!='Instruction budget':raise
            far_check=dict(status='unverified_instruction_budget',point=far,limit=200000)
            call=oracle(libil2cpp)  # Never reuse partially executed VM state.
        rows.append(dict(model=model,graph_sha256=hashlib.sha256(raw).hexdigest(),scene_sha256=scene['sha256'],
                         serialized_settings=profile,nodes=len(faces),cases=cases,far_check=far_check))
    return dict(models=rows,excluded=excluded,
                all_far_queries_verified=all(row['far_check']['status']=='verified_rejection' for row in rows),
                resource_platform=scenes['resource_platform'],
                data_version=scenes['data_version'],package_version=scenes['package_version'],
                can_send_packets=False,runtime_overrides_verified=False,complete_paths_verified=False,scope=__doc__)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('libil2cpp','manifest-root','bundle-root','cache-dir'):parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    print(json.dumps(review(args.libil2cpp,args.manifest_root,args.bundle_root,args.cache_dir),sort_keys=True))


if __name__=='__main__':main()
