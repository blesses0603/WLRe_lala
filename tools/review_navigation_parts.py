"""Native navmesh part splitting and portal construction on bounded corridor state.

Only pool allocation is modeled. Unsupported node/link types are rejected before
execution. Prepared graph state is not deserialization or movement authorization.
"""
import argparse
import json
import math
import struct
from tools.review_navigation_portals import oracle as portal_oracle
from tools.review_navigation_rotation import IL2CPP_SHA


def oracle(path):
    state={};portal=portal_oracle(path,_state=state);u=state['vm'];data=state['data']
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_LR,UC_ARM64_REG_PC
    ranges=((0x23565cc,0x2356c14),(0x2357d9c,0x23583b0),
            (0x297c43c,0x297c488),(0x2225164,0x22251c4),(0xe00550,0xe00554),
            (0xe81860,0xe81864),(0xec1130,0xec1178))
    callers={0x1cc2c10:(0x23566d8,),0x1cc17e4:(0x2357e70,0x2357e84)}
    model_ranges=tuple((p,p+4) for p in callers)
    slots=(0x4996120,0x49789c8,0x49b5318,0x4973d80,0x4977440,0x4940508,
           0x49728e0,0x4937a00,0x4926b08,0x4955018,0x4935fb8,0x49343c8,0x49523f8)
    pages={p for a,b in ranges+model_ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{p&~4095 for p in slots}|{0x4c58000,0x4c68000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['pages'].update(pages);state['ranges'].extend(ranges+model_ranges)
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    def read(a):return struct.unpack('<I',u.mem_read(a,4))[0]
    for p in slots:q(p,0x6010000)
    for p in (0x4c58694,0x4c58697):u.mem_write(p,b'\1')
    # Native node type test matches the prepared TriangleMeshNode inheritance.
    q(0x60471d8,0x28339a4)
    allocated=set();calls=[]
    def model(machine,address,size,user):
        if address not in callers:return
        caller=u.reg_read(UC_ARM64_REG_LR)
        if caller not in callers[address]:raise ValueError('Unreviewed part pool caller')
        ptr=0x60d0000 if address==0x1cc2c10 else (0x6040000 if caller==0x2357e70 else 0x6050000)
        if ptr in allocated:raise ValueError('Duplicate part pool allocation')
        if address==0x1cc17e4 and not 2<=u.reg_read(UC_ARM64_REG_X0)<=129:raise ValueError('Invalid part pool bound')
        allocated.add(ptr);calls.append(hex(caller))
        # The part buffer is distinct from the graph connection storage.
        u.mem_write(ptr,bytes(0x2000));q(ptr+0x10,ptr+0x1000);w(ptr+0x1018,128 if address==0x1cc2c10 else 256)
        u.reg_write(UC_ARM64_REG_X0,ptr);u.reg_write(UC_ARM64_REG_PC,caller)
    u.hook_add(UC_HOOK_CODE,model)
    def run(vertices,faces,connections,route,vector_path):
        if not 1<=len(vector_path)<=256 or any(len(p)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1000 for v in p) for p in vector_path):raise ValueError('Invalid bounded vector path')
        expected=portal(vertices,faces,connections,route)
        allocated.clear();calls.clear()
        # Path.path and Path.vectorPath are genuine native list layouts.
        u.mem_write(0x6000000,bytes(0x10000))
        q(0x6000050,0x6001000);q(0x6000058,0x6003000)
        for ptr,count in ((0x6001000,len(route)),(0x6003000,len(vector_path))):
            q(ptr+0x10,ptr+0x1000);w(ptr+0x18,count);w(ptr+0x1018,count)
        for i,n in enumerate(route):q(0x6002020+i*8,0x6080000+n*0x100)
        for i,p in enumerate(vector_path):u.mem_write(0x6004020+i*12,struct.pack('<3f',*p))
        result=struct.unpack('<Q',state['execute'](0x23565cc,(0x6000000,0),instruction_limit=500000)[:8])[0]
        if result!=0x60d0000 or read(result+0x18)!=1:raise ValueError('Unexpected native part count')
        part=bytes(u.mem_read(0x60d1020,36));a,b,*values=struct.unpack('<2i6fI',part)
        if (a,b,values[-1])!=(0,len(route)-1,0):raise ValueError('Unexpected native navmesh part')
        f32=lambda p:list(struct.unpack('<3f',struct.pack('<3f',*p)))
        if values[:3]!=f32(vector_path[0]) or values[3:6]!=f32(vector_path[-1]):raise ValueError('Native part endpoints differ')
        result=struct.unpack('<2Q',state['execute'](0x2357d9c,(0x6001000,0x60d1020,0),instruction_limit=500000))
        if result!=(0x6040000,0x6050000):raise ValueError('Unexpected portal list owners')
        output=[]
        for ptr,side in zip(result,('left','right')):
            count=read(ptr+0x18)
            if count!=len(route)+1:raise ValueError('Unexpected constructed portal count')
            points=[list(struct.unpack('<3f',u.mem_read(ptr+0x1020+i*12,12))) for i in range(count)]
            if points!=[f32(vector_path[0]),*expected[side],f32(vector_path[-1])]:raise ValueError('Native constructed portals differ')
            output.append(points)
        return dict(parts=[dict(start_index=a,end_index=b,start=values[:3],end=values[3:6],is_link=False)],left=output[0],right=output[1],pool_calls=list(calls),can_send_packets=False)
    return run


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    run=oracle(args.libil2cpp)
    print(json.dumps(run([[0,0,0],[10000,0,0],[0,5000,10000],[10000,5000,10000]],[[0,1,2],[1,3,2]],[[[1,5000,1]],[[0,5000,2]]],[0,1],[[1,1,1],[9,4,9]]),sort_keys=True))


if __name__=='__main__':main()
