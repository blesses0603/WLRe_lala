"""Official triangle vertex access and IntRect bounds on synthetic holder state.

Optional center execution uses an explicitly modeled external modf dependency.
Does not run the full BBTree caller or authorize paths.
"""
import argparse
import io
import json
import math
import random
import struct
from tools.review_navigation_rotation import checked_bytes,IL2CPP_SHA


def validate_inputs(vertices,indices):
    if not isinstance(vertices,list) or not 1<=len(vertices)<=4096:
        raise ValueError('Require bounded vertex array')
    if len(indices)!=3 or any(type(i) is not int or not 0<=i<len(vertices) for i in indices):
        raise ValueError('Invalid triangle indices')
    for v in vertices:
        if len(v)!=3 or any(type(x) is not int or abs(x)>10000000 for x in v):
            raise ValueError('Require bounded Int3 coordinates')


def modeled_modf(value):
    """Exact finite-domain contract model, NOT an official Android libm binary."""
    if not math.isfinite(value) or abs(value)>100000000:
        raise ValueError('Outside reviewed modf model domain')
    numerator,denominator=value.as_integer_ratio()
    integral=abs(numerator)//denominator
    integral=math.copysign(float(integral),value)
    fraction=math.copysign(abs(value-integral),value)
    return fraction,integral


def oracle(path,*,modeled_center=False):
    raw=checked_bytes(path,IL2CPP_SHA)
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1,UC_ARM64_REG_D0,UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC
    from elftools.elf.elffile import ELFFile
    with io.BytesIO(raw) as f:segments=[dict(s.header) for s in ELFFile(f).iter_segments() if s['p_type']=='PT_LOAD']
    def data(a,n):
        s=next(s for s in segments if s['p_vaddr']<=a and a+n<=s['p_vaddr']+s['p_filesz']);o=s['p_offset']+a-s['p_vaddr'];return raw[o:o+n]
    vm=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    ranges=((0x2832670,0x283284c),(0x2832338,0x28323ac),(0x2d8b75c,0x2d8b764),
            (0x27a12ec,0x27a1328),(0x24c6354,0x24c6388),(0x2a913cc,0x2a913d8),
            (0x2a91878,0x2a91948),(0x20d129c,0x20d12a8),(0x20d1494,0x20d14a0))
    if modeled_center:
        ranges+=((0x28325e8,0x2832670),(0x2d85b24,0x2d85b40),(0x2d86434,0x2d86658),(0xb125f0,0xb12600))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x4c5a000,0x4989000,0x4935000,0x4c5b000,0x498c000,0x4c5c000,0x37f3000,0x4923000}
    for p in pages:vm.mem_map(p,4096)
    vm.mem_map(0x6000000,0x200000)
    for a,b in ranges:vm.mem_write(a,data(a,b-a))
    def q(a,v):vm.mem_write(a,struct.pack('<Q',v))
    def w(a,v):vm.mem_write(a,struct.pack('<I',v))
    vm.mem_write(0x4c5aa85,b'\x01');vm.mem_write(0x4c5aa88,b'\x01');vm.mem_write(0x4c5b2f5,b'\x01')
    q(0x4989918,0x6010000);q(0x6010000,0x6010100);w(0x60101e0,1)
    q(0x60101b8,0x6010200);q(0x6010200,0x6010300);w(0x6010318,1);q(0x6010320,0x6020000)
    q(0x49356c0,0x6010400);q(0x6010400,0x6010500)
    q(0x6020000,0x6021000);vm.mem_write(0x602112a,struct.pack('<H',1))
    q(0x60210b0,0x6022000);q(0x6022000,0x6010500);w(0x6022008,0);q(0x6021138,0x27a12ec)
    q(0x60200e8,0x6023000);w(0x6023018,1);q(0x6023020,0x6024000);q(0x6024018,0x6030000)
    q(0x498c2b8,0x6010000)
    model_calls=[]
    if modeled_center:
        vm.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
        vm.mem_write(0x4c5c043,b'\x01')
        vm.mem_write(0x37f3af0,data(0x37f3af0,4))
        q(0x4923260,0x601e000)
    def guard(machine,address,size,user):
        if modeled_center and address==0x601e000:
            if vm.reg_read(UC_ARM64_REG_LR) not in (0x2d864b0,0x2d86530,0x2d865c8):
                raise ValueError('Unreviewed modf caller')
            destination=vm.reg_read(UC_ARM64_REG_X0)
            if not 0x61fe000<=destination<=0x61ffff8:raise ValueError('Invalid modf output pointer')
            value=struct.unpack('<d',struct.pack('<Q',vm.reg_read(UC_ARM64_REG_D0)))[0]
            fraction,integral=modeled_modf(value)
            vm.mem_write(destination,struct.pack('<d',integral))
            vm.reg_write(UC_ARM64_REG_D0,struct.unpack('<Q',struct.pack('<d',fraction))[0])
            model_calls.append(value)
            vm.reg_write(UC_ARM64_REG_PC,vm.reg_read(UC_ARM64_REG_LR))
            return
        if not any(a<=address<b for a,b in ranges):raise ValueError('Unverified runtime branch '+hex(address))
    vm.hook_add(UC_HOOK_CODE,guard)
    def execute(address,args):
        for i,value in enumerate(args):vm.reg_write(UC_ARM64_REG_X0+i,value & ((1<<64)-1))
        vm.reg_write(UC_ARM64_REG_SP,0x61ff000);vm.reg_write(UC_ARM64_REG_LR,0x601f000)
        vm.emu_start(address,0x601f000,count=10000)
        if vm.reg_read(UC_ARM64_REG_PC)!=0x601f000:raise ValueError('Instruction budget')
        return struct.pack('<2Q',vm.reg_read(UC_ARM64_REG_X0),vm.reg_read(UC_ARM64_REG_X1))
    def run(vertices,indices):
        validate_inputs(vertices,indices)
        w(0x6030018,len(vertices));vm.mem_write(0x6030020,b''.join(struct.pack('<3i',*v) for v in vertices))
        vm.mem_write(0x6000030,struct.pack('<3i',*indices))
        execute(0x2832670,(0x6000000,0x6000100,0x6000110,0x6000120))
        result=[list(struct.unpack('<3i',vm.mem_read(0x6000100+i*16,12))) for i in range(3)]
        x,y,z=result[0];execute(0x2a913cc,(0x6000200,x,z,x,z))
        for x,y,z in result[1:]:vm.mem_write(0x6000200,execute(0x2a91878,(0x6000200,x,z)))
        output=dict(vertices=result,bounds=list(struct.unpack('<4i',vm.mem_read(0x6000200,16))))
        if modeled_center:
            model_calls.clear()
            execute(0x28325e8,(0x6000000,))
            if len(model_calls)!=3:raise ValueError('Unexpected modf call count')
            output.update(center=list(struct.unpack('<3i',vm.mem_read(0x600001c,12))),modf_model_inputs=list(model_calls))
        return output
    return run


