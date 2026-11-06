"""Optional offline ARM64 math oracle; never executes host code or enables movement.

Requires research-only unicorn==2.1.4 and pyelftools. Supply the exact reviewed
public official APK libraries; they are not bundled or downloaded by this tool.
Outputs synthetic test vectors, not a complete client path acceptance result.
"""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import random
import struct

UNITY_SHA='dab8b8d67f215b8f8c83870a3ef4b118e5a0e0e2c225eb1f48e23ba9f1bc582c'
IL2CPP_SHA='7798c9aaa6986ee200deacf9816a5d2f17a606944aa4a56dd06bfa1acb344636'


def checked_bytes(path,expected):
    path=Path(path)
    if path.stat().st_size>96*1024*1024:raise ValueError('Library exceeds research size limit')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Unreviewed official library digest')
    return raw


def validate_vector(values,size):
    if len(values)!=size or any(not math.isfinite(v) or abs(v)>1e6 for v in values):
        raise ValueError('Invalid or out-of-range research vector')


def from_to_oracle(path):
    raw=checked_bytes(path,UNITY_SHA)
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1,UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC
    from elftools.elf.elffile import ELFFile
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0,0x2000000)
    with io.BytesIO(raw) as f:
     elf=ELFFile(f)
     for s in elf.iter_segments():
      if s['p_type']=='PT_LOAD':u.mem_write(s['p_vaddr'],s.data())
     for s in elf.iter_sections():
      if s['sh_type']=='SHT_RELA':
       for r in s.iter_relocations():
        if r['r_info_type']==1027:u.mem_write(r['r_offset'],struct.pack('<Q',r['r_addend']))
    u.mem_map(0x6000000,0x20000);u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
    allowed=((0x17b6a4,0x17b6c0),(0xb493e4,0xb494c8),(0xb51c0c,0xb51e20),(0xb48e7c,0xb49030))
    def guard(uc,address,size,user):
     if not any(a<=address<b for a,b in allowed):raise ValueError('Unreviewed instruction '+hex(address))
    u.hook_add(UC_HOOK_CODE,guard)
    def call(a,b):
     validate_vector(a,3);validate_vector(b,3)
     u.mem_write(0x6000000,struct.pack('<3f',*a));u.mem_write(0x6000010,struct.pack('<3f',*b));u.mem_write(0x6000020,bytes(16))
     u.reg_write(UC_ARM64_REG_X0,0x6000000);u.reg_write(UC_ARM64_REG_X1,0x6000010);u.reg_write(UC_ARM64_REG_X2,0x6000020)
     u.reg_write(UC_ARM64_REG_SP,0x601f000);u.reg_write(UC_ARM64_REG_LR,0x6001000)
     u.emu_start(0x17b6a4,0x6001000,count=2048)
     if u.reg_read(UC_ARM64_REG_PC)!=0x6001000:raise ValueError('Official FromToRotation exceeded instruction budget')
     return list(struct.unpack('<4f',u.mem_read(0x6000020,16)))
    return call


def multiply_oracle(path):
    raw=checked_bytes(path,IL2CPP_SHA)
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1,UC_ARM64_REG_S0,UC_ARM64_REG_LR,UC_ARM64_REG_PC
    from elftools.elf.elffile import ELFFile
    with io.BytesIO(raw) as f:
     elf=ELFFile(f);seg=next(s for s in elf.iter_segments() if s['p_type']=='PT_LOAD' and s['p_vaddr']<=0x30c66a4<s['p_vaddr']+s['p_filesz']);offset=seg['p_offset']+0x30c66a4-seg['p_vaddr']
    code=raw[offset:offset+0xa4];u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0x30c0000,0x10000);u.mem_write(0x30c66a4,code);u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
    def call(q,v):
     validate_vector(q,4);validate_vector(v,3)
     for i,n in enumerate((*q,*v)):u.reg_write(UC_ARM64_REG_S0+i,struct.unpack('<I',struct.pack('<f',n))[0])
     u.reg_write(UC_ARM64_REG_LR,0x30c6748);u.emu_start(0x30c66a4,0x30c6748,count=128)
     if u.reg_read(UC_ARM64_REG_PC)!=0x30c6748:raise ValueError('Official multiply exceeded instruction budget')
     return [struct.unpack('<f',struct.pack('<I',u.reg_read(UC_ARM64_REG_S0+i)))[0] for i in range(3)]
    return call


def reference_rotate(q,v):
    x,y,z,w=q;vx,vy,vz=v
    return [(1-2*(y*y+z*z))*vx+2*(x*y-z*w)*vy+2*(x*z+y*w)*vz,
            2*(x*y+z*w)*vx+(1-2*(x*x+z*z))*vy+2*(y*z-x*w)*vz,
            2*(x*z-y*w)*vx+2*(y*z+x*w)*vy+(1-2*(x*x+y*y))*vz]


def vectors(unity,il2cpp):
    between=from_to_oracle(unity);rotate=multiply_oracle(il2cpp)
    rng=random.Random(1296)
    cases=[((1,0,0),(0,1,0)),((1,0,0),(-1,0,0)),((0,1,0),(0,-1,0)),
           ((0,0,1),(0,0,-1)),((1,2,3),(1,2,3)),((0,0,0),(1,0,0)),
           ((1,0,0),(0,0,0)),((1,0,0),(1,1e-7,0))]
    cases += [(tuple(rng.uniform(-1,1) for _ in range(3)),tuple(rng.uniform(-1,1) for _ in range(3))) for _ in range(128)]
    from_to=[]
    for start,end in cases:
        q=between(start,end);an=math.sqrt(sum(v*v for v in start));bn=math.sqrt(sum(v*v for v in end))
        error=0.
        if min(an,bn)>1e-5:
            transformed=rotate(q,tuple(v/an for v in start))
            error=max(abs(v-t/bn) for v,t in zip(transformed,end))
            if error>=1e-4:raise ValueError('Official rotation direction comparison failed')
        elif q!=[0,0,0,1]:raise ValueError('Unexpected zero-vector result')
        from_to.append(dict(start=start,end=end,quaternion=q,direction_error=error))
    rng=random.Random(1296);multiply=[]
    quaternions=[(0,0,0,1),(0,math.sqrt(.5),0,math.sqrt(.5)),(1,0,0,0)]
    quaternions += [tuple(rng.uniform(-1,1) for _ in range(4)) for _ in range(64)]
    for q in quaternions:
        norm=math.sqrt(sum(x*x for x in q));q=tuple(x/norm for x in q)
        for v in ((1,0,0),(0,1,0),(0,0,1),(123.25,-42.5,0.125)):
            result=rotate(q,v);expected=reference_rotate(q,v)
            error=max(abs(a-b) for a,b in zip(result,expected))
            if error>=1e-4:raise ValueError('Official quaternion multiplication comparison failed')
            multiply.append(dict(quaternion=q,vector=v,result=result,max_error=error))
    return dict(unity_sha256=UNITY_SHA,il2cpp_sha256=IL2CPP_SHA,
                from_to=from_to,multiply=multiply,can_send_packets=False,
                scope='Pure official math under ARM64 emulation; not a complete path or live client oracle')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libunity',required=True);parser.add_argument('--libil2cpp',required=True)
    args=parser.parse_args()
    try:print(json.dumps(vectors(args.libunity,args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
