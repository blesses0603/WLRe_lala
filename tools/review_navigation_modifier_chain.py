"""Native register/sort/dispatch with guarded native-algorithm VM callbacks.

The two callbacks must execute the separately checked StartEnd and Funnel probes.
This composes native calculations across VMs, not a full managed player lifecycle.
"""
import struct
from tools.review_navigation_modifier_registration import oracle as registration_oracle


def oracle(path):
    state={};register=registration_oracle(path,_state=state);u=state['vm'];data=state['data']
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_LR,UC_ARM64_REG_PC
    ranges=((0x2a8e6a0,0x2a8e894),(0x297c43c,0x297c488))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x49c3000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['ranges'].extend(ranges+((0x601d000,0x601d004),(0x601d010,0x601d014)))
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    u.mem_write(0x4c5b2d6,b'\1');q(0x49c33b8,0x6010400)
    q(0x6041148,0x601d000);q(0x6051148,0x601d010)
    calls=[];callbacks=[];output=[]
    def bridge(machine,address,size,user):
        if address not in (0x601d000,0x601d010):return
        index=(address-0x601d000)//16
        if u.reg_read(UC_ARM64_REG_LR)!=0x2a8e870 or u.reg_read(UC_ARM64_REG_X0)!=0x6040000+index*0x10000 or u.reg_read(UC_ARM64_REG_X1)!=0x6005000 or index!=len(calls):raise ValueError('Unexpected modifier chain ABI/order')
        calls.append(('StartEnd.Apply','Funnel.Apply')[index]);output.append(callbacks[index](output[-1] if output else None))
        u.reg_write(UC_ARM64_REG_PC,0x2a8e870)
    u.hook_add(UC_HOOK_CODE,bridge)
    def run(start_end,funnel,*,registration_order=(1,0)):
        if not callable(start_end) or not callable(funnel) or sorted(registration_order)!=[0,1]:raise ValueError('Require both native modifier callbacks')
        registration=register(list(registration_order),cold=True);calls.clear();output.clear();callbacks[:]=[start_end,funnel]
        # No external pre/post-process delegates in this explicit profile.
        state['execute'](0x2a8e6a0,(0x6000000,2,0x6005000,0),instruction_limit=100000)
        if calls!=['StartEnd.Apply','Funnel.Apply']:raise ValueError('Incomplete native modifier dispatch')
        return dict(registration=registration,dispatch=list(calls),start_end=output[0],funnel_apply=output[1],can_send_packets=False,scope=__doc__)
    return run
