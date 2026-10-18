"""Server-backed inventory/skill knowledge; no inferred learned skills or HP gains."""
from wlre.paths import RESOURCE_ROOT
import json
import math
from wlre.network.wire import ProtocolError
from wlre.services.battle.combat import BROKEN
from wlre.core.inventory_updates import add_item

CAT=json.loads(RESOURCE_ROOT.joinpath('combat_catalog.json').read_text(encoding='utf8'))
NO_ITEMS={9,12,13,14,15,16,17,18,21,22,23,24}

def item_name(item_id):return CAT['items'].get(str(item_id),{}).get('name',f'物品{item_id}')
def skill_name(skill_id):return CAT['skills'].get(str(skill_id),{}).get('name',f'技能{skill_id}')

def apply_live(state,event):
    kind=event['type'];inv=state.inventory;k=state.knowledge
    if kind=='bag_snapshot':
        fresh={'ready':True,'reliable':True,'capacity':event['capacity'],'items':{},'reserved':{},
               'revision':inv.get('revision',0)+1,'use_failed':False,'field_supply':inv.get('field_supply',{}),'alchemy_slots':list(inv.get('alchemy_slots',[])),
               'expedition_slots':list(inv.get('expedition_slots',[])),
               'maintenance_slots':list(inv.get('maintenance_slots',[]))}
        for value in event['items']:
            if not add_item(fresh,dict(value)):break
        state.inventory=fresh
    elif kind=='bag_add':
        add_item(inv,dict(event['item']));inv['revision']+=1
    elif kind in ('bag_delete','bag_sell'):
        index=str(event['index']);value=inv['items'].get(index);count=event['count']
        if not value or count>value['count']:inv.update(reliable=False,sync_error='物品扣除數量或格位不符')
        elif value:
            value['count']-=count
            if not value['count']:inv['items'].pop(index)
        inv['reserved'][index]=max(0,inv['reserved'].get(index,0)-count);inv['revision']+=1
    elif kind=='bag_damage':
        item=inv['items'].get(str(event['index']))
        if item:
            item['damage']=event['damage'];inv['revision']+=1
    elif kind=='bag_broken':
        apply_live(state,{'type':'bag_delete','index':event['index'],'count':1})
    elif kind in ('equip_damage','equip_broken'):
        npc=event.get('npc_index',0)
        profile=k['player'] if not npc else k['companions'].get(str(npc),{})
        equips=profile.get('equips',[])
        index=event.get('index')
        if index is None:
            fit=CAT['items'].get(str(event.get('item_id')),{}).get('fit_type')
            index=7 if fit==11 else fit
        if type(index) is int and 1<=index<=len(equips):
            equip=equips[index-1]
            if kind=='equip_broken':equip.update(item_id=event['item_id'],damage=250)
            else:equip['damage']=event['damage']
    elif kind=='item_use_result':
        inv['last_use_result']=event['result']
        if event['result'] in (3,4):inv['use_failed']=True
    elif kind=='player_combat_data':
        data=event['data'];skills={}
        for v in data['skills']:
            sid=CAT['keys'].get(str(v['key']))
            if sid and v['level']>0:skills[str(sid)]={**v,'source':'S5-3'}
        k['player']={**k['player'],'ready':True,'skills':skills,'stats':{**k['player'].get('stats',{}),**{a:b for a,b in data.items() if a!='skills'}}}
    elif kind=='star_info':
        k['player'].setdefault('stats',{}).update(level=event['level'],degree=2,exp=event['exp'])
    elif kind=='player_equip_data':
        equips=[{'item_id':0} for _ in range(9)]
        for value in event['equips']:
            fit=CAT['items'].get(str(value['item_id']),{}).get('fit_type',0)
            if fit==11:fit=7
            if 1<=fit<=9:equips[fit-1]=dict(value)
        k['player']['equips']=equips
    elif kind=='companion_snapshot':
        # S15-8 may arrive in several packets: source adds each record, not clear-all.
        k['companions_ready']=True
        for data in event['companions']:set_companion(state,data)
    elif kind=='companion_add' and event['owner_id']==state.player.get('role_id'):
        data=dict(event['companion'])
        if k.get('companions_ready'):
            data['index']=next((i for i in range(1,256) if str(i) not in k['companions']),None)
            if data['index']:set_companion(state,data)
    elif kind=='companion_delete' and event['owner_id']==state.player.get('role_id'):
        k['companions'].pop(str(event['index']),None)
    elif kind=='active_companion':k['active_npc_id']=event['npc_id']
    elif kind=='attribute_set':
        entity=event['entity'];profile=None
        if entity=='self':profile=k['player']
        elif entity.startswith('follow:') and event.get('human_kind')==4:profile=k['companions'].get(str(event['index']))
        if profile is not None:
            if event['kind']==110:
                sid=str(event['parameter'])
                if event['value']>0:profile['skills'][sid]={'level':event['value'],'exp':0,'source':f'S8-{event.get("sub",0)}'}
                else:profile['skills'].pop(sid,None)
            else:
                names={25:'hp',26:'sp',35:'level',36:'exp',39:'degree',41:'atk',43:'matk',46:'max_hp',47:'max_sp',205:'max_hp',206:'max_sp'}
                if event['kind'] in names:profile.setdefault('stats',{})[names[event['kind']]]=event['value']
    elif kind in ('battle_start','battle_units'):
        for unit in event['units']:
            profile=profile_for({'knowledge':k,'player':state.player},unit)
            if profile:
                for attr in ('hp','sp','max_hp','max_sp','level','degree'):
                    if attr in unit:profile.setdefault('stats',{})[attr]=unit[attr]
    elif kind=='battle_attribute_set':
        for value in event['values']:
            unit=state.battle_units.get(f"{value['col']}:{value['row']}")
            if unit and value['kind'] in (25,26,46,47):
                profile=profile_for({'knowledge':k,'player':state.player},unit)
                if profile:profile.setdefault('stats',{})[{25:'hp',26:'sp',46:'max_hp',47:'max_sp'}[value['kind']]]=value['value']
    elif kind=='battle_equip' and 1<=event['equip_index']<=9:
        if event['owner_id']==state.player.get('role_id'):
            profile=k['player'] if not event['npc_index'] else k['companions'].get(str(event['npc_index']),{})
            equips=profile.get('equips',[]);index=event['equip_index']-1
            if index<len(equips) and equips[index].get('item_id')!=event['item_id']:
                equips[index]={'item_id':event['item_id'],'design_id':event['design_id']}
        for unit in state.battle_units.values():
            match=(unit['pid']==event['owner_id'] if event['npc_index']==0 else
                   unit['master_id']==event['owner_id'] and unit['npc_index']==event['npc_index'])
            if match:unit['equips'][event['equip_index']-1]={'item_id':event['item_id'],'design_id':event['design_id']}

