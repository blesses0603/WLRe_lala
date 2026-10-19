"""Route validated manual commands without owning the connection."""
from wlre.services.coordination import command_reason
import time
from wlre.network.wire import ProtocolError
from wlre.network.instances import list_request
from wlre.services.battle.party import team_command, own_team
from wlre.services.battle.attribute_points import allocation as build_allocation, begin as begin_allocation
from wlre.services.battle.companions import command as companion_command
from wlre.services.items.recovery import storage_plan, storage_packet
from wlre.services.social.chat import chat_packet
from wlre.network.protocol import select_role, attack, cast_skill, use_battle_item, use_field_item
from wlre.services.items.combat_resources import learned_command, food_command, reserve, field_context
from wlre.services.items import reservations
import copy
from wlre.services.battle.party_guard import validate as validate_party_guard
from wlre.services.battle.combat import normal_skill, NORMALS
from wlre.services.battle.battle_commands import plan_round, action_command, owned_units, slot

def dispatch(logic,command,state):
    kind = command.get('type')
    if kind == 'select_role':
        index = command['index']
        if not logic.authenticated or logic.selected or state.phase != 'role_selection':
            raise ProtocolError('role selection is not available')
        role = next((r for r in state.roles if r['index'] == index), None)
        if role is None or role['locked']: raise ProtocolError('role is unavailable or locked')
        packet = select_role(index)
        logic.selected = True
        state.phase = 'role_selected_awaiting_world'
        return [packet]
    if not logic.world_acknowledged: raise ProtocolError('world initialization has not completed')
    reason=command_reason(state,command,maintenance_pending=bool(logic.maintenance.pending),
                          maintenance_uncertain=logic.maintenance.uncertain)
    if reason:raise ProtocolError(reason)
    if kind == 'instance_refresh':
        if state.phase != 'world_ready' or not state.player.get('role_id'):
            raise ProtocolError('請先完成角色登入才能查詢副本房間')
        if state.battle.get('active') or state.event_flow.get('blocked'):
            raise ProtocolError('戰鬥或事件處理中不可查詢副本房間')
        return [list_request(command.get('mode'))]
    if kind == 'allocate_points':
        if state.phase != 'world_ready' or not state.player.get('role_id'):
            raise ProtocolError('角色尚未完成登入同步')
        if (state.battle.get('active') or state.event_flow.get('blocked')
                or state.auto_battle.get('enabled') or state.roaming.get('enabled')):
            raise ProtocolError('戰鬥、事件或自動活動中不可配點，請先停止')
        if not state.knowledge.get('player', {}).get('ready'):
            raise ProtocolError('請等待角色能力同步')
        if state.attribute_allocation['pending'] or state.attribute_allocation['uncertain']:
            raise ProtocolError('前次配點未確認，請重新同步')
        packet, expected = build_allocation(
            state.knowledge['player']['stats'], command.get('increments'),
            command.get('baseline'))
        begin_allocation(state, expected)
        return [packet]
    if kind == 'start_expedition':
        logic.expedition.start(state, command.get('settings', {}))
        return []
    if kind == 'stop_expedition':
        logic.expedition.stop(state)
        return []
    if kind == 'companion':
        packet = companion_command(state, command)
        now = time.monotonic()
        if logic.last_companion_time is not None and now - logic.last_companion_time < 2:
            raise ProtocolError('夥伴操作間隔至少 2 秒，請等待伺服器回覆')
        logic.last_companion_time = now
        return [packet]
    if kind in ('start_auto_battle','start_roaming','battle_item'):logic.field_supply.check()
    if kind=='craft':return logic.crafting.command(state,command)
    if kind=='reset_efficiency':
        from wlre.core.efficiency import defaults, observe
        state.efficiency=defaults();observe(state,{'type':'reset_efficiency'})
        return []
    if kind=='chat':
        packet=chat_packet(command,state)
        now=time.monotonic()
        if logic.last_chat_time is not None and now-logic.last_chat_time<2:raise ProtocolError('發話間隔至少 2 秒，請稍候再試')
        logic.last_chat_time=now
        return [packet]
    if kind=='team':return team_command(command,state)
    if kind=='start_alchemy':return logic.alchemy.start(state,command)
    if kind=='stop_alchemy':
        logic.alchemy.stop(state)
        return []
    if kind in ('start_roaming','walk','portal_walk','portal_direct'):
        team=own_team(state)
        if team and team['leader_id']!=state.player.get('role_id'):raise ProtocolError('隊員跟隨隊長，請先離隊再自主移動')
    if kind == 'set_party_guard':
        logic.auto_battle.settings['party_guard']=validate_party_guard(command.get('settings',{}))
        logic.auto_battle.status(state,state.auto_battle.get('status','armed'),'必要隊員設定已更新，下次可下令時套用')
        return []
    if kind == 'start_auto_battle':
        logic.auto_battle.start(state,command.get('settings',{}))
        return []
    if kind == 'stop_auto_battle':
        logic.auto_battle.stop(state)
        return []
    if kind == 'portal_walk':
        if logic.roaming.enabled:logic.roaming.stop(state,logic.movement,'改為前往傳送點')
        logic.portal_travel.start(state,logic.movement,command['portal_id'],time.monotonic())
        return []
    if kind == 'portal_direct':
        packets = logic.portal_travel.start_direct(state,logic.movement,command['portal_id'],time.monotonic())
        if packets and logic.roaming.enabled:
            logic.roaming.stop(state,logic.movement,'改為直接觸發出口')
        return packets
    if kind == 'start_roaming':
        logic.portal_travel.cancel(state,'改為自動徘徊')
        logic.roaming.start(state,logic.movement,now=time.monotonic())
        return []
    if kind in ('stop_roaming','stop_walk'):
        logic.portal_travel.cancel(state)
        logic.roaming.stop(state,logic.movement)
        return []
    if kind == 'walk':
        logic.portal_travel.cancel(state,'改為手動移動')
        if command.get('scene') is not None and command['scene']!=state.player.get('scene'):
            raise ProtocolError('目的地所屬地圖已變更，請重新選點')
        logic.movement.start(state,int(command['x']),int(command['y']),time.monotonic())
        if logic.roaming.enabled:logic.roaming.manual=True
        return []
    if kind in ('field_item','field_storage'):
        logic.field_supply.check()
        if state.alchemy.get('pending'):raise ProtocolError('本次煉金尚待包包回覆，確認後可補給')
        if state.battle.get('active') or state.event_flow.get('blocked') or (state.battle_count and state.battle.get('post_event',{}).get('status')!='completed'):
            raise ProtocolError('等待戰鬥／戰後事件結束後再補給')
        context,actor=field_context(state.snapshot())
        if actor.get('hp',0)<=0:raise ProtocolError('角色尚未恢復，不能使用一般補給')
        npc_index=int(command.get('npc_index',0))
        target=next((key for key,u in context['battle_units'].items() if u.get('npc_index')==npc_index),None)
        if target is None:raise ProtocolError('補給對象不是目前角色／出戰夥伴')
        if kind=='field_storage':
            unit=context['battle_units'][target];resource=command.get('resource','hp')
            if resource not in ('hp','sp') or unit.get('hp',0)<=0:raise ProtocolError('無效的儲存槽補給對象')
            plan=storage_plan(context,unit,resource)
            if not plan:raise ProtocolError('儲存槽不足或目標已恢復')
            packet=storage_packet(resource,npc_index,plan['amount'])
            logic.field_supply.begin_storage(state,plan,unit)
            logic.movement.stop(state,'等待儲存槽補給回覆')
            return [packet]
        plan=food_command(context,actor,command.get('resource','hp'),command.get('item_id'),target,True,index=command.get('bag_index'))
        logic.field_supply.begin(state,plan,context['battle_units'][target])
        logic.movement.stop(state,'等待補給回覆')
        return [use_field_item(plan['item_id'],plan['bag_index'],npc_index)]
    if kind in ('learned_action','battle_item'):
        if not state.battle.get('active') or state.battle.get('round',0)<=0:raise ProtocolError('沒有可下令的戰鬥回合')
        for field,value in (('battle_count',state.battle_count),('round',state.battle.get('round'))):
            if field in command and command[field]!=value:raise ProtocolError('戰場／回合已變更')
        actor=state.battle_units.get(f"{command['col']}:{command['row']}")
        pid=state.player.get('role_id')
        if not actor or not pid or not (actor['pid']==pid or actor['master_id']==pid) or actor['pid']!=command['actor_pid']:
            raise ProtocolError('操作單位已變更或不屬於本機')
        if actor.get('hp',0)<=0 or actor.get('exited'):raise ProtocolError('操作單位已陣亡／離場')
        key=(state.battle_count,state.battle['round'])
        if logic.round_key!=key:logic.round_key,logic.sent_units=key,set()
        if (actor['col'],actor['row']) in logic.sent_units:raise ProtocolError('本單位本回合已下令')
        target=f"{command['target_col']}:{command['target_row']}"
        if kind=='learned_action':
            plan=learned_command(state.snapshot(),actor,int(command['skill_id']),target)
            packet=cast_skill(actor['col'],actor['row'],plan['target_col'],plan['target_row'],plan['skill_id'])
        else:
            plan=food_command(state.snapshot(),actor,command.get('resource','hp'),int(command['item_id']),target,index=int(command['bag_index']))
            packet=use_battle_item(actor['col'],actor['row'],plan['target_col'],plan['target_row'],plan['item_id'],plan['bag_index'])
        reserve(state,plan['resource_reservations']);logic.sent_units.add((actor['col'],actor['row']))
        return [packet]
    if kind == 'battle_submit':
        if (command.get('battle_count'),command.get('round')) != (state.battle_count,state.battle.get('round')):
            raise ProtocolError('戰場或回合已變更，請確認後重新送出')
        for actor in owned_units(state.snapshot()):
            if command.get('actor_pids',{}).get(slot(actor))!=actor['pid']:
                raise ProtocolError('出戰單位已變更，請確認後重新送出')
        excluded={f'{c}:{r}' for c,r in logic.sent_units} if logic.round_key==(state.battle_count,state.battle.get('round')) else set()
        plans=plan_round(state.snapshot(),command.get('modes'),command.get('target_slot'),excluded)
        previous_key,previous_units=logic.round_key,set(logic.sent_units)
        previous_reserved=reservations.checkpoint(state.inventory)
        try:
            packets=[]
            for action in plans:packets.extend(logic.command(action,state))
            return packets
        except (ValueError,KeyError,TypeError):
            logic.round_key,logic.sent_units=previous_key,previous_units
            reservations.restore(state.inventory,previous_reserved)
            raise
    if kind in ('attack','battle_action'):
        if not state.battle.get('active') or state.battle.get('round', 0) <= 0:
            raise ProtocolError('no active command round')
        col, row, tc, tr = (int(command[k]) for k in ('col', 'row', 'target_col', 'target_row'))
        actor = state.battle_units.get(f'{col}:{row}')
        target = state.battle_units.get(f'{tc}:{tr}')
        pid = state.player.get('role_id')
        if not actor or not pid or not (actor['pid'] == pid or actor['master_id'] == pid):
            raise ProtocolError('selected unit does not belong to this player')
        if actor.get('exited') or actor['hp']<=0:raise ProtocolError('操作單位已陣亡或離場')
        if kind=='battle_action':
            if command.get('actor_pid')!=actor['pid']:raise ProtocolError('操作單位已變更')
            resolved=action_command(state.snapshot(),actor,command['mode'],f'{tc}:{tr}' if (tc,tr)!=(0,0) else None)
            tc,tr=resolved['target_col'],resolved['target_row']
            skill=resolved['skill_id']
        else:
            if not target or target.get('exited') or target['hp']<=0 or (col>2)==(tc>2):
                raise ProtocolError('invalid living attacker/opponent')
            requested = command.get('skill_id', 'auto')
            skill = normal_skill(actor, pid) if requested == 'auto' else int(requested)
            if skill not in NORMALS:raise ProtocolError('manual command supports known normal attacks only')
        key = (state.battle_count, state.battle['round'])
        if key != logic.round_key:
            logic.round_key, logic.sent_units = key, set()
        if (col, row) in logic.sent_units: raise ProtocolError('this unit already submitted a command this round')
        packet = attack(col, row, tc, tr, skill)
        logic.sent_units.add((col, row))
        return [packet]
    raise ProtocolError('unknown manual command')
