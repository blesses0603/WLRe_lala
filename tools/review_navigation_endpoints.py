"""Bounded native endpoint-branch probe with synthetic managed ABI inputs.

This does not construct ABPath graphs, resolve nearest nodes or authorize movement.
Requires optional research-only Unicorn and pyelftools; no binary is bundled.
"""
import argparse
import io
import json
import struct
from tools.review_navigation_rotation import checked_bytes,IL2CPP_SHA


def run(path):
    raw=checked_bytes(path,IL2CPP_SHA)
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1,UC_ARM64_REG_X0,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC,UC_ARM64_REG_S0
    from elftools.elf.elffile import ELFFile
    with io.BytesIO(raw) as f:
     segs=[dict(s.header) for s in ELFFile(f).iter_segments() if s['p_type']=='PT_LOAD']
    def data(a,size):
     s=next(s for s in segs if s['p_vaddr']<=a and a+size<=s['p_vaddr']+s['p_filesz']);o=s['p_offset']+a-s['p_vaddr'];return raw[o:o+size]
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for addr in (0x24d2000,0x297c000,0x2d83000,0x379a000,0x37f3000,0x4c59000,0x4977000):u.mem_map(addr,0x1000)
    u.mem_map(0x6000000,0x20000)
    for addr,size in ((0x24d2a10,0x4fc),(0x297c43c,0x54),(0x2d83820,0x28),(0x379addc,4),(0x37f3360,5)):u.mem_write(addr,data(addr,size))
    u.mem_write(0x4c59603,b'\x01');u.mem_write(0x4977440,struct.pack('<Q',0x600f000));u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
    allowed=((0x24d2a10,0x24d2f0c),(0x297c43c,0x297c490),(0x2d83820,0x2d83848));visited=set()
    def guard(uc,address,size,user):
     if not any(a<=address<b for a,b in allowed):raise ValueError('Unsupported runtime branch '+hex(address))
     visited.add(address)
    u.hook_add(UC_HOOK_CODE,guard)
    # Path, List<GraphNode>, array and two node records. All are synthetic ABI inputs.
    u.mem_write(0x6001050,struct.pack('<Q',0x6002000));u.mem_write(0x6002010,struct.pack('<Q',0x6003000));u.mem_write(0x6002018,struct.pack('<I',2));u.mem_write(0x6003018,struct.pack('<Q',2));u.mem_write(0x6003020,struct.pack('<2Q',0x6004000,0x6004100))
    u.mem_write(0x600401c,struct.pack('<3i',1000,2000,3000));u.mem_write(0x600411c,struct.pack('<3i',4000,5000,6000))
    def call(start,end,mode,is_start):
     u.mem_write(0x60010f8,struct.pack('<3f',*start));u.mem_write(0x6001104,struct.pack('<3f',*end))
     for i,value in enumerate((0x6000000,0x6001000,mode,is_start,0x6009000,0x6009010)):u.reg_write(UC_ARM64_REG_X0+i,value)
     u.reg_write(UC_ARM64_REG_SP,0x601f000);u.reg_write(UC_ARM64_REG_LR,0x600a000)
     u.emu_start(0x24d2a10,0x600a000,count=2048)
     if u.reg_read(UC_ARM64_REG_PC)!=0x600a000:raise ValueError('Instruction budget')
     return [struct.unpack('<f',struct.pack('<I',u.reg_read(UC_ARM64_REG_S0+i)))[0] for i in range(3)]
    rows=[]
    for start,end in (((1,2,3),(4,5,6)),((10,0,10),(10,100,10)),((-100,50,75),(100,-50,-75))):
     for mode in (0,3):
      for is_start in (0,1):
       result=call(start,end,mode,is_start);expected=(start if is_start else end) if mode==3 else ((1,2,3) if is_start else (4,5,6))
       if max(abs(a-b) for a,b in zip(result,expected))>1e-6:raise ValueError('Unexpected endpoint result')
       rows.append(dict(start=start,end=end,mode=mode,is_start=bool(is_start),official_kernel_output=result))
    report=dict(cases=rows,source_sha256=IL2CPP_SHA,unique_instructions=len(visited),scope='Native Snap branch only, synthetic ABI state and supplied clamped points; not ABPath nearest-node calculation',can_send_packets=False)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    try:print(json.dumps(run(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
