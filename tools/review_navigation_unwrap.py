"""Native 3-D Funnel.Unwrap with the pinned native Unity rotation icall.

Preallocated managed ABI state and a cross-emulator icall bridge; no local math
substitutes the rotation. Not a full FunnelModifier or final player path.
"""
import argparse
import json
import math
import struct
from tools.review_navigation_vertices import oracle as vertex_oracle
from tools.review_navigation_rotation import from_to_oracle,IL2CPP_SHA,UNITY_SHA


def validate_portals(left,right):
    if not 2<=len(left)==len(right)<=128:raise ValueError('Require 2..128 matched portals')
    for point in [*left,*right]:
        if len(point)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>1000 for x in point):raise ValueError('Invalid bounded portal point')
    if left[0]!=right[0] or left[-1]!=right[-1]:raise ValueError('Require point start/end portals')


def oracle(il2cpp,unity,*,_state=None):
    state={};vertex_oracle(il2cpp,_state=state);between=from_to_oracle(unity)
    u=state['vm'];data=state['data']
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_LR,UC_ARM64_REG_PC,UC_ARM64_REG_CPACR_EL1
    ranges=((0x2358620,0x2358dc4),(0x2225164,0x22251c4),(0x30c66a4,0x30c6748),
            (0x30c70e0,0x30c7140),(0x2a967e0,0x2a968ec),(0x30cd6e8,0x30cd7e4))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x4c58000,0x4c4f000,0x4c50000,0x4c53000,0x4c5d000,0x4c5e000,0x4955000,0x49b0000,0x49b2000,0x3792000,0x379a000,0x37c4000,0x37f1000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['pages'].update(pages);state['ranges'].extend(ranges+((0x601d000,0x601d004),))
    u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    for a in (0x4c58699,0x4c4ff4d,0x4c503a6,0x4c534bb,0x4c5e019):u.mem_write(a,b'\1')
    for a in (0x4955018,0x49b0590):q(a,0x6010000)
    q(0x49b2900,0x6011000);q(0x6011000,0x6011100);q(0x60111b8,0x6011300)
    # Existing synthetic class statics contain Vector2.zero at offset zero.
    q(0x60101b8,0x6010200);u.mem_write(0x6010200,bytes(16))
    for a,n in ((0x379ae10,8),(0x37c4280,24),(0x37f12bc,4),(0x3792e18,4)):u.mem_write(a,data(a,n))
    q(0x4c5df28,0x601d000)
    state['execute'](0x30cd6e8,(0,))
    if list(struct.unpack('<3f',u.mem_read(0x6011348,12)))!=[0.,0.,1.]:raise ValueError('Native forward constant mismatch')
    bridge_calls=[]
    def bridge(machine,address,size,user):
        if address!=0x601d000:return
        if u.reg_read(UC_ARM64_REG_LR)!=0x30c712c:raise ValueError('Unreviewed Unity icall caller')
        ptrs=[u.reg_read(reg) for reg in (UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2)]
        if any(not 0x61fd000<=p<=0x61ff000-16 for p in ptrs):raise ValueError('Invalid Unity icall pointers')
        a=list(struct.unpack('<3f',u.mem_read(ptrs[0],12)));b=list(struct.unpack('<3f',u.mem_read(ptrs[1],12)))
        rotation=between(a,b);u.mem_write(ptrs[2],struct.pack('<4f',*rotation));bridge_calls.append(dict(start=a,end=b,rotation=rotation))
        u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
    u.hook_add(UC_HOOK_CODE,bridge)
    def run(left,right):
        validate_portals(left,right);n=len(left);bridge_calls.clear()
        for record,points in ((0x6040000,left),(0x6050000,right)):
            u.mem_write(record,bytes(0x2000));q(record+0x10,record+0x1000);w(record+0x18,n);w(record+0x1018,n)
            u.mem_write(record+0x1020,b''.join(struct.pack('<3f',*p) for p in points))
        for arr in (0x6060000,0x6070000):u.mem_write(arr,bytes(0x1000));w(arr+0x18,n)
        state['execute'](0x235887c,(0x6040000,0x6050000,0x6060000,0x6070000),instruction_limit=500000)
        output=[[list(struct.unpack('<2f',u.mem_read(arr+0x20+i*8,8))) for i in range(n)] for arr in (0x6060000,0x6070000)]
        if any(not math.isfinite(v) for row in output for point in row for v in point):raise ValueError('Nonfinite native unfolded portal')
        return dict(left=output[0],right=output[1],rotation_calls=list(bridge_calls))
    if _state is not None:_state.update(state,bridge_calls=bridge_calls)
    return run



def compare_unfolding(left,right,result):
    for key in ('left','right'):
        if len(result[key])!=len(left) or any(len(p)!=2 or any(not math.isfinite(v) for v in p) for p in result[key]):raise ValueError('Invalid unfolded output')
    # Each adjacent pair is a planar quadrilateral or a shared-vertex pair of
    # portals on one triangle. Unfolding must preserve its local edge lengths.
    for i in range(1,len(left)):
        original=[left[i-1],right[i-1],left[i],right[i]]
        flat=[result['left'][i-1],result['right'][i-1],result['left'][i],result['right'][i]]
        for a in range(4):
            for b in range(a):
                expected=math.dist(original[a],original[b]);actual=math.dist(flat[a],flat[b])
                if abs(expected-actual)>0.0006*max(1,expected):raise ValueError('Unfolded local edge length mismatch')


def fixtures():
    templates=[([[0,0,0],[1,0,1],[3,0,0]],[[0,0,0],[1,0,-1],[3,0,0]]),
               ([[0,0,0],[1,0,1],[2,1,1],[3,1,0]],[[0,0,0],[1,0,-1],[1,0,-1],[3,1,0]]),
               ([[0,0,0],[1,0,2],[2,0,2],[3,0,4]],[[0,0,0],[1,0,1],[2,0,1],[3,0,4]])]
    transforms=(lambda x,y,z:[x,y,z],lambda x,y,z:[z,x,y],lambda x,y,z:[x,-z,y],lambda x,y,z:[x+10,y-20,z+30])
    for left,right in templates:
        for transform in transforms:
            for scale in (.01,1.,10.):
                yield [[scale*v for v in transform(*p)] for p in left],[[scale*v for v in transform(*p)] for p in right]


def vectors(il2cpp,unity):
    call=oracle(il2cpp,unity);rows=[]
    for left,right in fixtures():
        output=call(left,right);compare_unfolding(left,right,output);rows.append(dict(left=left,right=right,official_output=output))
    return dict(il2cpp_sha256=IL2CPP_SHA,unity_sha256=UNITY_SHA,cases=rows,can_send_packets=False,
                scope='Native Unwrap and native Unity rotation via verified ABI bridge; supplied portal corridors, no full player path')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--libunity',required=True);args=parser.parse_args()
    try:print(json.dumps(vectors(args.libil2cpp,args.libunity),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
