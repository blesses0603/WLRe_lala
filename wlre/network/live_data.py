"""Inventory and learned-skill wire layouts transcribed from the 1262 Lua."""
import math
from wlre.network.wire import ProtocolError

def item_save(r,index,equip=False):
    d={'index':index,'item_id':r.u16(),'count':1 if equip else r.u8(),
       'damage':r.u8(),'serial_version':r.u8(),'serial':r.u32()}
    if not equip:d.update(durable=r.u32(),firing=r.u32())
    d['magic_spar']=r.u16()
    d['available_time']=r.read('d');d['limited_time']=r.read('d')
    if not all(math.isfinite(d[k]) for k in ('available_time','limited_time')):raise ProtocolError('invalid item time')
    d.update(beat_level=r.u8(),differ=r.u8(),modeling=r.u16())
    if not equip:d['get_item_id']=r.u16()
    d.update(saddle_beat_level=r.u8(),enhance_level=r.u16(),design_id=r.u32())
    d['plugins']=[{'kind':r.u8(),'value':r.u16()} for _ in range(4)]
    d.update(locked=bool(r.u8()&1),star_soul_kind=r.u8(),star_soul_level=r.u8())
    if not equip:d['show_message']=r.u8()
    return d

def companion(r,index,npc_id,simple=False):
    d={'index':index,'npc_id':npc_id}
    if simple:
        d['can_grow']=r.u8()
        for key in ('str','con','int','wis','agi'):d[key]=r.u16()
        d.update(level=r.u8(),exp=r.u32())
    else:
        d.update(exp=r.i32(),level=r.u8(),hp=r.i32(),sp=r.u16())
        for key in ('int','str','con','agi','wis'):d[key]=r.u16()
        d.update(die=r.u8(),faith=r.u8(),can_grow=r.u8(),skill_potential=r.u16(),name=r.unicode8())
    d['skill_slots']=[{'level':r.u8(),'exp':r.u32()} for _ in range(5)]
    if simple:d['faith']=r.u8()
    d['equips']=[item_save(r,i+1,True) for i in range(9)]
    if not simple:d['sublime_count']=r.u8()
    d.update(sport_exp=r.u8(),degree=r.u8(),potential=r.u8(),modeling=r.u16())
    if not simple:d['party_index']=r.u8()
    d['use_up_stats']=r.u16()
    return d

def player_info(r):
    d={'element':r.u8(),'hp':r.u32(),'sp':r.u16()}
    for key in ('str','con','int','wis','agi'):d[key]=r.u16()
    d.update(level=r.u8(),exp=r.u32(),skill_potential=r.u16(),attribute_potential=r.u16(),max_hp=r.u32(),max_sp=r.u16())
    for key in ('equip_atk','equip_def','equip_matk','equip_speed_atk','equip_max_hp','equip_max_sp'):d[key]=r.u32()
    r.take(12) # organization serial and join time are irrelevant to combat.
    d['skills']=[{'key':r.u16(),'level':r.u8(),'exp':r.u32()} for _ in range(r.u16())]
    d.update(spring_hp=r.u16(),spring_sp=r.u16(),degree=r.u8(),job=r.u8(),potential=r.u8())
    return d

def decode_live(packet,r,event):
    key=packet.main,packet.sub
    if key==(5,47):
        event.update(type='star_info',level=r.u8(),star_core=r.u8(),exp=r.i64())
        r.take(30) # Lua ReceiveSecondJobInfo: 30 awaken-star point bytes
    elif key==(23,5):
        event.update(type='bag_snapshot',capacity=r.u8(),items=[])
        while r.remaining:event['items'].append(item_save(r,r.u8()))
    elif key==(23,6):event.update(type='bag_add',item=item_save(r,r.u8()),source=r.u16())
    elif key==(23,9):event.update(type='bag_delete',index=r.u8(),count=r.u8(),show_message=r.u8())
    elif key==(27,6):
        event.update(type='bag_sell',gold=r.u32(),index=r.u8(),count=r.u8())
    elif key==(27,8):event.update(type='sale_notice',result=r.u8())
    elif key in ((23,27),(23,28)):
        npc=r.u8() if key==(23,28) else 0
        event.update(type='equip_damage',npc_index=npc,index=r.u8(),damage=r.u8())
    elif key==(23,35):
        event.update(type='equip_broken',npc_index=r.u8(),item_id=r.u16())
    elif key==(23,140):
        kind=r.u8()
        if kind==1:
            grid,index,damage,npc=r.u8(),r.u8(),r.u32(),r.u8()
            event.update(type='bag_damage' if grid==1 else 'equip_damage' if grid in (2,3) else 'unknown_damage',
                         grid=grid,index=index,damage=damage,npc_index=0 if grid==2 else npc)
        elif kind==2:
            grid,index,npc,item=r.u8(),r.u8(),r.u8(),r.u16()
            event.update(type='bag_broken' if grid==1 else 'equip_broken' if grid in (2,3) else 'unknown_damage',
                         grid=grid,index=index,item_id=item,npc_index=0 if grid==2 else npc)
        elif kind==4:event.update(type='equip_damage',index=r.u8(),damage=r.u8(),npc_index=r.u8())
        elif kind in (3,5):
            r.take(8 if kind==3 else 16);event.update(type='item_server_time',kind=kind)
        else:raise ProtocolError('未知裝備損害度回覆')
    elif key==(23,11):
        event.update(type='player_equip_data',equips=[])
        while r.remaining:event['equips'].append(item_save(r,None,True))
    elif key==(23,15):
        kind=r.u8();event.update(type='item_use_result',result=kind)
        if kind==2:event.update(npc_index=r.u8(),item_id=r.u16())
    elif key==(5,3):event.update(type='player_combat_data',data=player_info(r))
    elif key==(15,8):
        event.update(type='companion_snapshot',companions=[])
        while r.remaining:
            index=r.u8();npc=r.u16();event['companions'].append(companion(r,index,npc))
    elif key==(15,1):
        owner=r.u32();npc=r.u32()
        event.update(type='companion_add',owner_id=owner,companion=companion(r,None,npc,True),show_message=r.u8())
    elif key==(15,2):event.update(type='companion_delete',owner_id=r.u32(),index=r.u8(),kind=r.u8())
    elif key in ((19,1),(19,4)):event.update(type='active_companion',npc_id=r.u32())
    elif key==(19,2):event.update(type='active_companion',npc_id=None)
    elif key==(11,252):event.update(type='battle_equip',owner_id=r.u32(),npc_index=r.u8(),equip_index=r.u8(),item_id=r.u16(),design_id=r.u32())
    else:return False
    return True