def set_companion(state,data):
    npc=CAT['npcs'].get(str(data['npc_id']),{});skills={}
    for sid,value in zip(npc.get('skills',[]),data['skill_slots']):
        if sid and value['level']>0:skills[str(sid)]={**value,'source':'S15技能槽＋NpcData'}
    state.knowledge['companions'][str(data['index'])]={'ready':True,'npc_id':data['npc_id'],'index':data['index'],
        'skills':skills,'stats':{a:b for a,b in data.items() if a not in ('skill_slots','equips')},'equips':data['equips']}
    # Native Role temporarily queues S8 updates that precede S15 initialization.
    for key,value in state.attributes.get(f"follow:{data['index']}",{}).items():
        attribute,parameter=map(int,key.split(':'))
        apply_live(state,{'type':'attribute_set','entity':f"follow:{data['index']}",'index':data['index'],
            'human_kind':4,'kind':attribute,'parameter':parameter,'value':value})

def available(inv,index):
    if str(index) in inv.get('expedition_slots',[]) or str(index) in inv.get('maintenance_slots',[]):return 0
    return max(0,inv.get('items',{}).get(str(index),{}).get('count',0)-inv.get('reserved',{}).get(str(index),0))

def allocate(inv,item_id,count):
    if not inv.get('ready') or not inv.get('reliable'):raise ProtocolError('包包資料尚未同步或已失效')
    result=[]
    for index,value in sorted(inv['items'].items(),key=lambda x:int(x[0])):
        if str(index) in inv.get('alchemy_slots',[]):continue
        if value['item_id']!=item_id:continue
        amount=min(count,available(inv,index))
        if amount:result.append({'index':int(index),'count':amount,'item_id':item_id});count-=amount
        if not count:return result
    raise ProtocolError(f'{item_name(item_id)}數量不足或仍待伺服器扣除')

