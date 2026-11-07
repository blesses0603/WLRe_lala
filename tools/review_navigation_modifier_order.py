"""Native Seeker modifier comparator; not registration or dispatch acceptance."""
import argparse
import json
import struct
from tools.review_navigation_vertices import oracle as vertex_oracle
from tools.review_navigation_rotation import IL2CPP_SHA


def run(path,*,_state=None):
    state={};vertex_oracle(path,_state=state);u=state['vm'];data=state['data']
    ranges=((0x2a8f51c,0x2a8f63c),(0x24d26e8,0x24d26f0),(0x24cd3a0,0x24cd3a8),(0x20cd9c8,0x20cd9e4))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x497e000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['pages'].update(pages);state['ranges'].extend(ranges)
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    q(0x497e3c8,0x6010400);u.mem_write(0x4c5b2df,b'\1')
    for ptr,getter in ((0x6040000,0x24d26e8),(0x6050000,0x24cd3a0)):
        klass=ptr+0x1000;table=ptr+0x2000;q(ptr,klass);q(klass+0xb0,table)
        u.mem_write(klass+0x12a,struct.pack('<H',1));q(table,0x6010500);w(table+8,0);q(klass+0x138,getter)
    rows=[]
    for a in range(2):
        for b in range(2):
            result=struct.unpack('<i',state['execute'](0x2a8f51c,(0,0x6040000+a*0x10000,0x6040000+b*0x10000,0))[:4])[0]
            if result!=(a>b)-(a<b):raise ValueError('Unexpected native modifier comparison')
            rows.append(dict(first=('StartEnd','Funnel')[a],second=('StartEnd','Funnel')[b],comparison=result))
    if _state is not None:_state.update(state)
    return dict(source_sha256=IL2CPP_SHA,cases=rows,can_send_packets=False,scope='Native RegisterModifier comparison delegate and native Order getters in prepared interface state; not complete list registration/sort or runtime inventory')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    try:print(json.dumps(run(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
