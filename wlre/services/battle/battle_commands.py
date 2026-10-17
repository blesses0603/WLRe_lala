"""One user submission, automatically resolved owned-unit commands for one round."""
from wlre.services.battle.combat import normal_skill, DATA
from wlre.network.wire import ProtocolError

ACTIONS={'auto_skill':'自動搜尋特技','heal_hp':'包包補HP','heal_sp':'包包補SP','normal':'自動普攻','defend':'防禦','escape':'逃跑','catch':'捕捉'}

def slot(unit):return f"{unit['col']}:{unit['row']}"

def identity(unit):return (unit['pid'],unit.get('master_id',0))

def owned_units(state, living=True):
    pid=state.get('player',{}).get('role_id')
    units=[u for u in state.get('battle_units',{}).values()
           if pid is not None and (u.get('pid')==pid or u.get('master_id')==pid)]
    if living:units=[u for u in units if u.get('hp',0)>0 and not u.get('exited')]
    return sorted(units,key=lambda u:(u['pid']!=pid,u['col'],u['row']))

def catch_allowed(state,actor,target):
    npc=DATA['npcs'].get(str(target['pid']))
    if not npc or not npc.get('canCatch'):return False
    if any(u['pid']==target['pid'] for u in owned_units(state,False)):return False
    pid=state['player']['role_id']
    master=next((u for u in owned_units(state,False) if u['pid']==pid),None)
    level_unit=master if actor.get('master_id')==pid else actor
    if not level_unit or 'level' not in level_unit or 'level' not in target:return False
    equips=actor.get('equips',[])
    if len(equips)<6:return False
    special=equips[5]['item_id']
    bonus=DATA.get('catch_nets',{}).get(str(special),0)
    level=level_unit.get('degree',0)*100+level_unit['level']
    return target['level']<=level+bonus+5

def action_command(state,actor,mode,target_slot=None):
    if mode not in ACTIONS:raise ProtocolError('未知戰鬥行動')
    if mode in ('auto_skill','heal_hp','heal_sp'):
        from wlre.services.items.combat_resources import best_skill_command, food_command
        return best_skill_command(state,actor,target_slot) if mode=='auto_skill' else food_command(state,actor,'hp' if mode=='heal_hp' else 'sp')
    base={'type':'battle_action','col':actor['col'],'row':actor['row'],
          'actor_pid':actor['pid'],'mode':mode}
    if mode in ('defend','escape'):
        return dict(base,target_col=0,target_row=0,skill_id=60021 if mode=='defend' else 60041)
    enemies=[u for u in state.get('battle_units',{}).values()
             if (u['col']>2)!=(actor['col']>2) and u.get('hp',0)>0 and not u.get('exited')]
    if mode=='catch':enemies=[u for u in enemies if catch_allowed(state,actor,u)]
    if target_slot:
        enemies=[u for u in enemies if slot(u)==target_slot]
    if not enemies:raise ProtocolError('沒有符合條件的捕捉目標' if mode=='catch' else '沒有存活的敵方目標')
    target=min(enemies,key=lambda u:(u['hp'],u['col'],u['row']))
    sid=normal_skill(actor,state['player']['role_id']) if mode=='normal' else 10008
    return dict(base,target_col=target['col'],target_row=target['row'],skill_id=sid)

def plan_round(state,modes=None,target_slot=None,excluded=()):
    battle=state.get('battle',{})
    if not battle.get('active') or battle.get('round',0)<=0:raise ProtocolError('等待伺服器開啟戰鬥回合')
    modes=modes or {}
    inventory=state.get('inventory',{})
    state={**state,'inventory':{**inventory,'reserved':dict(inventory.get('reserved',{}))}}
    excluded=set(excluded)|set(battle.get('commands',{}))
    plans=[]
    for actor in owned_units(state):
        if slot(actor) in excluded:continue
        mode=modes.get(slot(actor),'normal')
        try:
            plan=action_command(state,actor,mode,target_slot)
            for cost in plan.get('resource_reservations',[]):
                key=str(cost['index']);state['inventory']['reserved'][key]=state['inventory']['reserved'].get(key,0)+cost['count']
            plans.append(plan)
        except ProtocolError as exc:raise ProtocolError(f"{actor.get('name',slot(actor))}：{exc}") from exc
    if not plans:raise ProtocolError('本回合可操作單位皆已送出，或沒有存活的本機角色／夥伴')
    return plans