def reserve(state,allocations):
    for v in allocations:
        if str(v['index']) in state.inventory.get('alchemy_slots',[]):raise ProtocolError('此格仍等待煉金材料扣除回覆')
        if available(state.inventory,v['index'])<v['count']:raise ProtocolError('包包數量已變更')
    for v in allocations:
        key=str(v['index']);state.inventory['reserved'][key]=state.inventory['reserved'].get(key,0)+v['count']

def profile_for(state,actor):
    k=state.get('knowledge',{});pid=state.get('player',{}).get('role_id')
    if actor['pid']==pid:return k.get('player',{})
    if actor.get('master_id')!=pid:return {}
    profile=k.get('companions',{}).get(str(actor.get('npc_index')),{})
    return profile if profile.get('npc_id')==actor['pid'] else {}

def learned(state,actor):
    profile=profile_for(state,actor);records={sid:dict(v) for sid,v in profile.get('skills',{}).items()}
    # Native AppearanceData keeps one equipment-skill record: last nonzero link.
    equip_skill=None
    for equip in actor.get('equips',[]):
        sid=CAT['items'].get(str(equip['item_id']),{}).get('skill_link',0)
        if str(sid) in CAT['skills']:equip_skill=sid
    if equip_skill:records[str(equip_skill)]={'level':CAT['skills'][str(equip_skill)]['LvLimit'],'source':'目前裝備附帶'}
    result={}
    for sid,record in records.items():
        resolved=int(sid)
        if resolved==15003:
            char=next((c for c in CAT['characters'] if c['sex']==actor.get('sex') and c['head']==actor.get('head')),None)
            if char:resolved=char['skill']
        if record.get('level',0)>0:result[str(resolved)]=record
    return result

def weapon_group(actor):
    if len(actor.get('equips',[]))<3:return None
    item=actor['equips'][2]['item_id'];kind=0 if item==0 or item in BROKEN else CAT['items'].get(str(item),{}).get('kind')
    return 1 if kind in (1,2,3,6,8) else 2 if kind in (0,7,9) else 3 if kind in (5,10) else 4 if kind==4 else 5 if kind==11 else None

def skill_reasons(state,actor,sid):
    data=CAT['skills'].get(str(sid));problems=[];records=learned(state,actor)
    if data is None:return ['技能不在目前版本資料表']
    if str(sid) not in records:return ['此單位尚無已學／裝備授予證據']
    if data['Kind']==9 or data['KindSort']==4:return ['生活／被動技能，不能主動施放']
    if data['TargetKind']==4:return ['無可指定的戰鬥目標']
    if actor.get('exited') or actor.get('hp',0)<=0:problems.append('操作單位已陣亡／離場')
    if actor.get('sp',-1)<data['ReduceSP']:problems.append('SP不足／尚無SP資料')
    if data['ReduceHP'] and not data['ReduceSP'] and data['Kind']!=8 and math.ceil(actor.get('hp',0)*data['ReduceHP']/100)>=actor.get('hp',0):problems.append('HP不足以支付技能消耗')
    group=weapon_group(actor)
    if group is None or data.get('WeaponKind'+str(group))!=1:problems.append('目前武器不適用')
    char=next((c for c in CAT['characters'] if c['skill']==sid),None)
    if sid==15003 or (char and (actor.get('sex')!=char['sex'] or actor.get('head')!=char['head'] or len(actor.get('equips',[]))<2 or actor['equips'][1]['item_id']!=char['body'])):problems.append('新手特技外觀／初始衣服條件不符')
    if sid==11172 and (len(actor.get('equips',[]))<3 or actor['equips'][2]['item_id'] not in (20044,20045,20048,20050)):problems.append('艾琳專屬武器不符')
    if actor['pid']==state.get('player',{}).get('role_id') and data['CostItemID'] and data['CostItemCount']:
        try:allocate(state.get('inventory',{}),data['CostItemID'],data['CostItemCount'])
        except ProtocolError as exc:problems.append(str(exc))
    statuses=actor.get('statuses',{})
    if data['FightWay'] in (3,4,5,6,7,8,9,14,15,16,18,19,21,23,24,25) and statuses.get('silenced'):problems.append('目前狀態封鎖輔助技能')
    if statuses.get('taunt') and (data['TargetKind']!=0 or data['RangeKind1']!=1):problems.append('挑戰狀態限制目標／範圍')
    return problems

