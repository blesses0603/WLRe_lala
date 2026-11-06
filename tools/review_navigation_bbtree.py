"""Bounded official BBTree internal-builder oracle, without live graph activation.

Synthetic preallocated ABI records and opaque node references; no GetNearest claim.
"""
import argparse
import io
import json
import struct
from tools.review_navigation_rotation import checked_bytes,IL2CPP_SHA


def validate_inputs(rects,centers):
    if not 1<=len(rects)<=512 or len(centers)!=len(rects):raise ValueError('Invalid tree input count')
    for rect,center in zip(rects,centers):
        if len(rect)!=4 or len(center)!=3 or any(type(v) is not int or abs(v)>10000000 for v in (*rect,*center)):
            raise ValueError('Require bounded integer rectangle/center inputs')
        if rect[0]>rect[2] or rect[1]>rect[3]:raise ValueError('Inverted rectangle')


def validate_tree(result,rects):
    boxes=result['boxes'];refs=result['leaf_references'];seen=set()
    if sorted(j for j in refs if j is not None)!=list(range(len(rects))):
        raise ValueError('Native node references were lost or duplicated')
    def visit(i):
        if not 0<=i<len(boxes) or i in seen:raise ValueError('Invalid native tree links')
        seen.add(i);box=boxes[i];offset,left,right=box[4:]
        if offset>=0:
            if left!=-1 or right!=-1 or offset%4 or offset+4>len(refs):raise ValueError('Invalid native leaf')
            slots=refs[offset:offset+4]
            ids=[j for j in slots if j is not None]
            if slots!=ids+[None]*(4-len(ids)):raise ValueError('Invalid native leaf padding')
            if not ids or any(not 0<=j<len(rects) for j in ids):raise ValueError('Invalid native node reference')
            source=[rects[j] for j in ids]
        else:
            if offset!=-1:raise ValueError('Invalid internal box')
            source=[visit(left),visit(right)]
        expected=[min(r[0] for r in source),min(r[1] for r in source),max(r[2] for r in source),max(r[3] for r in source)]
        if box[:4]!=expected:raise ValueError('Native box does not bound its children')
        return expected
    visit(result['root'])
    if len(seen)!=len(boxes):raise ValueError('Unreachable native box')


def oracle(path):
    raw=checked_bytes(path,IL2CPP_SHA)
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1,UC_ARM64_REG_X0,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC,UC_ARM64_REG_W0
    from elftools.elf.elffile import ELFFile
    with io.BytesIO(raw) as f:segments=[dict(s.header) for s in ELFFile(f).iter_segments() if s['p_type']=='PT_LOAD']
    def data(a,n):
     s=next(s for s in segments if s['p_vaddr']<=a and a+n<=s['p_vaddr']+s['p_filesz']);o=s['p_offset']+a-s['p_vaddr'];return raw[o:o+n]
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    ranges=((0x2842cd4,0x2843518),(0x24c3e80,0x24c3e98),(0x20d129c,0x20d12a8),(0x20d1494,0x20d14a0),(0xe00550,0xe00554),(0xe81860,0xe81864),(0xec1130,0xec1178),(0xe006a0,0xe006a4),(0xe5bcdc,0xe5bd08),(0xe5bdb4,0xe5bdc8),(0xe9a72c,0xe9a760),(0xe9afc4,0xe9afe8))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x4c5a000,0x498c000,0x49a6000,0x4c68000}
    for page in pages:u.mem_map(page,4096)
    u.mem_map(0x6000000,0x400000)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    u.mem_write(0x4c5aae1,b'\x01\x01');u.mem_write(0x4c5aae4,b'\x01');u.mem_write(0x498c2b8,struct.pack('<Q',0x6010000));u.mem_write(0x6010000,struct.pack('<Q',0x6010100));u.mem_write(0x60101e0,struct.pack('<I',1))
    u.mem_write(0x6011040,struct.pack('<Q',0x6012000));u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20);visited=set()
    def guard(vm,address,size,user):
     if not any(a<=address<b for a,b in ranges):raise ValueError('Unverified runtime branch '+hex(address))
     visited.add(address)
    u.hook_add(UC_HOOK_CODE,guard)
    def run(rects,centers):
     validate_inputs(rects,centers);n=len(rects)
     u.mem_write(0x6000000,bytes(0x100));u.mem_write(0x6000010,struct.pack('<2Q',0x6020000,0x6040000))
     for ptr,count in ((0x6020000,2048),(0x6040000,2048),(0x6050000,n),(0x6052000,n),(0x6054000,n)):
      u.mem_write(ptr,bytes(0x20));u.mem_write(ptr+0x18,struct.pack('<Q',count))
     u.mem_write(0x6040000,struct.pack('<Q',0x6011000))
     u.mem_write(0x6052020,struct.pack('<'+'i'*n,*range(n)));u.mem_write(0x6054020,b''.join(struct.pack('<4i',*r) for r in rects))
     for i,center in enumerate(centers):
      node=0x6060000+i*0x100;u.mem_write(node,struct.pack('<Q',0x6012000));u.mem_write(node+0x1c,struct.pack('<3i',*center));u.mem_write(0x6050020+i*8,struct.pack('<Q',node))
     for i,value in enumerate((0x6000000,0x6050000,0x6052000,0x6054000,0,n,0)):u.reg_write(UC_ARM64_REG_X0+i,value)
     u.reg_write(UC_ARM64_REG_SP,0x63ff000);u.reg_write(UC_ARM64_REG_LR,0x601f000);u.emu_start(0x2842f6c,0x601f000,count=3000000)
     if u.reg_read(UC_ARM64_REG_PC)!=0x601f000:raise ValueError('Instruction ceiling')
     count,leaves=struct.unpack('<2I',u.mem_read(0x6000020,8))
     if not 0<count<2048 or not 0<leaves<=512:raise ValueError('Invalid native tree size')
     boxes=[list(struct.unpack('<7i',u.mem_read(0x6020020+i*28,28))) for i in range(count)]
     refs=list(struct.unpack('<'+'Q'*(leaves*4),u.mem_read(0x6040020,leaves*4*8)));
     if any(x and (not 0x6060000<=x<0x6060000+n*0x100 or (x-0x6060000)%0x100) for x in refs):
      raise ValueError('Invalid native node pointer')
     refs=[None if x==0 else (x-0x6060000)//0x100 for x in refs]
     found=sorted(x for x in refs if x is not None)
     if found!=list(range(n)):raise ValueError('Native node references were lost or duplicated')
     return dict(boxes=boxes,leaf_references=refs,root=u.reg_read(UC_ARM64_REG_W0))
    return run


def vectors(path):
    build=oracle(path);rows=[]
    for n in (1,4,5,8,17,64,256,512):
        rects=[(i*10,i%3*10,i*10+9,i%3*10+8) for i in range(n)]
        centers=[(a+4,0,b+4) for a,b,c,d in rects]
        result=build(rects,centers);validate_tree(result,rects)
        rows.append(dict(rects=rects,centers=centers,official_tree=result))
    rects=[(-10,-10,10,10)]*65;centers=[(0,0,0)]*65
    result=build(rects,centers);validate_tree(result,rects)
    rows.append(dict(rects=rects,centers=centers,official_tree=result))
    return dict(source_sha256=IL2CPP_SHA,cases=rows,can_send_packets=False,
                scope='Internal native BBTree builder with synthetic initialized ABI, preallocated buffers and inactive GC marking; not full graph/GetNearest')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    try:print(json.dumps(vectors(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
