"""Compare bounded native full-path fixtures under baseline and scene profiles.

Verified scene serialization supplies profile inputs; runtime callbacks, Unity
startup and player-session equivalence are not established. No packets are sent.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile
from tools.review_navigation_path_pipeline import oracle
from tools.review_navigation_scene_settings import inspect


def review(libil2cpp,libunity,manifest_root,bundle_root,cache_dir,move_source):
    from wlre.services.world.astar_cache import review_cache,MAX_BYTES
    from wlre.services.world.navigation_database import REVIEWED_MODELS
    scenes=inspect(manifest_root,bundle_root);call=oracle(libil2cpp,libunity,move_source=move_source);rows=[];excluded=[]
    for scene in scenes['scenes']:
        profile=scene['astar']['settings'];expected=dict(heuristic=2,heuristicScale=1.0,maxNearestNodeDistance=100.0,fullGetNearestSearch=False)
        if any(profile[k]!=v for k,v in expected.items()):raise ValueError('Unreviewed scene search profile')
        model=scene['model']
        with (Path(cache_dir)/f'M{model}-astar-cache.zip').open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=REVIEWED_MODELS[model]:raise ValueError('Unverified graph cache')
        record=review_cache(raw);tile=record['mesh']['tiles'][0];faces=tile['triangles'];vertices=tile['vertices_a_int3']
        if len(faces)>256:
            excluded.append(dict(model=model,nodes=len(faces),reason='Above existing graph bound'));continue
        with zipfile.ZipFile(io.BytesIO(raw)) as z:graph=json.loads(z.read('graph0.json'))
        if graph['nearestSearchOnlyXZ']:raise ValueError('Unsupported XZ-only graph')
        points=[[sum(vertices[j][k] for j in faces[i])/3000 for k in range(3)] for i in (0,len(faces)-1)]
        for point in points:point[1]+=1
        cases=[]
        for mode,mask in (('land',9),('sea',4),('sky',15)):
            outputs={}
            for name,enabled in (('baseline',False),('serialized_scene',True)):
                outputs[name]=call(vertices,faces,record['connections'],[f for p,f in tile['node_metadata']],
                                   [p for p,f in tile['node_metadata']],*points,mask,
                                   origin=[v/1000 for v in record['origin']],cell_size=graph['cellSize'],
                                   tile_cells=(graph['tileSizeX'],graph['tileSizeZ']),scene_profile=enabled)
            cases.append(dict(mode=mode,tag_mask=mask,input_points=points,outputs=outputs))
        rows.append(dict(model=model,graph_sha256=hashlib.sha256(raw).hexdigest(),scene_sha256=scene['sha256'],
                         nodes=len(faces),scene_profile=expected,cases=cases))
    return dict(models=rows,excluded=excluded,resource_platform=scenes['resource_platform'],data_version=scenes['data_version'],
                baseline_profile=dict(heuristic=0,heuristicScale=0.0,fullGetNearestSearch=True,maxNearestNodeDistance=None),
                can_send_packets=False,runtime_profile_verified=False,scope=__doc__)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('libil2cpp','libunity','manifest-root','bundle-root','cache-dir','move-source'):p.add_argument('--'+key,required=True)
    a=p.parse_args();print(json.dumps(review(a.libil2cpp,a.libunity,a.manifest_root,a.bundle_root,a.cache_dir,a.move_source),sort_keys=True))


if __name__=='__main__':main()
