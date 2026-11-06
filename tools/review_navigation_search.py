"""Bounded native ABPath search on explicitly prepared synthetic graph state.

Runs official expansion, endpoint costs, recursive G updates, heap and Trace.
External modf and single-thread synchronization are explicitly modeled. This is
not the official client runtime, Prepare/GetNearest or player postprocessing.
"""
import argparse
import json
import math
import struct
from tools.review_navigation_path_state import oracle as state_oracle
from tools.review_navigation_rotation import IL2CPP_SHA


def validate_graph(positions,connections,flags,penalties,start,end,tag_mask,tag_penalties,points):
    n=len(positions)
    if not 1<=n<=256 or len(connections)!=n or len(flags)!=n or len(penalties)!=n:
        raise ValueError('Invalid bounded search graph')
    if any(type(i) is not int or not 0<=i<n for i in (start,end)):raise ValueError('Invalid endpoint index')
    for p in [*positions,*points]:
        if len(p)!=3 or any(type(v) is not int or abs(v)>1000000 for v in p):raise ValueError('Invalid search position')
    if len(points)!=2:raise ValueError('Require two endpoint points')
    if type(tag_mask) is not int or not 0<=tag_mask<2**32:raise ValueError('Invalid tag mask')
    if len(tag_penalties)!=32:raise ValueError('Require 32 tag penalties')
    if any(type(v) is not int or not 0<=v<=100000 for v in [*penalties,*tag_penalties]):raise ValueError('Invalid bounded penalty')
    if any(type(v) is not int or not 0<=v<2**24 for v in flags):raise ValueError('Invalid graph-zero node flags')
    for i,edges in enumerate(connections):
        seen=set()
        if len(edges)>32:raise ValueError('Too many connections')
        for target,cost in edges:
            if type(target) is not int or not 0<=target<n or target==i or target in seen:raise ValueError('Invalid connection')
            if type(cost) is not int or not 1<=cost<=100000:raise ValueError('Invalid bounded edge cost')
            # Special-cost division must have a nonzero rounded center distance.
            if positions[i]==positions[target]:raise ValueError('Coincident connected centers')
            seen.add(target)
    # The native cost field is only 28 bits, and G/F are uint32. Bound even
    # worst-case endpoint scaling and a simple path before writing VM memory.
    scaled=0
    for source,row in enumerate(connections):
        for target,cost in row:
            corrected=[points[0] if i==start else points[1] if i==end else positions[i] for i in (source,target)]
            # At the coordinate bound, binary32 distance plus rounding deviates
            # by less than one Int3 unit; widen numerator/denominator accordingly.
            lower=max(1,math.floor(math.dist(positions[source],positions[target]))-1)
            upper=math.ceil(math.dist(*corrected))+1
            scaled=max(scaled,math.ceil(cost*upper/lower))
    if scaled>=2**28 or n*(scaled+200000)+6000000>=2**32:raise ValueError('Potential native cost overflow')



