"""Native modifier constructors and AstarPath's pre-allocation field defaults.

Zeroed objects and resolved metadata/static state are prepared. This is not Unity
AddComponent/Awake, serialized scene loading, or an installed player's settings.
"""
import argparse
import json
import struct
from tools.review_navigation_vertices import oracle as vertex_oracle
from tools.review_navigation_rotation import IL2CPP_SHA


def run(path):
    state={};vertex_oracle(path,_state=state);u=state['vm'];data=state['data']
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_CPACR_EL1,UC_ARM64_REG_LR,UC_ARM64_REG_X0
    ranges=((0x24cda58,0x24cda68),(0x24d30b4,0x24d30e4),(0x3442784,0x344278c),
            (0x352a718,0x352a720),(0x192dc90,0x192dc98),(0x33efae0,0x33efae8),
            (0x3419d98,0x3419d9c),(0x341a28c,0x341a2e4),(0x33f0f3c,0x33f0f44),(0x1de43dc,0x1de43e0),
            (0x1a76e50,0x1a76f4c),(0xe006b0,0xe006b4))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x4c63000,0x4934000,0x4c54000,0x4980000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['ranges'].extend(ranges)
    for a in (0x49343c8,0x4980e00):u.mem_write(a,struct.pack('<Q',0x6010000))
    for a in (0x4c63448,0x4c54e26):u.mem_write(a,b'\1')
    u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
    def stop(machine,address,size,user):
        if address==0xe006b0:
            if u.reg_read(UC_ARM64_REG_LR)!=0x1a76f4c or u.reg_read(UC_ARM64_REG_X0)!=0x6010100:raise ValueError('Unexpected constructor boundary')
            raise Boundary()
    class Boundary(Exception):pass
    u.hook_add(UC_HOOK_CODE,stop)
    rows=[]
    for name,entry in (('StartEndModifier',0x24d30b4),('FunnelModifier',0x24cda58),('AstarPath_prefix',0x1a76e50)):
        u.mem_write(0x6000000,bytes(0x1000));complete=True
        try:state['execute'](entry,(0x6000000,0),instruction_limit=20000)
        except Boundary:complete=False
        if (name=='AstarPath_prefix')==complete:raise ValueError('Unexpected constructor completion')
        def read(offset,fmt):return struct.unpack(fmt,u.mem_read(0x6000000+offset,struct.calcsize(fmt)))[0]
        if name=='StartEndModifier':
            fields=dict(exactStartPoint=read(0x1c,'<i'),exactEndPoint=read(0x20,'<i'),useRaycasting=bool(read(0x30,'B')),useGraphRaycasting=bool(read(0x38,'B')),layerMask=read(0x34,'<i'))
            expected=dict(exactStartPoint=3,exactEndPoint=3,useRaycasting=False,useGraphRaycasting=False,layerMask=-1)
        elif name=='FunnelModifier':
            fields=dict(quality=read(0x28,'<i'),unwrap=bool(read(0x2c,'B')),splitAtEveryPortal=bool(read(0x2d,'B')));expected=dict(quality=0,unwrap=True,splitAtEveryPortal=False)
        else:
            fields=dict(heuristic=read(0x60,'<i'),heuristicScale=read(0x64,'<f'),maxNearestNodeDistance=read(0x44,'<f'),fullGetNearestSearch=bool(read(0x49,'B')))
            expected=dict(heuristic=2,heuristicScale=1.,maxNearestNodeDistance=100.,fullGetNearestSearch=False)
        if fields!=expected:raise ValueError('Native constructor defaults differ')
        rows.append(dict(type=name,constructor_completed=complete,fields=fields))
    return dict(source_sha256=IL2CPP_SHA,cases=rows,can_send_packets=False,scope=__doc__)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    print(json.dumps(run(args.libil2cpp),sort_keys=True))


if __name__=='__main__':main()