def target_valid(actor,target,data):
    if target.get('exited') or target.get('is_fly'):return False
    dead=target.get('hp',0)<=0
    if data['ID'] in (11053,15138):
        if not dead:return False
    elif data['ID']!=15253 and data['HitStatus']!=254 and dead:return False
    same=(actor['col']>2)==(target['col']>2);kind=data['TargetKind']
    return (not same if kind==0 else same if kind==1 else True if kind==2 else
            (actor['col'],actor['row'])==(target['col'],target['row']) if kind==3 else
            same and (actor['col'],actor['row'])!=(target['col'],target['row']) if kind==5 else False)

def learned_command(state,actor,sid,target_slot=None,target_kind=1,next_skill=False):
    sid=int(sid);records=learned(state,actor)
    if next_skill:
        for _ in range(2):
            data=CAT['skills'].get(str(sid),{});nxt=data.get('NextSkillId',0)
            if not nxt or records.get(str(sid),{}).get('level',0)<data.get('LvLimit',1) or str(nxt) not in records:break
            sid=nxt
    reasons=skill_reasons(state,actor,sid)
    if reasons:raise ProtocolError('；'.join(reasons))
    data=CAT['skills'][str(sid)]
    candidates=[u for key,u in state.get('battle_units',{}).items() if (not target_slot or key==target_slot) and target_valid(actor,u,data)
                and (not data['TargetNPCID'] or u['pid']==data['TargetNPCID'])]
    if not candidates:raise ProtocolError('此技能沒有符合條件的目標')
    if target_kind==3:target=min(candidates,key=lambda u:(-u['hp'],u['col'],u['row']))
    elif target_kind==2:
        element=actor.get('element',0) if sid in (10001,10002,10003,10004) else data['Element']
        weights=CAT.get('element_weights',{}).get(str(element),{})
        target=min(candidates,key=lambda u:(-weights.get(str(u.get('element',0)),1),u['col'],u['row']))
    else:target=min(candidates,key=lambda u:(u['hp'],u['col'],u['row']))
    costs=allocate(state['inventory'],data['CostItemID'],data['CostItemCount']) if actor['pid']==state['player']['role_id'] and data['CostItemID'] and data['CostItemCount'] else []
    return {'type':'learned_action','col':actor['col'],'row':actor['row'],'actor_pid':actor['pid'],
        'target_col':target['col'],'target_row':target['row'],'skill_id':sid,'resource_reservations':costs}

def best_skill_command(state,actor,target_slot=None,target_kind=1):
    candidates=[]
    for sid in learned(state,actor):
        data=CAT['skills'].get(sid,{})
        physical=data.get('AtkKind')==1 or (data.get('AtkKind')==3 and data.get('FightWay')==1)
        magic=(data.get('AtkKind')==2 and data.get('FightWay') in (1,2)) or (data.get('AtkKind')==3 and data.get('FightWay')==2)
        if data.get('KindSort') not in (1,2) or not (physical or magic):continue
        preference=0
        if actor['pid']==state.get('player',{}).get('role_id'):
            stats=profile_for(state,actor).get('stats',{})
            if 'atk' in stats and 'matk' in stats and physical!=(stats['atk']>=stats['matk']):continue
        candidates.append((preference,data.get('ReduceSP',0),data.get('Sort',0),int(sid)))
    for _,_,_,sid in sorted(candidates):
        try:return learned_command(state,actor,sid,target_slot,target_kind)
        except ProtocolError:continue
    from wlre.services.battle.battle_commands import action_command
    if not target_slot and target_kind in (2,3):
        enemies=[u for u in state.get('battle_units',{}).values() if u.get('hp',0)>0 and not u.get('exited') and (u['col']>2)!=(actor['col']>2)]
        if enemies:
            weights=CAT.get('element_weights',{}).get(str(actor.get('element',0)),{})
            chosen=min(enemies,key=lambda u:((-u['hp'] if target_kind==3 else -weights.get(str(u.get('element',0)),1)),u['col'],u['row']))
            target_slot=f"{chosen['col']}:{chosen['row']}"
    return action_command(state,actor,'normal',target_slot)

