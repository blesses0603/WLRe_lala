"""Bounded official FloodFill/Area-table oracle on synthetic hierarchy adjacency.

This does not reconstruct hierarchy groups from triangle nodes or initialize BBTree.
"""
import argparse
import io
import json
import random
import struct
from tools.review_navigation_rotation import checked_bytes,IL2CPP_SHA


def validate_adjacency(adjacency):
    if not isinstance(adjacency,list) or not 1<=len(adjacency)<=257 or adjacency[0]!=[]:
        raise ValueError('Require reserved empty node zero and at most 256 hierarchy nodes')
    for i,neighbors in enumerate(adjacency):
        if not isinstance(neighbors,list) or any(type(j) is not int for j in neighbors) or len(neighbors)!=len(set(neighbors)):raise ValueError('Invalid adjacency')
        for j in neighbors:
            if type(j) is not int or not 0<j<len(adjacency) or i==j or i not in adjacency[j]:
                raise ValueError('Probe requires bounded reciprocal hierarchy links')


def oracle(path):
    raw=checked_bytes(path,IL2CPP_SHA)
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1,UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC,UC_ARM64_REG_W0
    from elftools.elf.elffile import ELFFile
    with io.BytesIO(raw) as source:segments=[dict(s.header) for s in ELFFile(source).iter_segments() if s['p_type']=='PT_LOAD']
    def data(a,size):
        s=next(s for s in segments if s['p_vaddr']<=a and a+size<=s['p_vaddr']+s['p_filesz']);o=s['p_offset']+a-s['p_vaddr'];return raw[o:o+size]
    vm=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    ranges=((0x2d85198,0x2d853bc),(0x2d84a14,0x2d84a44),(0x17c10cc,0x17c1198),(0x1f50780,0x1f507d4),(0x20d129c,0x20d12a8))
    pages={a&~4095 for a,b in ranges}|{0x4c5c000,0x496a000,0x49a7000,0x493f000,0x498c000}
    for page in pages:vm.mem_map(page,4096)
    vm.mem_map(0x6000000,0x200000)
    for a,b in ranges:vm.mem_write(a,data(a,b-a))
    vm.mem_write(0x4c5c03d,b'\x01')
    for slot in (0x496ae30,0x49a7608,0x493fbe0,0x498c2b8):vm.mem_write(slot,struct.pack('<Q',0x6010000))
    vm.mem_write(0x6010000,struct.pack('<Q',0x6010100));vm.mem_write(0x60101e0,struct.pack('<I',1))
    vm.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
    def guard(machine,address,size,user):
        if not any(a<=address<b for a,b in ranges):raise ValueError('Unverified runtime call '+hex(address))
    vm.hook_add(UC_HOOK_CODE,guard)
    def execute(address,x1=0):
        vm.reg_write(UC_ARM64_REG_X0,0x6000000);vm.reg_write(UC_ARM64_REG_X1,x1)
        vm.reg_write(UC_ARM64_REG_SP,0x61ff000);vm.reg_write(UC_ARM64_REG_LR,0x601f000)
        vm.emu_start(address,0x601f000,count=2000000)
        if vm.reg_read(UC_ARM64_REG_PC)!=0x601f000:raise ValueError('Instruction budget exceeded')
        return vm.reg_read(UC_ARM64_REG_W0)
    def call(adjacency):
        validate_adjacency(adjacency);n=len(adjacency)
        vm.mem_write(0x6000000,bytes(0x100))
        vm.mem_write(0x6000018,struct.pack('<2Q',0x6002000,0x6001000));vm.mem_write(0x6000068,struct.pack('<Q',0x6004000))
        vm.mem_write(0x6001018,struct.pack('<Q',n));vm.mem_write(0x6002018,struct.pack('<Q',n))
        vm.mem_write(0x6004010,struct.pack('<QII',0x6005000,0,0));vm.mem_write(0x6005018,struct.pack('<Q',1024))
        for i,neighbors in enumerate(adjacency):
            record=0x6020000+i*0x1000;array=record+0x100
            vm.mem_write(0x6002020+i*8,struct.pack('<Q',record));vm.mem_write(record+0x10,struct.pack('<QI',array,len(neighbors)))
            vm.mem_write(array+0x18,struct.pack('<Q',len(neighbors)))
            if neighbors:vm.mem_write(array+0x20,struct.pack('<'+'i'*len(neighbors),*neighbors))
        execute(0x2d85198)
        areas=[execute(0x2d84a14,i) for i in range(n)]
        count=struct.unpack('<I',vm.mem_read(0x60000a0,4))[0];version=struct.unpack('<I',vm.mem_read(0x6000030,4))[0]
        return dict(areas=areas,component_count_including_reserved_zero=count,version=version)
    return call


def vectors(path):
    call=oracle(path);rng=random.Random(1296);cases=[[[]],[[],[],[]],[[],[2],[1],[]],[[],[2,3],[1,3],[1,2]]]
    for n in (4,8,16,32,64):
        for density in (.05,.2,.5):
            adj=[[] for _ in range(n+1)]
            for i in range(1,n+1):
                for j in range(i+1,n+1):
                    if rng.random()<density:adj[i].append(j);adj[j].append(i)
            cases.append(adj)
    rows=[]
    for adjacency in cases:
        result=call(adjacency);expected=[0]*len(adjacency);count=0
        for start in range(1,len(adjacency)):
            if expected[start]:continue
            count+=1;todo=[start];expected[start]=count
            while todo:
                for j in adjacency[todo.pop()]:
                    if not expected[j]:expected[j]=count;todo.append(j)
        if result['areas']!=expected or result['component_count_including_reserved_zero']!=count+1 or result['version']!=1:
            raise ValueError('Official component table comparison failed')
        rows.append(dict(adjacency=adjacency,official_output=result))
    return dict(source_sha256=IL2CPP_SHA,cases=rows,can_send_packets=False,scope='Synthetic hierarchy adjacency; not official triangle-to-hierarchy or BBTree initialization')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    try:print(json.dumps(vectors(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