def vectors(path,*,modeled_center=False):
    call=oracle(path,modeled_center=modeled_center);rows=[]
    inputs=[[[0,0,0],[1000,0,0],[0,0,1000]],
                     [[-3000,1000,4000],[7000,-2000,-9000],[0,8000,0]],
                     [[10000000,-10000000,10000000],[-10000000,10000000,-10000000],[0,0,0]]]
    if modeled_center:
        rng=random.Random(1296)
        inputs.extend([[[rng.randint(-10000000,10000000) for _ in range(3)] for _ in range(3)] for _ in range(30)])
    for vertices in inputs:
        for indices in ([0,1,2],[2,0,1],[1,1,1]):
            result=call(vertices,indices);expected=[vertices[i] for i in indices]
            bounds=[min(v[0] for v in expected),min(v[2] for v in expected),max(v[0] for v in expected),max(v[2] for v in expected)]
            if result['vertices']!=expected or result['bounds']!=bounds:raise ValueError('Native vertex/bounds mismatch')
            if modeled_center:
                f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
                factor=struct.unpack('<f',bytes.fromhex('9faaaa3e'))[0]
                reference=[round(f32(f32(sum(v[k] for v in expected))*factor)) for k in range(3)]
                if result['center']!=reference:raise ValueError('Modeled-dependency center comparison failed')
            rows.append(dict(vertices=vertices,indices=indices,official_output=result))
    return dict(source_sha256=IL2CPP_SHA,cases=rows,can_send_packets=False,
                modeled_modf=modeled_center,scope='Synthetic single-tile holder; native vertex/bounds and optionally center with explicit finite modf model; not GetNearest')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--modeled-center',action='store_true',help='Explicitly model external modf; not an entirely official-binary oracle');args=parser.parse_args()
    try:print(json.dumps(vectors(args.libil2cpp,modeled_center=args.modeled_center),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
