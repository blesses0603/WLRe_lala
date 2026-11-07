"""Native FunnelModifier.Apply with native parts/portals and a native-funnel VM bridge.

Bounded object/pool/list storage is modeled. The funnel bridge runs pinned native
math in another ARM64 VM; no Python path formula replaces it. Quality=Medium,
unwrap=true and a single same-tile navmesh corridor are explicit fixture scope.
"""
import argparse
import json
import struct
from tools.review_navigation_parts import oracle as parts_oracle
from tools.review_navigation_funnel_wrapper import oracle as funnel_oracle


def oracle(il2cpp,unity):
    state={};prepare=parts_oracle(il2cpp,_state=state);funnel=funnel_oracle(il2cpp,unity);u=state['vm'];data=state['data']
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_LR,UC_ARM64_REG_PC
    ranges=((0x24cd3a8,0x24cda4c),(0x18785c0,0x1878620),(0x1de43dc,0x1de43e0),
            (0x2d93c10,0x2d93c34),(0x2a94c4c,0x2a94d40),(0x33efd50,0x33efe54),
            (0x33efeb8,0x33eff10),(0x1dec964,0x1dec980))
    callers={0xe006b0:(0x24cd4ec,),0x1cc0f50:(0x24cd560,),0x2358f78:(0x24cd6c8,),
             0x2225730:(0x24cd6e8,),0x1cc219c:(0x24cd704,0x24cd710,0x24cd71c,0x24cda0c),0x1cc3e5c:(0x24cd9e4,)}
    model_ranges=tuple((p,p+4) for p in callers)
    slots=(0x49bcd28,0x49408a8,0x49416f0,0x49a2d78,0x49795b0,0x495c2e0,0x49b4260,0x498a430,0x4948398)
    pages={p for a,b in ranges+model_ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{p&~4095 for p in slots}|{0x4c59000,0x4c60000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['ranges'].extend(ranges+model_ranges);state['pages'].update(pages)
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    def read(a):return struct.unpack('<I',u.mem_read(a,4))[0]
    for a in slots:q(a,0x6010000)
    for a in (0x4c595ec,0x4c5b30e,0x4c609bb,0x4c6096b,0x4c6096c):u.mem_write(a,b'\1')
    # AstarPath.active -> data -> the existing navmesh, with a non-null Unity handle.
    q(0x498a430,0x6110000);q(0x6110000,0x6111000);w(0x61110e0,1);q(0x61110b8,0x6112000)
    q(0x6112018,0x6113000);q(0x6113010,1);q(0x6113020,0x6114000)
    q(0x6114040,0x6115000);w(0x6115018,1);q(0x6115020,0x6020000)
    # Distinct GridGraph type prevents treating the navmesh as a grid graph.
    q(0x49b4260,0x6116000);q(0x6116000,0x6117000);u.mem_write(0x611712c,b'\2')
    released=set();calls=[];bridge_outputs=[];allocated=set()
    def vectors(ptr):
        count=read(ptr+0x18);array=struct.unpack('<Q',u.mem_read(ptr+0x10,8))[0]
        if not 1<=count<=256 or array!=ptr+0x1000:raise ValueError('Invalid Apply list layout')
        return [list(struct.unpack('<3f',u.mem_read(array+0x20+i*12,12))) for i in range(count)]
    def model(machine,address,size,user):
        if address not in callers:return
        caller=u.reg_read(UC_ARM64_REG_LR);arg=u.reg_read(UC_ARM64_REG_X0)
        if caller not in callers[address]:raise ValueError('Unreviewed Apply bridge caller')
        calls.append(hex(caller))
        if address in (0xe006b0,0x1cc0f50):
            ptr=0x60f0000 if address==0xe006b0 else 0x60e0000
            if ptr in allocated or arg!=0x6010100:raise ValueError('Invalid Apply allocation')
            allocated.add(ptr);u.mem_write(ptr,bytes(0x100 if address==0xe006b0 else 0x2000))
            if address==0x1cc0f50:q(ptr+0x10,ptr+0x1000);w(ptr+0x1018,256)
            u.reg_write(UC_ARM64_REG_X0,ptr)
        elif address==0x2358f78:
            args=[u.reg_read(UC_ARM64_REG_X0+i) for i in range(5)]
            if args[:3]!=[0x6040000,0x6050000,1] or args[3] not in (0,1) or args[4]!=0 or bridge_outputs:raise ValueError('Invalid native funnel bridge ABI')
            output=funnel(vectors(args[0]),vectors(args[1]),split=bool(args[3]));bridge_outputs.append(output)
            ptr=0x60c0000;allocated.add(ptr);u.mem_write(ptr,bytes(0x2000));q(ptr+0x10,ptr+0x1000);w(ptr+0x1018,256);w(ptr+0x18,len(output['vector_path']))
            for i,p in enumerate(output['vector_path']):u.mem_write(ptr+0x1020+i*12,struct.pack('<3f',*p))
            u.reg_write(UC_ARM64_REG_X0,ptr)
        elif address==0x2225730:
            source=u.reg_read(UC_ARM64_REG_X0+1)
            if arg!=0x60e0000 or source!=0x60c0000 or read(arg+0x18)!=0:raise ValueError('Unreviewed AddRange storage bridge')
            count=read(source+0x18)
            if not 2<=count<=256:raise ValueError('Invalid AddRange size')
            u.mem_write(arg+0x1020,bytes(u.mem_read(source+0x1020,count*12)));w(arg+0x18,count);w(arg+0x1c,read(arg+0x1c)+1)
        else:
            if not (0x61fd000<=arg<0x61ff000 or arg==0x6000058):raise ValueError('Invalid Apply release address')
            ptr=struct.unpack('<Q',u.mem_read(arg,8))[0]
            expected={0x24cd704:0x6040000,0x24cd710:0x6050000,0x24cd71c:0x60c0000,0x24cd9e4:0x60d0000,0x24cda0c:0x6003000}[caller]
            if ptr!=expected or ptr in released:raise ValueError('Invalid Apply release owner')
            released.add(ptr);q(arg,0)
        u.reg_write(UC_ARM64_REG_PC,caller)
    u.hook_add(UC_HOOK_CODE,model)
    def run(vertices,faces,connections,route,vector_path,*,split=False):
        if type(split) is not bool:raise ValueError('Invalid Apply split profile')
        prepare(vertices,faces,connections,route,vector_path,_prepare_only=True)
        calls.clear();released.clear();allocated.clear();bridge_outputs.clear()
        u.mem_write(0x60f1000,bytes(0x100));u.mem_write(0x60f102c,bytes((1,int(split))))
        state['execute'](0x24cd3a8,(0x60f1000,0x6000000,0),instruction_limit=1000000)
        owner=struct.unpack('<Q',u.mem_read(0x6000058,8))[0]
        if owner!=0x60e0000 or released!={0x6040000,0x6050000,0x60c0000,0x60d0000,0x6003000} or len(bridge_outputs)!=1:raise ValueError('Invalid Apply lifecycle')
        output=vectors(owner)
        if output!=bridge_outputs[0]['vector_path']:raise ValueError('Apply changed bridged funnel output')
        return dict(vector_path=output,funnel=bridge_outputs[0],apply_calls=list(calls),part_pool_calls=list(state['pool_calls']),can_send_packets=False,scope=__doc__)
    return run


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--libunity',required=True);args=parser.parse_args()
    run=oracle(args.libil2cpp,args.libunity)
    print(json.dumps(run([[0,0,0],[10000,0,0],[0,5000,10000],[10000,5000,10000]],[[0,1,2],[1,3,2]],[[[1,5000,1]],[[0,5000,2]]],[0,1],[[1,1,1],[9,4,9]]),sort_keys=True))


if __name__=='__main__':main()
