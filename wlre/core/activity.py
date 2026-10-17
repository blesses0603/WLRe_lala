"""Observed movement locks from Lua fishing/gather/dance/sport protocols."""
from wlre.network.wire import Reader

def decode_activity(packet):
    r=Reader(packet.payload);key=packet.main,packet.sub;event=None
    if key in ((23,122),(23,123)):
        event={'type':'activity_roles','activity':'釣魚','active':packet.sub==123,'roles':[r.u32()]};r.u8()
    elif key==(23,138):event={'type':'activity_roles','activity':'採集','active':True,'roles':[r.u32() for _ in range(r.remaining//4)]}
    elif key==(23,137):event={'type':'activity_roles','activity':'採集','active':False,'roles':[r.u32()]}
    elif key==(7,4):
        mode=r.u8()
        if mode==0:event={'type':'activity_roles','activity':'跳舞','active':True,'initial':True,'roles':[r.u32() for _ in range(r.u32())]}
        elif mode in (1,3):event={'type':'activity_roles','activity':'跳舞','active':mode==1,'roles':[r.u32()]}
        else:return None
    elif key==(62,67):event={'type':'activity_self','activity':'馬桶製作','active':True}
    elif key==(62,84):event={'type':'activity_self','activity':'鍛鍊' if r.u8()==1 else '夥伴鍛鍊','active':True}
    if event is not None:r.end()
    return event

def apply_activity(state,event):
    kind=event['type'];pid=state.player.get('role_id')
    if kind=='activity_roles':
        name=event['activity']
        if event.get('initial'):state.activities.pop(name,None)
        if pid in event['roles']:
            if event['active']:state.activities[name]=True
            else:state.activities.pop(name,None)
    elif kind=='activity_self':
        if event['active']:state.activities[event['activity']]=True
        else:state.activities.pop(event['activity'],None)
    elif kind=='navigation_geometry_change' and event.get('clear_activity_role')==pid:
        for key in ('馬桶製作','鍛鍊','夥伴鍛鍊'):state.activities.pop(key,None)
    elif kind=='world_player':state.activities.clear()
