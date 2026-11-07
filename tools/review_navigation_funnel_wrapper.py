"""Native Funnel.Calculate wrapper on supplied bounded 3-D portal corridors.

Only pool allocation/release is modeled, with fixed buffers and exact call sites.
The native algorithm performs Unwrap, FixFunnel, corner search and reconstruction.
This is not native portal extraction, Seeker dispatch or final movement authority.
"""
import argparse
import json
import math
import struct
from tools.review_navigation_unwrap import oracle as unwrap_oracle,validate_portals,fixtures,compare_unfolding
from tools.review_navigation_rotation import IL2CPP_SHA,UNITY_SHA


def oracle(il2cpp,unity):
    state={};unwrap=unwrap_oracle(il2cpp,unity,_state=state);u=state['vm'];data=state['data']
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_LR,UC_ARM64_REG_PC
    ranges=((0x2358dc4,0x2358ee4),(0x2358f78,0x2359754),(0x23597a4,0x2359c44),
            (0x1f50780,0x1f507d4),(0x2617264,0x2617268),(0x2a97190,0x2a971e4))
    model_callers={0x11f64c0:(0x23590d8,0x23590ec),0x1cb62d0:(0x23591f0,),0x1cc17e4:(0x235931c,),
                   0x1cb751c:(0x23596dc,),0x11f6e1c:(0x2359710,0x2359720)}
    model_ranges=tuple((a,a+4) for a in model_callers)
    slots=(0x49c4de8,0x497cff0,0x4984030,0x4996120,0x49c3a48,0x495bc58,0x4993e68,
           0x49789c8,0x49b9ab8,0x49b5318,0x4926b08,0x497c2e0,0x493fbe0,0x49b45e0,0x496cb20)
    pages={p for a,b in ranges+model_ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{a&~4095 for a in slots}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['pages'].update(pages);state['ranges'].extend(ranges+model_ranges)
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    def read(a):return struct.unpack('<I',u.mem_read(a,4))[0]
    for a in slots:q(a,0x6010000)
    for a in (0x4c5869a,0x4c5869b,0x4c5080c):u.mem_write(a,b'\1')
    u.mem_write(0x3792f64,data(0x3792f64,4))
    allocated={};released=set();calls=[]
    def model(machine,address,size,user):
        if address not in model_callers:return
        caller=u.reg_read(UC_ARM64_REG_LR)
        if caller not in model_callers[address]:raise ValueError('Unreviewed pool caller')
        arg=u.reg_read(UC_ARM64_REG_X0);calls.append(hex(address))
        if address==0x11f64c0:
            ptr=0x6060000 if caller==0x23590d8 else 0x6070000
            if not 2<=arg<=128 or ptr in allocated:raise ValueError('Invalid array pool claim')
            u.mem_write(ptr,bytes(0x1000));w(ptr+0x18,arg);allocated[ptr]='array2';u.reg_write(UC_ARM64_REG_X0,ptr)
        elif address in (0x1cb62d0,0x1cc17e4):
            ptr=0x6080000 if address==0x1cb62d0 else 0x6090000
            if ptr in allocated or (address==0x1cc17e4 and not 1<=arg<=256):raise ValueError('Invalid list pool claim')
            u.mem_write(ptr,bytes(0x2000));q(ptr+0x10,ptr+0x1000);w(ptr+0x1018,256)
            allocated[ptr]='listint' if address==0x1cb62d0 else 'list3';u.reg_write(UC_ARM64_REG_X0,ptr)
        else:
            if not 0x61fd000<=arg<0x61ff000:raise ValueError('Invalid pool release pointer')
            ptr=struct.unpack('<Q',u.mem_read(arg,8))[0]
            expected='listint' if address==0x1cb751c else 'array2'
            if allocated.get(ptr)!=expected or ptr in released:raise ValueError('Invalid pool release')
            released.add(ptr);q(arg,0)
        u.reg_write(UC_ARM64_REG_PC,caller)
    u.hook_add(UC_HOOK_CODE,model)
    def run(left,right,*,split=False):
        validate_portals(left,right)
        if type(split) is not bool:raise ValueError('Invalid split flag')
        unfolded=unwrap(left,right);allocated.clear();released.clear();calls.clear();state['bridge_calls'].clear()
        result=struct.unpack('<Q',state['execute'](0x2358f78,(0x6040000,0x6050000,1,int(split),0),instruction_limit=1000000)[:8])[0]
        if result!=0x6090000 or released!={0x6060000,0x6070000,0x6080000}:raise ValueError('Invalid pool lifecycle')
        count=read(result+0x18)
        if not 2<=count<=256:raise ValueError('Invalid funnel output size')
        output=[list(struct.unpack('<3f',u.mem_read(result+0x1020+i*12,12))) for i in range(count)]
        if any(not math.isfinite(x) for p in output for x in p):raise ValueError('Nonfinite funnel output')
        f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
        if output[0]!=[f32(x) for x in left[0]] or output[-1]!=[f32(x) for x in left[-1]]:raise ValueError('Funnel endpoints changed')
        if not 2<=read(0x6080018)<=256:raise ValueError('Invalid native corner count')
        indices=list(struct.unpack('<'+'i'*read(0x6080018),u.mem_read(0x6081020,4*read(0x6080018))))
        if any(abs(i)>=len(left) for i in indices):raise ValueError('Invalid native corner index')
        if not split:
            expected=[[f32(x) for x in (left[i] if i>=0 else right[-i])] for i in indices]
            if output!=expected:raise ValueError('Native 3-D corner reconstruction mismatch')
        if split:
            if len(output)!=len(left):raise ValueError('Missing split-portal point')
            for point,a,b in zip(output,left,right):
                delta=[y-x for x,y in zip(a,b)];length2=sum(x*x for x in delta)
                t=0. if length2==0 else sum((p-x)*d for p,x,d in zip(point,a,delta))/length2
                closest=[x+min(1.,max(0.,t))*d for x,d in zip(a,delta)]
                if math.dist(point,closest)>0.0006*max(1,math.dist(a,b)):raise ValueError('Split point off original 3-D portal')
        return dict(vector_path=output,corner_indices=indices,unfolded=unfolded,pool_calls=list(calls),rotation_calls=list(state['bridge_calls']),can_send_packets=False)
    return run



def vectors(il2cpp,unity):
    call=oracle(il2cpp,unity);rows=[]
    for left,right in fixtures():
        for split in (False,True):
            output=call(left,right,split=split);compare_unfolding(left,right,output['unfolded'])
            rows.append(dict(left=left,right=right,split=split,official_output=output))
    return dict(il2cpp_sha256=IL2CPP_SHA,unity_sha256=UNITY_SHA,cases=rows,can_send_packets=False,scope='Native Unwrap/FixFunnel/corner search/3-D reconstruction with modeled bounded pool and native Unity icall bridge; supplied portals, not extraction or actual Seeker dispatch')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--libunity',required=True);args=parser.parse_args()
    try:print(json.dumps(vectors(args.libil2cpp,args.libunity),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
