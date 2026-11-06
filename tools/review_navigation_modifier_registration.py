"""Native Seeker registration/List.Sort with an explicitly prepared cached delegate.

Only the reviewed StartEnd/Funnel pair is accepted. Generic metadata and static
initialization are prepared, not a full managed runtime or component lifecycle.
"""
import argparse
import json
import struct
from tools.review_navigation_modifier_order import run as order_probe
from tools.review_navigation_rotation import IL2CPP_SHA


def validate_order(order):
    if not isinstance(order,list) or len(order)>2 or any(type(i) is not int or i not in (0,1) for i in order) or len(set(order))!=len(order):raise ValueError('Require unique reviewed modifier pair')


def oracle(path,*,_state=None):
    state={};order_probe(path,_state=state);u=state['vm'];data=state['data']
    ranges=((0x2a8e4b4,0x2a8e638),(0x297e744,0x297e7dc),(0x1456294,0x1456350),
            (0x14565a0,0x14566cc),(0x1456760,0x1456d08),(0x1104f7c,0x1104f90),
            (0x2ab4648,0x2ab467c),(0xe00550,0xe00554),(0xe81860,0xe81864),(0xec1130,0xec1178))
    slots=(0x498e370,0x4963188,0x49af7e8)
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{a&~4095 for a in slots}|{0x4c68000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['pages'].update(pages);state['ranges'].extend(ranges)
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    u.mem_write(0x4c5b2d4,b'\1')
    q(0x498e370,0x6010000);q(0x4963188,0x6010000)
    # Cached comparison delegate; creation/GC and cold static initialization excluded.
    q(0x6010208,0x6003000);q(0x6003018,0x2a8f51c);q(0x6003040,0x6004000)
    q(0x49af7e8,0x6102000);q(0x6102000,0x6103000);q(0x6103020,0x6100000)
    q(0x61000c0,0x6101000);q(0x6101198,0x6112000);q(0x61011a0,0x6110000)
    w(0x61100e0,1);u.mem_write(0x6110132,b'\1');q(0x61100c0,0x6111000)
    for ptr,addr in ((0x6112000,0x1456294),(0x6113000,0x1456760),(0x6114000,0x145685c),(0x6115000,0x14565a0),(0x6116000,0x1104f7c)):
        q(ptr+8,addr);q(ptr+0x20,0x6110000)
    for offset,ptr in ((0x30,0x6113000),(0x38,0x6110000),(0x58,0x6115000),(0x48,0x6116000),(0x50,0x6114000)):q(0x6111000+offset,ptr)
    def run(order):
        validate_order(order)
        u.mem_write(0x6000000,bytes(0x3000));q(0x60000a0,0x6001000);q(0x6001010,0x6002000);w(0x6002018,2)
        stages=[]
        for i in order:
            state['execute'](0x2a8e4b4,(0x6000000,0x6040000+i*0x10000,0),instruction_limit=100000)
            count=struct.unpack('<I',u.mem_read(0x6001018,4))[0]
            pointers=struct.unpack('<'+'Q'*count,u.mem_read(0x6002020,8*count))
            indices=[(p-0x6040000)//0x10000 for p in pointers]
            if any(p not in (0x6040000,0x6050000) for p in pointers) or indices!=sorted(order[:len(stages)+1]):raise ValueError('Native registration sort mismatch')
            stages.append(indices)
        return dict(input_order=order,registration_stages=stages,sorted_order=stages[-1] if stages else [],can_send_packets=False)
    if _state is not None:_state.update(state)
    return run


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    run=oracle(args.libil2cpp)
    print(json.dumps(dict(source_sha256=IL2CPP_SHA,cases=[run(order) for order in ([],[0],[1],[0,1],[1,0])],can_send_packets=False,scope=__doc__),sort_keys=True))


if __name__=='__main__':main()
