"""Native Prepare/GetNearest/Area followed by search in one bounded VM.

Preallocated graph state, native hierarchy output and modeled math/monitor/TLS
are explicit. This does not reproduce the player modifier registration or Funnel.
"""
import argparse
import json
import math
import struct
from tools.review_navigation_nearest import oracle as nearest_oracle,validate_query
from tools.review_navigation_search import oracle as search_oracle,compare as compare_search,validate_graph as validate_search
from tools.review_navigation_groups import oracle as groups_oracle
from tools.review_navigation_outer import compare as compare_nearest
from tools.review_navigation_rotation import IL2CPP_SHA


def validate_inputs(vertices,faces,connections,flags,penalties,start_point,end_point,tag_mask,origin=(0,0,0)):
    validate_query(vertices,faces,start_point,origin);validate_query(vertices,faces,end_point,origin)
    n=len(faces)
    if n>128:raise ValueError('Require at most 128 preparation nodes')
    # Validate graph bookkeeping before creating native hierarchy. Exact native
    # centers and adjusted endpoint cost bounds are validated again by search.
    validate_search([[i,0,0] for i in range(n)],connections,flags,penalties,0,0,tag_mask,[0]*32,[[0,0,0],[0,0,0]])


def oracle(path):
    state={};nearest=nearest_oracle(path,_state=state,_search_state=True)
    search=search_oracle(path,_existing_state=state,_state=state);groups=groups_oracle(path,multiple=True)
    u=state['vm'];data=state['data']
    from unicorn.arm64_const import UC_ARM64_REG_TPIDR_EL0
    ranges=((0x234d214,0x234d55c),(0x2d861d8,0x2d863ec),(0x2d95850,0x2d95938),
            (0x2d93f00,0x2d93f74),(0x2d84a14,0x2d84a44),(0x2a90220,0x2a9024c),
            (0x234caf4,0x234cbd4),(0x24c410c,0x24c4254),(0x20d134c,0x20d1358))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x4936000,0x497b000,0x4947000,0x49a9000,0x4925000,0x497f000,0x4986000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['pages'].update(pages);state['ranges'].extend(ranges)
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    for a in (0x4c58643,0x4c58641,0x4c5c042,0x4c5c0b6,0x4c5c0a8,0x4c595ac):u.mem_write(a,b'\1')
    for a in (0x497be28,0x4947f80,0x49a9200,0x49254f8,0x497fdf0):q(a,0x6010000)
    # Preinitialized Astar active/class/static-field state, shared by Prepare,
    # GetNearest, GetArea and the disabled (zero-pivot) embedding heuristic.
    q(0x498a430,0x601b000);q(0x601b000,0x601b100);w(0x601b1e0,1)
    q(0x601b1b8,0x601b300);q(0x601b318,0x6049000)
    q(0x60490b8,0x6063000);q(0x6063020,0x6064000)
    q(0x60490f8,0x6061000);q(0x6061028,0x6062000);w(0x6062018,1);w(0x6061034,0)
    q(0x49360f0,0x601b600);q(0x601b600,0x6047000)
    u.mem_write(0x604712c,b'\1');q(0x60470c8,0x6047800);q(0x6047800,0x6047000);q(0x6047198,0x2a90220)
    q(0x4986eb0,0x601b700);q(0x601b700,0x601b800);u.mem_write(0x601b92c,b'\1')
    # A fixed canary in prepared single-thread TLS, not an Android TLS runtime.
    u.reg_write(UC_ARM64_REG_TPIDR_EL0,0x61d0000)
    def run(vertices,faces,connections,flags,penalties,start_point,end_point,tag_mask,origin=(0,0,0),cell_size=1.,tile_cells=(10,10)):
        validate_inputs(vertices,faces,connections,flags,penalties,start_point,end_point,tag_mask,origin)
        n=len(faces)
        # Native hierarchy construction ignores traffic tags, as the official
        # hierarchy does; NNConstraint subsequently enforces both Area and tags.
        hierarchy=groups([[target for target,cost in row] for row in connections],[bool(f&1) for f in flags])
        native_flags=[(f&~0x3fffe)|(h&0x3fffe) for f,h in zip(flags,hierarchy['flags'])]
        # Clear Area filtering before building/reusing graph and BBTree state.
        u.mem_write(0x6048014,b'\0');w(0x6048018,0xffffffff)
        nearest(vertices,faces,start_point,origin,outer=True,full_search=True,node_flags=native_flags,tag_mask=tag_mask,cell_size=cell_size,tile_cells=tile_cells)
        positions=[list(struct.unpack('<3i',u.mem_read(0x609001c+i*0x100,12))) for i in range(n)]
        areas=hierarchy['native_area_output']['areas'];w(0x6064018,len(areas));u.mem_write(0x6064020,struct.pack('<'+'I'*len(areas),*areas))
        def prepare():
            for i,face in enumerate(faces):u.mem_write(0x6090030+i*0x100,struct.pack('<3i',*face))
            q(0x60f0218,0x2832dd8);q(0x600e308,0x234caf4)
            q(0x6008078,0x6048000);u.mem_write(0x6048014,b'\1');w(0x6048018,0xffffffff)
            u.mem_write(0x604801f,b'\1')
            for address,point in zip((0x60080f8,0x6008104),(start_point,end_point)):u.mem_write(address,struct.pack('<3f',*point))
            state['execute'](0x234d214,(0x6008000,0),instruction_limit=1000000)
            ptrs=struct.unpack('<2Q',u.mem_read(0x60080d0,16))
            if any(not 0x6090000<=p<0x6090000+n*0x100 or (p-0x6090000)%0x100 for p in ptrs):raise ValueError('Invalid prepared endpoint pointer')
            nodes=[(p-0x6090000)//0x100 for p in ptrs]
            points=[list(struct.unpack('<3f',u.mem_read(a,12))) for a in (0x60080f8,0x6008104)]
            int_points=[list(struct.unpack('<3i',u.mem_read(a,12))) for a in (0x6008110,0x60080a0)]
            allowed=[bool(f&1 and tag_mask&(1<<((f>>19)&31))) for f in flags]
            compare_nearest(vertices,faces,start_point,dict(node=nodes[0],point=points[0]),allowed)
            start_area=hierarchy['native_node_areas'][nodes[0]]
            eligible=[ok and area==start_area for ok,area in zip(allowed,hierarchy['native_node_areas'])]
            compare_nearest(vertices,faces,end_point,dict(node=nodes[1],point=points[1]),eligible)
            f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
            if int_points!=[[round(f32(v*1000)) for v in point] for point in points]:raise ValueError('Native endpoint rounding mismatch')
            return dict(nodes=nodes,points=points,int_points=int_points,area=start_area)
        fixture=dict(positions=positions,connections=connections,flags=native_flags,penalties=penalties,start=0,end=0,tag_mask=tag_mask)
        output=search(**fixture,_prepare=prepare)
        if 'prepared' in output:
            fixture.update(start=output['prepared']['nodes'][0],end=output['prepared']['nodes'][1],points=output['prepared']['int_points'])
            compare_search(fixture,output)
        return output
    return run



def vectors(path):
    call=oracle(path);rows=[]
    for height in (0,3000,-3000):
        vertices=[[0,0,0],[10000,0,0],[0,height,10000],[10000,height,10000],[0,2*height,20000],[10000,2*height,20000]]
        faces=[[0,1,2],[1,3,2],[2,3,4],[3,5,4]]
        for disconnected in (False,True):
            connections=[[[1,5000]],[[0,5000],[2,5000]],[[1,5000],[3,5000]],[[2,5000]]]
            if disconnected:connections[1]=[[0,5000]];connections[2]=[[3,5000]]
            for mode,mask in (('land',9),('sea',4),('sky',15),('none',0)):
                inputs=dict(vertices=vertices,faces=faces,connections=connections,flags=[1,1+(3<<19),1+(2<<19),1],penalties=[0]*4,
                            start_point=[1,2,1],end_point=[9,2+2*height/1000,19],tag_mask=mask,tile_cells=(40,40))
                result=call(**inputs)
                if mask==0 and result.get('prepare_completed') is not False:raise ValueError('Empty mask did not fail Prepare')
                rows.append(dict(mode=mode,disconnected=disconnected,input=inputs,official_output=result))
    blocked=dict(vertices=[[0,0,0],[1000,0,0],[0,0,1000]],faces=[[0,1,2]],connections=[[]],flags=[0],penalties=[0],start_point=[0,1,0],end_point=[1,1,0],tag_mask=9)
    output=call(**blocked)
    if output.get('prepare_completed') is not False:raise ValueError('Unwalkable mesh did not fail Prepare')
    rows.append(dict(mode='all_unwalkable',input=blocked,official_output=output))
    return dict(source_sha256=IL2CPP_SHA,cases=rows,can_send_packets=False,
                scope='Native Prepare, same-state GetNearest/Area, search and endpoint modifier; native hierarchy imported from separate bounded grouping VM; modeled finite modf/monitor/TLS, no Funnel or player modifier sequence')



def official(path,cache_dir):
    import hashlib
    import io
    from pathlib import Path
    import zipfile
    from wlre.services.world.astar_cache import review_cache,MAX_BYTES
    from wlre.services.world.navigation_database import REVIEWED_MODELS
    call=oracle(path);rows=[];excluded=[]
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
                output=call(vertices,faces,[[[t,c] for t,c,e in row] for row in record['connections']],
                            [f for p,f in tile['node_metadata']],[p for p,f in tile['node_metadata']],
                            *points,mask,origin=[v/1000 for v in record['origin']],cell_size=settings['cellSize'],tile_cells=(settings['tileSizeX'],settings['tileSizeZ']))
                cases.append(dict(mode=mode,input_points=points,official_output=output))
        rows.append(dict(model=model,sha256=digest,nodes=len(faces),cases=cases))
    return dict(source_sha256=IL2CPP_SHA,models=rows,excluded=excluded,can_send_packets=False,
                scope='Whole reviewed meshes in native Prepare/GetNearest/Area/search/endpoint modifier, full nearest search and zero heuristic; synthetic runtime, no Funnel or actual player settings')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--cache-dir');args=parser.parse_args()
    try:print(json.dumps(official(args.libil2cpp,args.cache_dir) if args.cache_dir else vectors(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
