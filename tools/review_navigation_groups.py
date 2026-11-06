"""Execute official hierarchy grouping on bounded synthetic triangle-node records.

This validates one group's traversal, not RecalculateAll, real graph initialization
or GetNearest. Optional Unicorn dependencies are isolated from the application.
"""
import argparse
import io
import json
import random
import struct
from tools.review_navigation_rotation import checked_bytes,IL2CPP_SHA


def validate_graph(adjacency,walkable,*,multiple=False):
    if not isinstance(adjacency,list) or not 1<=len(adjacency)<=(512 if multiple else 256):
        raise ValueError('Require bounded node count')
    if len(walkable)!=len(adjacency) or any(type(v) is not bool for v in walkable) or not walkable[0]:
        raise ValueError('Require Boolean flags and a walkable starting node')
    for i,neighbors in enumerate(adjacency):
        if not isinstance(neighbors,list) or any(type(j) is not int or not 0<=j<len(adjacency) or i==j for j in neighbors):
            raise ValueError('Invalid node references')
        if len(neighbors)!=len(set(neighbors)):raise ValueError('Duplicate references')


def oracle(path,*,multiple=False):
    raw=checked_bytes(path,IL2CPP_SHA)
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1,UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC
    from elftools.elf.elffile import ELFFile
    with io.BytesIO(raw) as f:segments=[dict(s.header) for s in ELFFile(f).iter_segments() if s['p_type']=='PT_LOAD']
    def data(a,n):
     s=next(s for s in segments if s['p_vaddr']<=a and a+n<=s['p_vaddr']+s['p_filesz']);o=s['p_offset']+a-s['p_vaddr'];return raw[o:o+n]
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    ranges=((0x2d93f00,0x2d93f70),(0x2a8ff80,0x2a90030),(0x2d83808,0x2d83814),(0x2d93f7c,0x2d93f88),(0x2d85198,0x2d853bc),(0x2d84a14,0x2d84a44),(0x17c10cc,0x17c1198),(0x20d129c,0x20d12a8),(0x1f51960,0x1f51984),(0x2a270e0,0x2a27120),(0x25371d0,0x253722c),(0x164c9d8,0x164ca18),(0x164cac8,0x164cad8),(0x2ce74f8,0x2ce758c),(0x20cda5c,0x20cda6c),(0xe005bc,0xe005c0),(0xe0fca4,0xe0fcac),(0x2d84edc,0x2d85194),(0x2d94558,0x2d945d0),(0x29d6340,0x29d63ac),(0x1f50780,0x1f507d4),(0x2d85d64,0x2d85f38),(0x29d66b0,0x29d6770),(0x29d6848,0x29d68f0),(0x29d6a34,0x29d6a60),(0x1f50ee0,0x1f50f18),(0xe00550,0xe00554),(0xe81860,0xe81864),(0xec1130,0xec1178))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x4c5c000,0x49b9000,0x49a0000,0x4929000,0x4953000,0x4c68000,0x37ed000,0x496e000,0x496f000,0x493f000,0x496a000,0x49a7000,0x498c000,0x498a000}
    for page in pages:u.mem_map(page,4096)
    u.mem_map(0x6000000,0x1000000)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    u.mem_write(0x37ed7c0,data(0x37ed7c0,8));u.mem_write(0x4c5c040,b'\x01');u.mem_write(0x4c5c03e,b'\x01')
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    for slot in (0x49b9ab8,0x49a09e0,0x4929c10,0x49530e8,0x496ec18,0x496f890,0x493fbe0):q(slot,0x6010000)
    q(0x6010000,0x6010100);q(0x6010120,0x6010200);q(0x60102c0,0x6010300);q(0x6010318,0x6010400);q(0x6010408,0x29d6a34)
    u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
    def guard(vm,address,size,user):
     if not any(a<=address<b for a,b in ranges):raise ValueError('Unverified branch '+hex(address))
    u.hook_add(UC_HOOK_CODE,guard)
    def execute(addr,x0,x1,x2=0):
     for reg,v in ((UC_ARM64_REG_X0,x0),(UC_ARM64_REG_X1,x1),(UC_ARM64_REG_X2,x2),(UC_ARM64_REG_SP,0x6fff000),(UC_ARM64_REG_LR,0x601f000)):u.reg_write(reg,v)
     u.emu_start(addr,0x601f000,count=2000000)
     if u.reg_read(UC_ARM64_REG_PC)!=0x601f000:raise ValueError('Instruction budget')
     return u.reg_read(UC_ARM64_REG_X0)
    def group(adjacency,walkable):
     validate_graph(adjacency,walkable)
     u.mem_write(0x6000000,bytes(0x5000))
     q(0x6000010,0x6060000);q(0x6000018,0x6061000)
     for arr,record in ((0x6060000,0x6002000),(0x6061000,0x6003000)):
      w(arr+0x18,2);q(arr+0x28,record)
     q(0x6000040,0x6062000);q(0x6062018,0x2d85d64);q(0x6062040,0x6000000)
     q(0x6063188,0x2d94558)
     q(0x6000048,0x6001000)
     for obj,arr in ((0x6001000,0x6020000),(0x6002000,0x6030000),(0x6003000,0x6040000)):
      q(obj+0x10,arr);w(arr+0x18,512)
     for i,neighbors in enumerate(adjacency):
      node=0x6050000+i*0x100;arr=0x6100000+i*0x2000
      q(node,0x6063000);w(node+0x14,int(walkable[i]));q(node+0x28,arr);w(arr+0x18,len(neighbors))
      for j,neighbor in enumerate(neighbors):q(arr+0x20+j*16,0x6050000+neighbor*0x100)
     execute(0x2d84edc,0x6000000,1,0x6050000)
     read=lambda a:struct.unpack('<I',u.mem_read(a,4))[0]
     count=read(0x6002018)
     if not 1<=count<=len(adjacency):raise ValueError('Invalid native child count')
     refs=[struct.unpack('<Q',u.mem_read(0x6030020+i*8,8))[0] for i in range(count)]
     if any(not 0x6050000<=p<0x6050000+len(adjacency)*0x100 or (p-0x6050000)%0x100 for p in refs):
      raise ValueError('Invalid native child pointer')
     children=[(p-0x6050000)//0x100 for p in refs]
     if len(set(children))!=count:raise ValueError('Duplicate native children')
     return dict(children=children,flags=[read(0x6050014+i*0x100) for i in range(len(adjacency))],queue_remaining=read(0x6001020))
    def grouped(adjacency,walkable):
        validate_graph(adjacency,walkable,multiple=True)
        n=len(adjacency)
        u.mem_write(0x6000000,bytes(0x5000))
        q(0x6000010,0x6070000);q(0x6000018,0x6073000)
        for arr in (0x6070000,0x6073000):w(arr+0x18,n+1)
        q(0x6000040,0x6062000);q(0x6062018,0x2d85d64);q(0x6062040,0x6000000)
        q(0x6063188,0x2d94558);q(0x6000048,0x6001000)
        q(0x6001010,0x6020000);w(0x6020018,512)
        # Registered int-specialized native methods, with preinitialized
        # comparer/static context; no Python search or deduplication callback.
        q(0x60103a0,0x6010500);q(0x6010508,0x1f51960);q(0x6010520,0x6010200)
        q(0x6010428,0x6010600);q(0x6010608,0x2a270e0);q(0x6010638,0x6010700)
        q(0x6010700,0x6010800);q(0x6010808,0x25371d0);q(0x6010838,0x6010900)
        q(0x6010900,0x6010a00);q(0x6010a08,0x164c9d8);q(0x6010a20,0x6014000)
        u.mem_write(0x6014132,b'\x01');q(0x60140c0,0x6015000);q(0x6015000,0x6016000)
        u.mem_write(0x6016132,b'\x01');q(0x60160b8,0x6017000);q(0x6017000,0x6018000)
        q(0x6018000,0x6019000);q(0x60191d8,0x2ce74f8);q(0x60191e0,0x601a000);q(0x601a020,0x6010200)
        for g in range(n+1):
            record=0x6800000+g*0x3000
            u.mem_write(record,bytes(0x2000))
            q(0x6070020+g*8,record);q(0x6073020+g*8,record+0x1100)
            q(record+0x10,record+0x100);w(record+0x118,256)
            q(record+0x1110,record+0x1200);w(record+0x1218,512)
        for i,neighbors in enumerate(adjacency):
            node=0x6080000+i*0x100;arr=0x6100000+i*0x2000
            q(node,0x6063000);w(node+0x14,int(walkable[i]));q(node+0x28,arr);w(arr+0x18,len(neighbors))
            for j,neighbor in enumerate(neighbors):q(arr+0x20+j*16,0x6080000+neighbor*0x100)
        read=lambda a:struct.unpack('<I',u.mem_read(a,4))[0]
        groups=[]
        # Explicit deterministic test root order, not RecalculateAll's iteration.
        for i in range(n):
            if not walkable[i] or (read(0x6080014+i*0x100)>>1)&0x1ffff:continue
            g=len(groups)+1
            execute(0x2d84edc,0x6000000,g,0x6080000+i*0x100)
            record=0x6800000+g*0x3000;count=read(record+0x18)
            if not 1<=count<=256:raise ValueError('Invalid group size')
            refs=[struct.unpack('<Q',u.mem_read(record+0x120+j*8,8))[0] for j in range(count)]
            if any(not 0x6080000<=p<0x6080000+n*0x100 or (p-0x6080000)%0x100 for p in refs):raise ValueError('Invalid group pointer')
            groups.append([(p-0x6080000)//0x100 for p in refs])
        connections=[[]]
        for g in range(1,len(groups)+1):
            record=0x6800000+g*0x3000;count=read(record+0x1118)
            if count>len(groups):raise ValueError('Invalid group link count')
            connections.append(list(struct.unpack('<'+'I'*count,u.mem_read(record+0x1220,count*4))))
        # Keep native groups/connections in this VM and run native Area fill.
        for slot in (0x496ae30,0x49a7608,0x498c2b8):q(slot,0x6010000)
        w(0x60101e0,1);u.mem_write(0x4c5c03d,b'\x01')
        size=len(groups)+1
        w(0x6073018,size);q(0x6000020,0x67f0000);w(0x67f0018,size)
        q(0x6000068,0x67e0000);u.mem_write(0x67e0000,bytes(0x100))
        q(0x67e0010,0x67e1000);w(0x67e1018,1024)
        execute(0x2d85198,0x6000000,0)
        areas=[execute(0x2d84a14,0x6000000,i)&0xffffffff for i in range(size)]
        area_output=dict(areas=areas,component_count_including_reserved_zero=read(0x60000a0),version=read(0x6000030))
        u.mem_write(0x4c5c0a8,b'\x01');q(0x498a430,0x601b000);q(0x601b000,0x601b100)
        w(0x601b1e0,1);q(0x601b1b8,0x601b300);q(0x601b318,0x601b400);q(0x601b4b8,0x6000000)
        node_areas=[execute(0x2d93f00,0x6080000+i*0x100,0)&0xffffffff for i in range(n)]
        u.mem_write(0x67d0000,bytes(0x100));u.mem_write(0x67d0014,b'\x01');u.mem_write(0x67d001c,b'\x01\x01')
        suitable={}
        for target in (0,1,-1):
            w(0x67d0018,target&0xffffffff)
            suitable[str(target)]=[bool(execute(0x2a8ff80,0x67d0000,0x6080000+i*0x100)&0xffffffff) for i in range(n)]

        return dict(groups=groups,connections=connections,flags=[read(0x6080014+i*0x100) for i in range(n)],queue_remaining=read(0x6001020),native_area_output=area_output,native_node_areas=node_areas,native_area_suitable=suitable)

    return grouped if multiple else group


def vectors(path):
    call=oracle(path);cases=[]
    for n in (1,2,4,16,64,256):
        chain=[[j for j in (i-1,i+1) if 0<=j<n] for i in range(n)]
        cases.append((chain,[True]*n))
        if n>2:cases.append((chain,[i!=n//2 for i in range(n)]))
    cases.append(([[1,2,3],[0],[0],[0]],[True]*4))
    cases.append(([[1],[2],[0],[]],[True]*4))
    rng=random.Random(1296)
    for n in (8,32,128):
        cases.append(([[j for j in range(n) if j!=i and rng.random()<.08] for i in range(n)], [True]+[rng.random()>.15 for _ in range(n-1)]))
    rows=[]
    for adjacency,walkable in cases:
        result=call(adjacency,walkable)
        expected=[0];seen={0}
        for i in expected:
            for j in adjacency[i]:
                if walkable[j] and j not in seen:seen.add(j);expected.append(j)
        flags=[int(w)+(2 if i in seen else 0) for i,w in enumerate(walkable)]
        if result!=dict(children=expected,flags=flags,queue_remaining=0):
            raise ValueError('Native grouping disagrees with independent traversal')
        rows.append(dict(adjacency=adjacency,walkable=walkable,official_output=result))
    return dict(source_sha256=IL2CPP_SHA,cases=rows,can_send_packets=False,
                scope='One native group on synthetic node/vtable/delegate records, preallocated capacity and inactive GC; not RecalculateAll or GetNearest')


def multiple_vectors(path):
    from tools.review_navigation_areas import oracle as area_oracle
    build=oracle(path,multiple=True);area=area_oracle(path);cases=[]
    for n in (257,300,512):
        cases.append(([[j for j in (i-1,i+1) if 0<=j<n] for i in range(n)],[True]*n))
    cases.append(([[] for _ in range(32)],[True]*32))
    cases.append(([[j for j in (i-1,i+1) if 0<=j<512] for i in range(512)],[i!=300 for i in range(512)]))
    for n in (257,300,512):
        cases.append(([[(i-1)%n,(i+1)%n] for i in range(n)],[True]*n))
    cases.append(([[j for j in range(300) if j!=i and (j-i)%300 in (1,2,298,299)] for i in range(300)],[True]*300))
    rows=[]
    for adjacency,walkable in cases:
        output=build(adjacency,walkable)
        assignments=[0]*len(adjacency);groups=[];links=[[]]
        for start in range(len(adjacency)):
            if not walkable[start] or assignments[start]:continue
            g=len(groups)+1;children=[start];assignments[start]=g;neighbors=[]
            for node in children:
                for nxt in adjacency[node]:
                    assigned=assignments[nxt]
                    if assigned and assigned!=g:
                        if assigned not in neighbors:neighbors.append(assigned)
                    elif not assigned and walkable[nxt] and len(children)<256:
                        assignments[nxt]=g;children.append(nxt)
            groups.append(children);links.append(neighbors)
            for other in neighbors:links[other].append(g)
        expected=dict(groups=groups,connections=links,flags=[int(w)+(assignments[i]<<1) for i,w in enumerate(walkable)],queue_remaining=0)
        areas=area(output['connections'])
        expected['native_area_output']=areas
        node_areas=[areas['areas'][g] for g in assignments]
        expected['native_node_areas']=node_areas
        expected['native_area_suitable']={str(target):[w and (target==-1 or node_areas[i]==target) for i,w in enumerate(walkable)] for target in (0,1,-1)}
        if output!=expected:raise ValueError('Multi-group native comparison failed')
        rows.append(dict(adjacency=adjacency,walkable=walkable,official_output=output,official_area_output=areas))
    return dict(source_sha256=IL2CPP_SHA,cases=rows,
                can_send_packets=False,scope='Native grouping/deduplication and FloodFill in one synthetic VM state, independently cross-checked Area output; not RecalculateAll/GetNearest')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--multiple',action='store_true');args=parser.parse_args()
    try:print(json.dumps((multiple_vectors if args.multiple else vectors)(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
