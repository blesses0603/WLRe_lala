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
    ranges=((0x2d84edc,0x2d85194),(0x2d94558,0x2d945d0),(0x29d6340,0x29d63ac),(0x1f50780,0x1f507d4),(0x2d85d64,0x2d85f38),(0x29d66b0,0x29d6770),(0x29d6848,0x29d68f0),(0x29d6a34,0x29d6a60),(0x1f50ee0,0x1f50f18),(0xe00550,0xe00554),(0xe81860,0xe81864),(0xec1130,0xec1178))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x4c5c000,0x49b9000,0x49a0000,0x4929000,0x4953000,0x4c68000,0x37ed000,0x496e000,0x496f000,0x493f000}
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
     u.emu_start(addr,0x601f000,count=100000)
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
        # Nonempty Contains requires an unresolved generic IndexOf context.
        # Stop explicitly; never silently substitute a local deduplication result.
        q(0x60103a0,0x6010500);q(0x6010508,0x601d000)
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
        return dict(groups=groups,connections=connections,flags=[read(0x6080014+i*0x100) for i in range(n)],queue_remaining=read(0x6001020))
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
        if output!=expected:raise ValueError('Multi-group native comparison failed')
        areas=area(output['connections'])
        rows.append(dict(adjacency=adjacency,walkable=walkable,official_output=output,official_area_output=areas))
    # A cycle crosses the boundary more than once; unresolved generic Contains
    # dispatch must stop, rather than accepting guessed deduplication behavior.
    n=300;cycle=[[(i-1)%n,(i+1)%n] for i in range(n)]
    try:build(cycle,[True]*n)
    except ValueError as error:
        if str(error)!='Unverified branch 0x601d000':raise
        rejection=str(error)
    else:raise ValueError('Unverified cross-group deduplication was accepted')
    return dict(source_sha256=IL2CPP_SHA,cases=rows,expected_unresolved_dedup_rejection=rejection,
                can_send_packets=False,scope='Native group calls in synthetic deterministic root order, composed with native FloodFill; unresolved repeated cross-group links reject; not RecalculateAll/GetNearest')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--multiple',action='store_true');args=parser.parse_args()
    try:print(json.dumps((multiple_vectors if args.multiple else vectors)(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