def oracle(path,*,_state=None,_existing_state=None):
    state={} if _existing_state is None else _existing_state
    state_oracle(path,_state=state,_path_magnitude=True,_existing_state=_existing_state)
    u=state['vm'];data=state['data']
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_LR,UC_ARM64_REG_PC
    ranges=[(0x2833638,0x283393c),(0x2e9a6b0,0x2e9a7b8),
            (0x2d95938,0x2d95b0c),(0x2d9516c,0x2d9519c),(0x2d955b0,0x2d95840),
            (0x234c80c,0x234c9f4),(0x2d863ec,0x2d86408),(0x2d869bc,0x2d86a4c),
            (0x2d86a8c,0x2d86b7c),(0x234d55c,0x234d6a8),(0x234d6f4,0x234d8e4),
            (0x234da68,0x234dc80),(0x234c294,0x234c29c),(0x2d7f564,0x2d7f574),
            (0x2d951b4,0x2d95224),(0x246b398,0x246b3b8),(0x246e0fc,0x246e100),
            (0x24d26f0,0x24d2f0c),(0x2225164,0x222524c),(0x2d83820,0x2d83848)]
    # Model only external synchronization at these exact reviewed boundaries.
    models=[(0x2472d50,0x2472d54),(0xe6e774,0xe6e778),(0x2d91c7c,0x2d91c80)]
    pages={p for a,b in ranges+models for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x4c58000,0x496a000,0x498a000,0x49b7000,0x499e000,0x4c59000,0x4926000,0x4928000,0x4955000,0x4973000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['ranges'].extend(ranges+models);state['pages'].update(pages)
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    def h(a,v):u.mem_write(a,struct.pack('<H',v))
    def rw(a):return struct.unpack('<I',u.mem_read(a,4))[0]
    def rq(a):return struct.unpack('<Q',u.mem_read(a,8))[0]
    for a in (0x4c5c0b5,0x4c5c0b7,0x4c5c0b8,0x4c5c047,0x4c5c048,0x4c58644,0x4c58645,0x4c58646):u.mem_write(a,b'\1')
    for a in (0x498a430,0x498c2b8,0x49b75f0,0x499e638,0x496ab30,0x497c550):q(a,0x6010000)
    q(0x6010000,0x6010100);w(0x60101e0,1)
    for a in (0x4928060,0x4955018,0x4973240):q(a,0x6010000)
    q(0x4926908,0x6010800);q(0x6010800,0x600e000)
    u.mem_write(0x4c59602,b'\1');u.mem_write(0x4c59603,b'\1');u.mem_write(0x37f3360,data(0x37f3360,5))
    counters={};lock=[False]
    class NoRoute(Exception):pass
    def hook(machine,address,size,user):
        if address in (0x2833724,0x2833638,0x234c80c,0x2d96358):counters[hex(address)]=counters.get(hex(address),0)+1
        if address==0x2472d50:
            if u.reg_read(UC_ARM64_REG_X0)!=0x600f000 or u.reg_read(UC_ARM64_REG_LR)!=0x2d951e0 or lock[0]:raise ValueError('Unreviewed monitor enter')
            pointer=u.reg_read(UC_ARM64_REG_X2)
            if not 0x61fe000<=pointer<0x61ff000:raise ValueError('Invalid lockTaken pointer')
            u.mem_write(pointer,b'\1');lock[0]=True;u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
        elif address==0xe6e774:
            if u.reg_read(UC_ARM64_REG_X0)!=0x600f000 or u.reg_read(UC_ARM64_REG_LR)!=0x2d95210 or not lock[0]:raise ValueError('Unreviewed monitor exit')
            lock[0]=False;u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
        elif address==0x2d91c7c:
            if u.reg_read(UC_ARM64_REG_X0)!=0x6008000:raise ValueError('Invalid error receiver')
            raise NoRoute()
    u.hook_add(UC_HOOK_CODE,hook)
    def execute(a,args):return state['execute'](a,args,instruction_limit=2000000)
    def run(positions,connections,flags,penalties,start,end,tag_mask,tag_penalties=None,points=None,*,heuristic_scale=0.0,heuristic=0,_prepare=None):
        if type(heuristic) is not int or heuristic not in (0,2):raise ValueError('Unreviewed heuristic mode')
        if type(heuristic_scale) not in (int,float) or not math.isfinite(heuristic_scale) or not 0<=heuristic_scale<=1:raise ValueError('Invalid heuristic scale')
        tag_penalties=[0]*32 if tag_penalties is None else tag_penalties
        points=[positions[start],positions[end]] if points is None and type(start) is int and type(end) is int and 0<=start<len(positions) and 0<=end<len(positions) else points
        if points is None:raise ValueError('Invalid endpoint points')
        validate_graph(positions,connections,flags,penalties,start,end,tag_mask,tag_penalties,points)
        # Endpoint choice is prepared input. No nearest-node or Area equivalence claimed.
        if _prepare is None and any(not flags[i]&1 or not tag_mask&(1<<((flags[i]>>19)&31)) for i in (start,end)):
            raise ValueError('Prepared endpoint is not traversable')
        n=len(positions);counters.clear();lock[0]=False
        u.mem_write(0x6000000,bytes(0x10000));u.mem_write(0x60a0000,bytes(0x50000))
        h(0x6000010,1);q(0x6000020,0x6001000);q(0x6000028,0x6002000);w(0x6002018,n)
        q(0x6001018,0x6003000);w(0x6003018,1025)
        q(0x6008000,0x600e000);q(0x6008010,0x6000000);q(0x6008030,0x600f000)
        u.mem_write(0x600e12c,b'\1');q(0x600e0c8,0x600e800);q(0x600e800,0x600e000)
        q(0x600e258,0x234c80c);q(0x600e288,0x2d96358);q(0x600e2f8,0x234c294);q(0x600e318,0x234d55c)
        q(0x6008050,0x6009000);q(0x6008058,0x600a000)
        q(0x6009010,0x600b000);q(0x600a010,0x600d000);w(0x600b018,256);w(0x600d018,256)
        # Native reviewed modes 0 and 2. Default remains zero-scale mode 0;
        # scene-profile diagnostics explicitly select mode 2, scale 1.
        # The embedding cost pointer remains null.
        w(0x6008088,heuristic);u.mem_write(0x600808c,struct.pack('<f',heuristic_scale));w(0x60080ac,tag_mask)
        q(0x60080b0,0x600c000);w(0x600c018,32);u.mem_write(0x600c020,struct.pack('<32I',*tag_penalties))
        q(0x60080d0,0x6090000+start*0x100);q(0x60080d8,0x6090000+end*0x100)
        u.mem_write(0x6008110,struct.pack('<3i',*points[0]));u.mem_write(0x60080a0,struct.pack('<3i',*points[1]))
        f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
        for address,point in zip((0x60080f8,0x6008104),points):u.mem_write(address,struct.pack('<3f',*[f32(f32(x)*f32(.001)) for x in point]))
        q(0x60f0178,0x2833638);q(0x60f01e8,0x2833724)
        for i,(position,edges) in enumerate(zip(positions,connections)):
            pn=0x6080000+i*0x100;node=0x6090000+i*0x100;arr=0x60a0000+i*0x400
            u.mem_write(pn,bytes(0x100));u.mem_write(node,bytes(0x100))
            q(node,0x60f0000);w(node+0x10,i);w(node+0x14,flags[i]);w(node+0x18,penalties[i]);u.mem_write(node+0x1c,struct.pack('<3i',*position));q(node+0x28,arr)
            w(arr+0x18,len(edges))
            for j,(target,cost) in enumerate(edges):q(arr+0x20+j*16,0x6090000+target*0x100);w(arr+0x28+j*16,cost)
            q(pn+0x10,node);h(pn+0x22,65535);q(0x6002020+i*8,pn)
        prepared=None
        if _prepare is None:execute(0x2e9a6d0,(0x6080000+end*0x100,1,0))
        try:
            if _prepare is not None:
                prepared=_prepare()
                start,end=prepared['nodes'];points=prepared['int_points']
                validate_graph(positions,connections,flags,penalties,start,end,tag_mask,tag_penalties,points)
            stored_scale=struct.unpack('<f',u.mem_read(0x600808c,4))[0]
            requested_scale=struct.unpack('<f',struct.pack('<f',heuristic_scale))[0]
            if rw(0x6008088)!=heuristic or stored_scale!=requested_scale:raise ValueError('Prepared heuristic profile changed')
            execute(0x234d6f4,(0x6008000,0))
            if rw(0x6008040)!=2:execute(0x234da68,(0x6008000,2**63-1,0))
        except NoRoute:
            return dict(status='native_no_route_error_boundary',calls=dict(counters),can_send_packets=False,**({'prepare_completed':prepared is not None,**({'prepared':prepared} if prepared is not None else {})} if _prepare is not None else {}))
        if lock[0] or rw(0x6008040)!=2:raise ValueError('Incomplete native search')
        count=rw(0x6009018)
        if not 1<=count<=n or count!=rw(0x600a018):raise ValueError('Invalid native trace size')
        refs=[rq(0x600b020+i*8) for i in range(count)]
        if any(not 0x6090000<=r<0x6090000+n*0x100 or (r-0x6090000)%0x100 for r in refs):raise ValueError('Invalid trace reference')
        nodes=[(r-0x6090000)//0x100 for r in refs]
        if nodes[0]!=start or nodes[-1]!=end or len(set(nodes))!=count:raise ValueError('Invalid native search route')
        vectors=[list(struct.unpack('<3f',u.mem_read(0x600d020+i*12,12))) for i in range(count)]
        w(0x600f11c,3);w(0x600f120,3)
        execute(0x24d26f0,(0x600f100,0x6008000,0))
        modified_count=rw(0x600a018)
        if modified_count!=max(2,count):raise ValueError('Invalid endpoint-modified size')
        modified=[list(struct.unpack('<3f',u.mem_read(0x600d020+i*12,12))) for i in range(modified_count)]
        expected=[list(v) for v in vectors] if count>1 else [list(vectors[0]),list(vectors[0])]
        expected[0]=list(struct.unpack('<3f',u.mem_read(0x60080f8,12)));expected[-1]=list(struct.unpack('<3f',u.mem_read(0x6008104,12)))
        if modified!=expected:raise ValueError('Native endpoint modifier mismatch')
        parents=[];gs=[]
        for i in range(n):
            pn=0x6080000+i*0x100;parent=rq(pn+0x18);parents.append(None if parent==0 else (parent-0x6080000)//0x100);gs.append(rw(pn+0x28))
        return dict(status='complete_prepared_search',path_nodes=nodes,vector_path=vectors,endpoint_modified_path=modified,total_cost=gs[end],parents=parents,g_costs=gs,calls=dict(counters),can_send_packets=False,**({'prepared':prepared} if prepared is not None else {}))
    if _state is not None:_state.update(state)
    return run



def reference_costs(positions,connections,flags,penalties,start,end,tag_mask,tag_penalties,points):
    """Independent Bellman-Ford cost check; no native queue/parent decisions."""
    f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
    magnitude=lambda a,b:round(f32(math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))))
    edges=[]
    for source,row in enumerate(connections):
        for target,cost in row:
            if not flags[target]&1 or not tag_mask&(1<<((flags[target]>>19)&31)):continue
            if start in (source,target) or end in (source,target):
                corrected=[points[0] if i==start else points[1] if i==end else positions[i] for i in (source,target)]
                cost=int((cost/magnitude(positions[source],positions[target]))*magnitude(*corrected))
            cost+=penalties[target]+tag_penalties[(flags[target]>>19)&31]
            edges.append((source,target,cost))
    distances=[math.inf]*len(positions);distances[start]=penalties[start]+tag_penalties[(flags[start]>>19)&31]
    for _ in range(len(positions)-1):
        changed=False
        for source,target,cost in edges:
            if distances[source]+cost<distances[target]:distances[target]=distances[source]+cost;changed=True
        if not changed:break
    return distances[end],edges


def compare(fixture,result):
    points=fixture.get('points',[fixture['positions'][fixture['start']],fixture['positions'][fixture['end']]])
    tag_penalties=fixture.get('tag_penalties',[0]*32)
    expected,edges=reference_costs(*(fixture[k] for k in ('positions','connections','flags','penalties','start','end','tag_mask')),tag_penalties,points)
    if math.isinf(expected):
        if result['status']!='native_no_route_error_boundary':raise ValueError('Unexpected reachable native path')
        return
    if result['status']!='complete_prepared_search' or result['total_cost']!=expected:raise ValueError('Native shortest cost mismatch')
    route=result['path_nodes'];lookup={(a,b):cost for a,b,cost in edges}
    total=fixture['penalties'][route[0]]+tag_penalties[(fixture['flags'][route[0]]>>19)&31]
    for a,b in zip(route,route[1:]):
        if (a,b) not in lookup:raise ValueError('Native path crosses excluded edge')
        total+=lookup[a,b]
    if total!=expected:raise ValueError('Native route cost mismatch')
    f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
    vectors=[[f32(f32(x)*f32(.001)) for x in fixture['positions'][i]] for i in route]
    if result['vector_path']!=vectors:raise ValueError('Native traced positions mismatch')


def vectors(path):
    call=oracle(path);rows=[]
    for mode,mask,endpoint_tag in (('land',9,0),('sea',4,2),('sky',15,0)):
        for height in (0,500,-500):
            for shifted in (False,True):
                for blocked in (False,True):
                    positions=[[0,0,0],[1000,height,500],[1000,-height,-500],[2000,0,0]]
                    flags=[1+(endpoint_tag<<19),1+(3<<19),1+(2<<19),1+(endpoint_tag<<19)]
                    if blocked:flags[1]&=~1;flags[2]&=~1
                    fixture=dict(positions=positions,connections=[[[1,100],[2,150]],[[3,100]],[[3,150]],[]],flags=flags,penalties=[2,3,4,5],start=0,end=3,tag_mask=mask,tag_penalties=[7*i for i in range(32)])
                    if shifted:fixture['points']=[[100,50,0],[1900,-50,0]]
                    result=call(**fixture);compare(fixture,result)
                    rows.append(dict(mode=mode,input=fixture,official_output=result))
    recursive=dict(positions=[[100,0,0],[900,0,0],[950,0,0],[0,0,0],[1000,0,0]],connections=[[[1,100],[3,1]],[[2,100]],[[4,1000]],[[1,1]],[]],flags=[1]*5,penalties=[0]*5,start=0,end=4,tag_mask=9,heuristic_scale=1)
    result=call(**recursive);compare(recursive,result)
    if result['calls'].get('0x2833638',0)<3:raise ValueError('Missing recursive descendant update')
    rows.append(dict(case='recursive_reopen_adversarial_heuristic',input=recursive,official_output=result))
    for points in (None,[[10,-20,30],[-10,20,-30]]):
        fixture=dict(positions=[[0,0,0]],connections=[[]],flags=[1],penalties=[3],start=0,end=0,tag_mask=9)
        if points is not None:fixture['points']=points
        result=call(**fixture);compare(fixture,result);rows.append(dict(case='same_node',input=fixture,official_output=result))
    n=256
    boundary=dict(positions=[[i*1000,0,0] for i in range(n)],
                  connections=[([[i-1,1000]] if i else [])+([[i+1,1000]] if i<n-1 else []) for i in range(n)],
                  flags=[1]*n,penalties=[0]*n,start=0,end=n-1,tag_mask=9)
    result=call(**boundary);compare(boundary,result)
    if len(result['path_nodes'])!=256:raise ValueError('Full boundary trace missing')
    rows.append(dict(case='maximum_256_node_trace',input=boundary,official_output=result))
    return dict(source_sha256=IL2CPP_SHA,cases=rows,can_send_packets=False,
                modeled_dependencies=['finite modf','single-thread monitor enter/exit'],
                scope='Native ABPath.Initialize/CalculateStep/Open/recursive G/heap/Trace and StartEndModifier modes 3 on prepared graph; not Prepare, nearest selection, Funnel, registered modifier sequence or player final vectorPath')



def official(path,cache_dir):
    import hashlib
    from pathlib import Path
    from wlre.services.world.astar_cache import review_cache,MAX_BYTES
    from wlre.services.world.navigation_database import REVIEWED_MODELS
    from tools.review_navigation_vertices import oracle as vertex_oracle
    call=oracle(path);center=vertex_oracle(path,modeled_center=True);rows=[];excluded=[]
    for model,digest in REVIEWED_MODELS.items():
        if model in (10000,10004,10005):continue
        with (Path(cache_dir)/f'M{model}-astar-cache.zip').open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Invalid official cache bytes')
        record=review_cache(raw);tile=record['mesh']['tiles'][0];faces=tile['triangles']
        if len(faces)>256:
            excluded.append(dict(model=model,nodes=len(faces),reason='Above 256-node bounded search fixture; no truncation'));continue
        positions=[center(tile['vertices_a_int3'],face)['center'] for face in faces]
        flags=[f for p,f in tile['node_metadata']];penalties=[p for p,f in tile['node_metadata']]
        connections=[[[target,cost] for target,cost,edge in row] for row in record['connections']]
        cases=[]
        for mode,mask in (('land',9),('sea',4),('sky',15)):
            allowed=[i for i,f in enumerate(flags) if f&1 and mask&(1<<((f>>19)&31))]
            if not allowed:
                cases.append(dict(mode=mode,status='no_traversable_endpoints'));continue
            for start,end in ((allowed[0],allowed[-1]),(allowed[-1],allowed[0]),(allowed[0],allowed[len(allowed)//2])):
                fixture=dict(positions=positions,connections=connections,flags=flags,penalties=penalties,start=start,end=end,tag_mask=mask)
                output=call(**fixture);compare(fixture,output)
                cases.append(dict(mode=mode,start=start,end=end,official_output=output))
        rows.append(dict(model=model,sha256=digest,nodes=len(faces),cases=cases))
    return dict(models=rows,excluded=excluded,source_sha256=IL2CPP_SHA,can_send_packets=False,
                modeled_dependencies=['finite modf','single-thread monitor enter/exit'],
                scope='Whole reviewed graph connections/flags/penalties and native centers in prepared ABPath search; center endpoints selected explicitly, not Prepare, Funnel or player final route')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--cache-dir');args=parser.parse_args()
    try:print(json.dumps(official(args.libil2cpp,args.cache_dir) if args.cache_dir else vectors(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
