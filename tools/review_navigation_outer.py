"""Outer native GetNearest: synthetic tiles and bounded reviewed official meshes.

Native execution uses prepared state and an explicit modf model. No live device,
formal path/movement authority, or arbitrary official-map support is implied.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile
from tools.review_navigation_nearest import oracle,reference_triangle


def compare(vertices,faces,point,output,allowed):
    candidates=[]
    for i,face in enumerate(faces):
        if not allowed[i]:continue
        closest=reference_triangle([[x/1000 for x in vertices[j]] for j in face],point)
        distance=sum((x-y)**2 for x,y in zip(point,closest));candidates.append((distance,i,closest))
    if not candidates:
        if output['node'] is not None:raise ValueError('Unexpected selected node')
        return
    best=min(candidates)
    chosen=next((row for row in candidates if row[1]==output['node']),None)
    if chosen is None:raise ValueError('Native selected missing/excluded node')
    # Boundary ties may select a different triangle, but the selected triangle's
    # independently computed closest point and distance must still be minimal.
    if chosen[0]>best[0]+0.001 or max(abs(x-y) for x,y in zip(output['point'],chosen[2]))>0.0002:
        raise ValueError('Native nearest mismatch '+str((output,chosen,best)))


def synthetic(path):
    call=oracle(path);rows=[]
    vertices=[];faces=[]
    for i in range(4):
        x=(i%2)*10000;z=(i//2)*10000;y=i*1000
        vertices.extend([[x+1000,y,z+1000],[x+9000,y,z+1000],[x+1000,y,z+9000]])
        faces.append([3*i,3*i+1,3*i+2])
    for shape,ownership in (((1,1),[0]*4),((2,2),[0,1,2,3])):
        for point in ((2,3,2),(12,4,2),(2,4,12),(12,5,12),(10,2,5),(-.1,1,1)):
            for full in (False,True):
                for mask in (0,1):
                    for limit in (None,0.5,10.):
                        output=call(vertices,faces,point,outer=True,full_search=full,graph_mask=mask,max_distance=limit,tile_shape=shape,face_tiles=ownership)
                        nearest=min(sum((x-y)**2 for x,y in zip(point,reference_triangle([[v/1000 for v in vertices[j]] for j in face],point))) for face in faces)
                        allowed=bool(mask) and (limit is None or nearest<=limit*limit)
                        compare(vertices,faces,point,output,[allowed]*len(faces))
                        rows.append(dict(shape=shape,point=point,full_search=full,graph_mask=mask,max_distance=limit,output=output))
    return dict(cases=rows,scope='Synthetic one graph, one/four tiles, bounded outer selection and distance limits',can_send_packets=False)


def official(path,cache_dir):
    from wlre.services.world.astar_cache import review_cache,MAX_BYTES
    from wlre.services.world.navigation_database import REVIEWED_MODELS
    call=oracle(path);rows=[];excluded=[]
    for model,digest in REVIEWED_MODELS.items():
        if model in (10000,10004,10005):continue
        file=Path(cache_dir)/f'M{model}-astar-cache.zip'
        with file.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Invalid official model bytes '+str(model))
        result=review_cache(raw);tile=result['mesh']['tiles'][0];faces=tile['triangles'];vertices=tile['vertices_a_int3']
        if len(faces)>512:
            excluded.append(dict(model=model,nodes=len(faces),reason='Above the research probe 512-node bound; not truncated'));continue
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:settings=json.loads(archive.read('graph0.json'))
        if settings['nearestSearchOnlyXZ']:raise ValueError('Unreviewed XZ-only official map')
        flags=[row[1] for row in tile['node_metadata']];origin=[x/1000 for x in result['origin']]
        cases=[]
        for index in sorted({0,len(faces)//2,len(faces)-1}):
            point=[sum(vertices[j][k] for j in faces[index])/3000 for k in range(3)];point[1]+=2
            for full in (False,True):
                for mask in (9,15):
                    output=call(vertices,faces,point,origin,outer=True,full_search=full,node_flags=flags,tag_mask=mask,
                                cell_size=settings['cellSize'],tile_cells=(settings['tileSizeX'],settings['tileSizeZ']))
                    allowed=[bool(f&1 and mask&(1<<((f>>19)&31))) for f in flags]
                    compare(vertices,faces,point,output,allowed)
                    cases.append(dict(point=point,full_search=full,tag_mask=mask,output=output))
        rows.append(dict(model=model,sha256=digest,nodes=len(faces),cases=cases))
    return dict(models=rows,excluded=excluded,scope='Whole reviewed official mesh geometry/settings/flags in synthetic native runtime state; not official deserialization or device execution',modeled_modf=True,can_send_packets=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--cache-dir');args=parser.parse_args()
    try:print(json.dumps(official(args.libil2cpp,args.cache_dir) if args.cache_dir else synthetic(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
