"""Offline oracle for default native traversal and nearest-node suitability.

Synthetic ABI records, no custom provider or connected-area reconstruction.
Requires optional Unicorn/pyelftools; only the reviewed official binary is allowed.
"""
import argparse
import io
import json
import struct
from tools.review_navigation_rotation import checked_bytes,IL2CPP_SHA


def oracle(path):
    raw=checked_bytes(path,IL2CPP_SHA)
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1,UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC,UC_ARM64_REG_W0
    from elftools.elf.elffile import ELFFile
    with io.BytesIO(raw) as source:
        segments=[dict(s.header) for s in ELFFile(source).iter_segments() if s['p_type']=='PT_LOAD']
    def data(address,size):
        segment=next(s for s in segments if s['p_vaddr']<=address and address+size<=s['p_vaddr']+s['p_filesz'])
        offset=segment['p_offset']+address-segment['p_vaddr']
        return raw[offset:offset+size]
    machine=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for address in (0x2d95000,0x2a8f000,0x2a90000,0x2d83000,0x2d93000,0x4c5c000):machine.mem_map(address,4096)
    machine.mem_map(0x6000000,0x20000)
    ranges=((0x2d95850,0x2d95938),(0x2a8ff50,0x2a90030),(0x2d83808,0x2d83814),(0x2d93f7c,0x2d93f88))
    for start,end in ranges:machine.mem_write(start,data(start,end-start))
    machine.mem_write(0x4c5c0b6,b'\x01')
    machine.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
    def guard(vm,address,size,user):
        if not any(a<=address<b for a,b in ranges):raise ValueError('Unverified native runtime branch '+hex(address))
        if 0x2d95888<=address<0x2d958d0:raise ValueError('Custom traversal provider is not verified')
    machine.hook_add(UC_HOOK_CODE,guard)
    def evaluate(flags,mask,*,kind='traverse',graph_index=0,constrain_walkability=True,walkable=True,constrain_tags=True,area=None,provider=None):
        if type(flags) is not int or not 0<=flags<=0xffffffff or type(mask) is not int or not 0<=mask<=0xffffffff:
            raise ValueError('Flags/mask must be UInt32')
        if area is not None or provider is not None:raise ValueError('Runtime area/provider state has not been verified')
        if kind not in ('traverse','suitable','graph'):raise ValueError('Unknown native probe')
        if type(graph_index) is not int or not 0<=graph_index<32:raise ValueError('Graph index outside verified range')
        machine.mem_write(0x6000000,bytes(0x200))
        machine.mem_write(0x6001014,struct.pack('<I',flags))
        if kind=='traverse':
            machine.mem_write(0x60000ac,struct.pack('<I',mask));entry=0x2d95850
        else:
            machine.mem_write(0x6000010,struct.pack('<I',mask))
            machine.mem_write(0x6000018,struct.pack('<i',-1))
            machine.mem_write(0x600001c,bytes((bool(constrain_walkability),bool(walkable),0,bool(constrain_tags))))
            machine.mem_write(0x6000020,struct.pack('<I',mask))
            entry=0x2a8ff80 if kind=='suitable' else 0x2a8ff50
        machine.reg_write(UC_ARM64_REG_X0,0x6000000)
        machine.reg_write(UC_ARM64_REG_X1,graph_index if kind=='graph' else 0x6001000)
        machine.reg_write(UC_ARM64_REG_SP,0x601f000);machine.reg_write(UC_ARM64_REG_LR,0x600f000)
        machine.emu_start(entry,0x600f000,count=512)
        if machine.reg_read(UC_ARM64_REG_PC)!=0x600f000:raise ValueError('Native instruction budget exceeded')
        return bool(machine.reg_read(UC_ARM64_REG_W0))
    return evaluate


def vectors(path):
    evaluate=oracle(path);rows=[]
    for mask in (0,4,9,15,0xffffffff):
        for tag in range(32):
            for walkable in (0,1):
                for unrelated in (0,0x40000,0xff03fffe):
                    flags=(tag<<19)|walkable|unrelated
                    expected=bool(flags&1 and mask&(1<<((flags>>19)&31)))
                    traverse=evaluate(flags,mask);suitable=evaluate(flags,mask,kind='suitable')
                    if traverse!=expected or suitable!=expected:raise ValueError('Native default policy mismatch')
                    rows.append(dict(flags=flags,mask=mask,traverse=traverse,suitable=suitable))
    extra=[]
    for tag in (0,2,3,31):
        for walkable in (0,1):
            for require_walk in (False,True):
                for target_walk in (False,True):
                    for require_tags in (False,True):
                        flags=tag<<19|walkable
                        result=evaluate(flags,9,kind='suitable',constrain_walkability=require_walk,walkable=target_walk,constrain_tags=require_tags)
                        expected=(not require_walk or bool(walkable)==target_walk) and (not require_tags or bool(9&(1<<tag)))
                        if result!=expected:raise ValueError('Native nearest policy mismatch')
                        extra.append(dict(flags=flags,constrain_walkability=require_walk,walkable=target_walk,constrain_tags=require_tags,result=result))
    graphs=[]
    for mask in (0,1,0x80000000,0xffffffff):
        for index in range(32):
            result=evaluate(0,mask,kind='graph',graph_index=index)
            if result!=bool(mask&(1<<index)):raise ValueError('Native graph mask mismatch')
            graphs.append(dict(mask=mask,index=index,result=result))
    return dict(source_sha256=IL2CPP_SHA,default_cases=rows,nearest_cases=extra,graph_cases=graphs,can_send_packets=False,
                scope='Default native flag/tag checks with synthetic ABI state; no area/provider/nearest geometry oracle')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    try:print(json.dumps(vectors(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