def heal_effects(item_id):
    item=CAT['items'].get(str(item_id),{})
    if item.get('kind') not in (23,32):return {}
    return {('hp' if a['kind']==25 else 'sp'):a['value']-100 for a in item['attributes'] if a['kind'] in (25,26) and a['value']>100}

def food_command(state,actor,resource='hp',item_id=None,target_slot=None,field=False,index=None):
    inv=state.get('inventory',{})
    if not inv.get('ready'):raise ProtocolError('包包尚未同步；請重新登入')
    if not inv.get('reliable'):raise ProtocolError('包包同步異常：'+inv.get('sync_error','先前操作未完整確認')+'；請重新登入同步')
    if inv.get('use_failed'):raise ProtocolError('前次道具使用失敗或結果未確認；請重新登入同步')
    if not field and state.get('battle',{}).get('war_style') in NO_ITEMS:raise ProtocolError('此戰鬥類型禁止使用道具')
    targets=[u for key,u in state.get('battle_units',{}).items() if u.get('hp',0)>0 and not u.get('exited')
             and (u['col']>2)==(actor['col']>2) and (not target_slot or key==target_slot)
             and u.get('max_'+resource,0)>u.get(resource,0)]
    if not targets:raise ProtocolError('沒有需要回復的存活同方目標')
    target=min(targets,key=lambda u:(u.get(resource,0)/max(1,u.get('max_'+resource,0)),u['col'],u['row']))
    choices=[];missing=target['max_'+resource]-target.get(resource,0)
    for bag_index,value in inv.get('items',{}).items():
        if str(bag_index) in inv.get('alchemy_slots',[]):continue
        if index is not None and int(bag_index)!=int(index):continue
        index_key=bag_index
        if item_id and value['item_id']!=item_id:continue
        data=CAT['items'].get(str(value['item_id']),{});effect=heal_effects(value['item_id'])
        if not effect.get(resource) or available(inv,index_key)<1 or value.get('locked') or value.get('available_time') or value.get('limited_time'):continue
        if not field and data.get('restrict',0)&256:continue
        if any(a['kind'] in (25,26) and a['value'] not in (0,100) and a['value']<100 for a in data['attributes']):continue
        amount=effect[resource];choices.append((amount<missing,abs(amount-missing),int(index_key),value['item_id']))
    if not choices:raise ProtocolError('包包沒有可用的'+resource.upper()+'回復食物')
    _,_,index,item_id=min(choices)
    return {'type':'field_item' if field else 'battle_item','col':actor['col'],'row':actor['row'],'actor_pid':actor['pid'],
        'target_col':target['col'],'target_row':target['row'],'item_id':item_id,'bag_index':index,'resource':resource,
        'resource_reservations':[{'index':index,'item_id':item_id,'count':1}]}

def skill_rows(state,actor):
    result=[]
    for sid,record in learned(state,actor).items():
        data=CAT['skills'].get(sid,{})
        result.append({'id':int(sid),'name':data.get('name',f'技能{sid}'),'level':record['level'],
            'category':{1:'物理',2:'魔法',3:'輔助',4:'被動'}.get(data.get('KindSort'),'其他'),
            'sp':data.get('ReduceSP'),'source':record.get('source'),
            'reasons':skill_reasons(state,actor,int(sid))})
    return sorted(result,key=lambda v:(v['category'],v['sp'] if v['sp'] is not None else 99999,v['id']))


def field_context(state):
    """Only server-confirmed role / active follower health, never last attack deltas."""
    context=dict(state);k=state.get('knowledge',{});pid=state.get('player',{}).get('role_id')
    stats=k.get('player',{}).get('stats',{})
    player={'sex':state.get('player',{}).get('sex'),'head':state.get('player',{}).get('head'),'equips':k.get('player',{}).get('equips',[]),'col':1,'row':1,'pid':pid,'master_id':0,'npc_index':0,'name':state.get('player',{}).get('name','角色'),**stats}
    units={'1:1':player}
    for profile in k.get('companions',{}).values():
        if profile.get('npc_id')==k.get('active_npc_id'):
            units['2:1']={'col':2,'row':1,'pid':profile['npc_id'],'master_id':pid,'npc_index':profile['index'],
                'name':CAT['npcs'].get(str(profile['npc_id']),{}).get('name','出戰夥伴'),'equips':profile.get('equips',[]),**profile.get('stats',{})}
            break
    context['battle_units']=units
    return context,player
