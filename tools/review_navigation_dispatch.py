"""Native Seeker.RunModifiers dispatch trace on explicit prepared modifier lists.

Callbacks record control flow only, not modifier mathematics. No registration,
sorting, final-player-path equivalence or movement authorization is implied.
"""
import argparse
import json
import struct
from tools.review_navigation_modifier_order import run as order_probe
from tools.review_navigation_rotation import IL2CPP_SHA


def run(path):
    state={};order_probe(path,_state=state);u=state['vm'];data=state['data']
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_LR,UC_ARM64_REG_PC
    ranges=((0x2a8e6a0,0x2a8e894),(0x297c43c,0x297c488))
    bridges={0x601d000:('StartEnd.Apply',0x2a8e870,0x6040000),0x601d010:('Funnel.Apply',0x2a8e870,0x6050000),
             0x601d020:('StartEnd.PreProcess',0x2a8e7b8,0x6040000),0x601d030:('Funnel.PreProcess',0x2a8e7b8,0x6050000),
             0x601d040:('preProcessCallback',0x2a8e72c,0x6000000),0x601d050:('postProcessCallback',0x2a8e7e4,0x6000000)}
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x49c3000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['ranges'].extend(ranges+tuple((a,a+4) for a in bridges))
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    u.mem_write(0x4c5b2d6,b'\1');q(0x49c33b8,0x6010400)
    q(0x6041148,0x601d000);q(0x6051148,0x601d010);q(0x6041158,0x601d020);q(0x6051158,0x601d030)
    q(0x60000a0,0x6001000);q(0x6001010,0x6002000);w(0x6002018,2)
    for ptr,target in ((0x6003000,0x601d040),(0x6004000,0x601d050)):
        q(ptr+0x18,target);q(ptr+0x40,0x6000000)
    calls=[]
    def trace(machine,address,size,user):
        if address not in bridges:return
        label,caller,owner=bridges[address]
        if u.reg_read(UC_ARM64_REG_LR)!=caller or u.reg_read(UC_ARM64_REG_X0)!=owner or u.reg_read(UC_ARM64_REG_X1)!=0x6005000:raise ValueError('Unexpected native dispatch ABI')
        calls.append(label);u.reg_write(UC_ARM64_REG_PC,caller)
    u.hook_add(UC_HOOK_CODE,trace);rows=[]
    for order in ([],[0],[1],[0,1],[1,0]):
        w(0x6001018,len(order))
        for i,n in enumerate(order):q(0x6002020+8*i,0x6040000+n*0x10000)
        for callbacks in (False,True):
            q(0x6000050,0x6003000 if callbacks else 0);q(0x6000058,0x6004000 if callbacks else 0)
            for mode in (0,1,2):
                calls.clear();state['execute'](0x2a8e6a0,(0x6000000,mode,0x6005000,0),instruction_limit=20000)
                method='PreProcess' if mode==0 else 'Apply'
                expected=[] if mode==1 else ([('preProcessCallback' if mode==0 else 'postProcessCallback')] if callbacks else [])+[('StartEnd' if i==0 else 'Funnel')+'.'+method for i in order]
                if calls!=expected:raise ValueError('Native dispatch order mismatch')
                rows.append(dict(prepared_order=order,callbacks=callbacks,pass_value=mode,calls=list(calls)))
    return dict(source_sha256=IL2CPP_SHA,cases=rows,can_send_packets=False,scope=__doc__)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    print(json.dumps(run(args.libil2cpp),sort_keys=True))


if __name__=='__main__':main()
