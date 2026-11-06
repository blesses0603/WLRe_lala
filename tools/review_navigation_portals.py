"""Native same-tile triangle portals for a supplied searched node corridor.

Uses official connection edge indices and world vertices, never guesses a shared
edge. Cross-tile/off-mesh links and missing/invalid edges are rejected.
"""
import argparse
import json
import struct
from tools.review_navigation_vertices import oracle as vertex_oracle,validate_inputs
from tools.review_navigation_rotation import IL2CPP_SHA


def validate_corridor(vertices,faces,connections,route):
    n=len(faces)
    if not 1<=n<=128 or len(connections)!=n or not 1<=len(route)<=n:raise ValueError('Invalid bounded corridor')
    for face in faces:
        validate_inputs(vertices,face)
        a,b,c=[vertices[i] for i in face];v=[b[i]-a[i] for i in range(3)];w=[c[i]-a[i] for i in range(3)]
        if not any((v[1]*w[2]-v[2]*w[1],v[2]*w[0]-v[0]*w[2],v[0]*w[1]-v[1]*w[0])):raise ValueError('Degenerate corridor triangle')
    if any(type(i) is not int or not 0<=i<n for i in route) or len(set(route))!=len(route):raise ValueError('Invalid node route')
    for source,row in enumerate(connections):
        seen=set()
        if len(row)>32:raise ValueError('Connection bound')
        for target,cost,edge in row:
            if type(target) is not int or not 0<=target<n or target==source or target in seen:raise ValueError('Invalid neighbor')
            if type(cost) is not int or not 0<=cost<2**28 or type(edge) is not int or not 0<=edge<3:raise ValueError('Unreviewed edge/cost')
            a=vertices[faces[source][edge]];b=vertices[faces[source][(edge+1)%3]]
            neighbor=[vertices[i] for i in faces[target]]
            if a==b or a not in neighbor or b not in neighbor:raise ValueError('Connection edge not shared by neighbor')
            seen.add(target)
    for a,b in zip(route,route[1:]):
        if not any(t==b for t,c,e in connections[a]):raise ValueError('Missing route connection')


def oracle(path,*,_state=None):
    state={};vertex_oracle(path,_state=state);u=state['vm'];data=state['data']
    from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1
    ranges=((0x283393c,0x2833ef8),(0x2832b84,0x2832ca8),(0x2832dd0,0x2832dd8),(0x2d83820,0x2d83848))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x49b5000,0x494b000,0x379a000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['pages'].update(pages);state['ranges'].extend(ranges);u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    for a in (0x4c5aa90,0x4c5aa8a):u.mem_write(a,b'\1')
    for a in (0x49b5318,0x494b930):q(a,0x6010000)
    u.mem_write(0x379addc,data(0x379addc,4))
    u.mem_write(0x601022c,b'\1');u.mem_write(0x604712c,b'\1')
    q(0x60470c8,0x6047800);q(0x6047800,0x6010100)
    q(0x6047278,0x2832b84);q(0x6047288,0x2832dd0)
    def run(vertices,faces,connections,route):
        validate_corridor(vertices,faces,connections,route)
        w(0x6030018,len(vertices));u.mem_write(0x6030020,b''.join(struct.pack('<3i',*p) for p in vertices))
        for i,(face,neighbors) in enumerate(zip(faces,connections)):
            node=0x6080000+i*0x100;arr=0x60a0000+i*0x400
            u.mem_write(node,bytes(0x100));q(node,0x6047000);w(node+0x14,1)
            u.mem_write(node+0x30,struct.pack('<3i',*face));q(node+0x28,arr);w(arr+0x18,len(neighbors))
            for j,(target,cost,edge) in enumerate(neighbors):
                q(arr+0x20+j*16,0x6080000+target*0x100);w(arr+0x28+j*16,cost);w(arr+0x2c+j*16,edge)
        for record in (0x6040000,0x6050000):
            u.mem_write(record,bytes(0x100));q(record+0x10,record+0x1000);w(record+0x1018,256)
        selected=[]
        for a,b in zip(route,route[1:]):
            result=state['execute'](0x28339c8,(0x6080000+a*0x100,0x6080000+b*0x100,0x6040000,0x6050000,0,0x6090000,0x6090010,0),instruction_limit=20000)
            if struct.unpack('<Q',result[:8])[0]!=1:raise ValueError('Native portal rejected')
            selected.append([struct.unpack('<i',u.mem_read(p,4))[0] for p in (0x6090000,0x6090010)])
        count=len(route)-1
        if any(struct.unpack('<I',u.mem_read(a+0x18,4))[0]!=count for a in (0x6040000,0x6050000)):raise ValueError('Native portal count mismatch')
        left=[list(struct.unpack('<3f',u.mem_read(0x6041020+i*12,12))) for i in range(count)]
        right=[list(struct.unpack('<3f',u.mem_read(0x6051020+i*12,12))) for i in range(count)]
        f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
        for i,(a,b) in enumerate(zip(route,route[1:])):
            edge=next(e for t,c,e in connections[a] if t==b)
            if selected[i]!=[edge,(edge+1)%3]:raise ValueError('Native edge index mismatch')
            expected=[[f32(f32(x)*f32(.001)) for x in vertices[faces[a][j]]] for j in selected[i]]
            if [left[i],right[i]]!=expected:raise ValueError('Native portal vertex mismatch')
        return dict(left=left,right=right,edge_indices=selected,can_send_packets=False)
    if _state is not None:_state.update(state)
    return run


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    call=oracle(args.libil2cpp)
    print(json.dumps(call([[0,0,0],[10000,0,0],[0,5000,10000],[10000,5000,10000]],[[0,1,2],[1,3,2]],[[[1,5000,1]],[[0,5000,2]]],[0,1]),sort_keys=True))


if __name__=='__main__':main()
