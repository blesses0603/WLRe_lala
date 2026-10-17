"""Noncombat recovery preferences and the original Bag.SendUseMagicBottle protocol."""
import copy, math
from wlre.network.wire import Reader, Writer, Packet, ProtocolError
from wlre.services.items.combat_resources import food_command, heal_effects

KINDS={1:'hp',2:'sp',3:'hp',4:'sp'}

def defaults():
    return {res:{'enabled':True,'items':[0]*10,'storage':'off','other_items':True,
                 'player_percent':percent,'partner_percent':percent}
            for res,percent in (('hp',60),('sp',30))}

def validate(value):
    result=defaults()
    if not isinstance(value,dict) or set(value)-set(result):raise ProtocolError('未知戰後補給設定')
    for res,data in value.items():
        if not isinstance(data,dict) or set(data)-set(result[res]):raise ProtocolError('未知補給欄位')
        result[res].update(copy.deepcopy(data));p=result[res]
        if any(type(p[k]) is not bool for k in ('enabled','other_items')):raise ProtocolError('補給開關須為布林值')
        if p['storage'] not in ('off','first','after'):raise ProtocolError('儲存槽順序無效')
        for k in ('player_percent','partner_percent'):
            if type(p[k]) is not int or not 0<=p[k]<=100:raise ProtocolError('補給門檻須為0～100百分比')
        if not isinstance(p['items'],list) or len(p['items'])!=10:raise ProtocolError('每種補給需為10格')
        for sid in p['items']:
            if type(sid) is not int or (sid!=0 and not heal_effects(sid).get(res)):raise ProtocolError('指定物品不是可用的'+res.upper()+'補品')
    return result

def decode_recovery(packet):
    if (packet.main,packet.sub)!=(23,208):return None
    r=Reader(packet.payload);kind=r.u8();e={'main':23,'sub':208}
    if kind in (3,4):
        bottle=r.u8()
        if bottle not in KINDS:raise ProtocolError('未知藥水儲存槽類型')
        value=r.i32()
        if kind==3 and value<0:raise ProtocolError('藥水儲存槽數量無效')
        e.update(type='potion_balance' if kind==3 else 'potion_balance_add',resource=KINDS[bottle],value=value)
    elif kind==5:
        bottle=r.u8()
        if bottle not in (3,4):raise ProtocolError('未知藥水儲存槽回覆類型')
        e.update(type='potion_used',resource=KINDS[bottle],targets=[r.u8() for _ in range(r.u8())])
    elif kind in (1,2):
        bottle=r.u8() if kind==1 else None
        index=r.u8();durable=r.i32()
        e.update(type='potion_item_update',index=index,durable=durable)
        if kind==1:e.update(bottle_kind=bottle,npc_index=r.u8())
    else:raise ProtocolError('未知藥水儲存槽回覆')
    r.end();return e

def apply_recovery(state,event):
    kind=event['type']
    if kind not in ('potion_balance','potion_balance_add'):return
    resource=event['resource'];old=state.potion_storage.get(resource,{})
    if kind=='potion_balance':value=event['value']
    else:
        if 'value' not in old:return  # delta cannot establish an unknown baseline
        value=max(0,old['value']+event['value'])
    state.potion_storage[resource]={'value':value,'revision':old.get('revision',0)+1}

def storage_plan(state,unit,resource):
    balance=state.get('potion_storage',{}).get(resource,{})
    if 'value' not in balance:raise ProtocolError(resource.upper()+'藥水儲存槽尚未同步')
    if not unit.get('max_'+resource) or resource not in unit:raise ProtocolError('補給對象的'+resource.upper()+'尚未同步')
    amount=min(balance['value'],65535,max(0,math.ceil(unit['max_'+resource]-unit[resource])))
    if amount<=0:return None
    return {'type':'field_storage','resource':resource,'npc_index':unit.get('npc_index',0),'amount':amount}

def storage_packet(resource,npc_index,amount):
    if resource not in ('hp','sp') or type(npc_index) is not int or not 0<=npc_index<=255 or type(amount) is not int or not 1<=amount<=65535:
        raise ProtocolError('儲存槽補給參數無效')
    return Packet(23,147,Writer().u8(3 if resource=='hp' else 4).u8(1).u8(npc_index).u16(amount).build())

def choose(state,actor,unit,key,resource,settings):
    if settings['storage']=='first':
        cmd=storage_plan(state,unit,resource)
        if cmd:return cmd
    if settings['enabled']:
        for sid in settings['items']:
            if not sid:continue
            try:return food_command(state,actor,resource,sid,key,True)
            except ProtocolError:pass
        if settings['storage']=='after':
            cmd=storage_plan(state,unit,resource)
            if cmd:return cmd
        if settings['other_items']:
            return food_command(state,actor,resource,target_slot=key,field=True)
    if settings['enabled'] or settings['storage']=='first':raise ProtocolError(resource.upper()+'補給不足，請補充指定物品或儲存槽')
    return None


def needed(context,settings):
    """Whether a confirmed living unit is below an enabled recovery threshold."""
    if not settings or not settings.get('field_heal'):return False
    for unit in context.get('battle_units',{}).values():
        if unit.get('hp',0)<=0:continue
        who='partner' if unit.get('npc_index',0) else 'player'
        for resource,config in settings['recovery'].items():
            if not config['enabled'] and config['storage']!='first':continue
            maximum=unit.get('max_'+resource,0)
            if maximum and unit.get(resource,0)<maximum*config[who+'_percent']/100:return True
    return False
