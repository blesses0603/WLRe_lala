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


def validate_graph(adjacency,walkable):
    if not isinstance(adjacency,list) or not 1<=len(adjacency)<=256:
        raise ValueError('Require 1..256 nodes')
    if len(walkable)!=len(adjacency) or any(type(v) is not bool for v in walkable) or not walkable[0]:
        raise ValueError('Require Boolean flags and a walkable starting node')
    for i,neighbors in enumerate(adjacency):
        if not isinstance(neighbors,list) or any(type(j) is not int or not 0<=j<len(adjacency) or i==j for j in neighbors):
            raise ValueError('Invalid node references')
        if len(neighbors)!=len(set(neighbors)):raise ValueError('Duplicate references')


def oracle(path):
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
    u.mem_map(0x6000000,0x400000)
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
     for reg,v in ((UC_ARM64_REG_X0,x0),(UC_ARM64_REG_X1,x1),(UC_ARM64_REG_X2,x2),(UC_ARM64_REG_SP,0x63ff000),(UC_ARM64_REG_LR,0x601f000)):u.reg_write(reg,v)
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
    return group


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


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    try:print(json.dumps(vectors(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
