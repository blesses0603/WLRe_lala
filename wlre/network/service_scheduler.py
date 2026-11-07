"""Advance independent services in a stable order within the network thread."""
import time
from wlre.network.state_updates import notify_state
from wlre.network.protocol import decode_outbound_movement
from wlre.services.battle.party import expire as expire_team
from wlre.services.instance_creation import expire as expire_instance_create
from wlre.services.instance_room_flow import expire as expire_instance_room
from wlre.services.instance_standby import expire as expire_instance_standby
from wlre.services.instance_start import expire as expire_instance_start
from wlre.services.instance_entry import expire as expire_instance_entry
from wlre.services.instance_rewards import tick as tick_instance_rewards, expire as expire_instance_rewards
from wlre.services.world.tent import expire as expire_tent
from wlre.network.resource_safety import observe_hold

def auto_battle_status_event(state):
    """Publish only numeric, session-local battle evidence for safe diagnostics."""
    battle = state.battle
    pid = state.player.get('role_id')
    owned_living = sum(
        1 for unit in state.battle_units.values()
        if pid is not None and (unit.get('pid') == pid or unit.get('master_id') == pid)
        and unit.get('hp', 0) > 0 and not unit.get('exited'))
    return {
        'type': 'auto_battle_status', **state.auto_battle,
        'battle_war_style': battle.get('war_style'),
        'battle_round': battle.get('round'),
        'battle_active': bool(battle.get('active')),
        'battle_count': state.battle_count,
        'owned_living': owned_living,
    }


def maintenance_trace_event(state, logic, now):
    """Expose only action class and elapsed time, never slots, items or names."""
    guard = logic.maintenance
    pending = guard.pending
    phase = ('uncertain' if guard.uncertain else 'pending' if pending
             else 'checking' if state.maintenance.get('checking') else 'idle')
    action = pending.get('action') if pending else 'none'
    if action not in ('repair', 'sell', 'delete'):
        action = 'none'
    elapsed = 0
    if pending and type(pending.get('due')) in (int, float):
        elapsed = max(0, min(3600, int(now - (pending['due'] - guard.timeout))))
    return {'type': 'maintenance_trace', 'phase': phase, 'action': action,
            'elapsed_s': elapsed, 'battle_count': state.battle_count,
            'completed': state.maintenance.get('completed', 0)}


def advance_services(logic,state,send_command,send_raw,emit,on_state):
    state.assert_writer()
    # Hold is checked at each service boundary. A started synchronous batch
    # finishes intact; pending-only branches below never create new requests.
    observe_hold(logic, state)
    before_storage=state.room_storage['revision']
    logic.room_storage.tick(state,time.monotonic())
    if before_storage!=state.room_storage['revision'] and on_state:notify_state(on_state,state)
    before_maintenance=state.maintenance
    before_maintenance_ai=state.auto_battle
    maintenance_now=time.monotonic()
    held = observe_hold(logic, state)
    maintenance_packets = (logic.maintenance.tick(state,logic,maintenance_now)
                           if not held or logic.maintenance.pending else [])
    for packet in maintenance_packets:
        send_command(packet)
    if state.maintenance != before_maintenance:
        emit({'type':'maintenance_status',**state.maintenance})
        if on_state:notify_state(on_state,state)
    # A maintenance timeout may stop AI inside maintenance.tick, before the AI tick.
    if state.auto_battle is not before_maintenance_ai:
        emit(auto_battle_status_event(state))
        if on_state:notify_state(on_state,state)
    trace=maintenance_trace_event(state,logic,maintenance_now)
    trace_key=(trace['phase'],trace['action'],trace['battle_count'],trace['completed'])
    guard=logic.maintenance
    if (trace_key != guard.trace_key or
            trace['phase'] in ('pending', 'uncertain') and
            (guard.trace_at is None or maintenance_now - guard.trace_at >= 10)):
        guard.trace_key=trace_key
        guard.trace_at=maintenance_now
        emit(trace)
    before_expedition = (state.expedition['status'], state.expedition['pending'], state.expedition['enabled'])
    held = observe_hold(logic, state)
    expedition_packets = (logic.expedition.tick(state,time.monotonic())
                          if not held or logic.expedition.pending else [])
    for packet in expedition_packets:
        send_command(packet)
    if before_expedition != (state.expedition['status'], state.expedition['pending'], state.expedition['enabled']) and on_state:
        notify_state(on_state,state)
    if expire_tent(state) and on_state:
        notify_state(on_state,state)
    if expire_instance_create(state) and on_state:
        notify_state(on_state,state)
    if expire_instance_room(state) and on_state:
        notify_state(on_state,state)
    if expire_instance_standby(state) and on_state:
        notify_state(on_state,state)
    if expire_instance_start(state) and on_state:
        notify_state(on_state,state)
    if expire_instance_entry(state) and on_state:
        notify_state(on_state,state)
    if expire_instance_rewards(state) and on_state:
        notify_state(on_state,state)
    reward_packets = [] if observe_hold(logic, state) else tick_instance_rewards(state)
    for packet in reward_packets:
        send_command(packet)
        if on_state:
            notify_state(on_state,state)
    before_craft=(state.crafting['status'],state.crafting['pending'],state.crafting['revision'],state.crafting['auto_continue'],repr(state.crafting.get('local_plan')))
    held = observe_hold(logic, state)
    if not held:
        craft_packets = logic.crafting.tick(state,time.monotonic())
    elif logic.crafting.pending:
        # Only settle the already-sent request. Plan.tick can enqueue more work
        # after a confirmation, even when an incoming update re-enables a flag.
        craft_packets = logic.crafting._server_tick(state,time.monotonic())
    else:
        craft_packets = []
    for packet in craft_packets:send_command(packet)
    if before_craft!=(state.crafting['status'],state.crafting['pending'],state.crafting['revision'],state.crafting['auto_continue'],repr(state.crafting.get('local_plan'))) and on_state:notify_state(on_state,state)
    supply_event=logic.field_supply.tick(state,time.monotonic())
    if supply_event:
        emit(supply_event)
        if logic.field_supply.uncertain:
            logic.auto_battle.stop(state,supply_event['reason'],source='field_supply_uncertain')
            logic.roaming.stop(state,logic.movement,'補給結果未確認')
            emit(auto_battle_status_event(state))
        if on_state:notify_state(on_state,state)
    before_ai=state.auto_battle
    ai_packets=([] if observe_hold(logic, state) else
                logic.auto_battle.tick(state,logic,time.monotonic()))
    if state.auto_battle is not before_ai:
        emit(auto_battle_status_event(state))
        if on_state:notify_state(on_state,state)
    for packet in ai_packets:send_command(packet)
    before_services=(state.alchemy['status'],state.alchemy['pending'],state.alchemy['completed'],state.party['status'])
    held = observe_hold(logic, state)
    service_packets=(logic.alchemy.tick(state,time.monotonic())
                     if not held or logic.alchemy.pending else [])
    expired=expire_team(state)
    for packet in service_packets:send_command(packet)
    after_services=(state.alchemy['status'],state.alchemy['pending'],state.alchemy['completed'],state.party['status'])
    if (expired or before_services!=after_services) and on_state:notify_state(on_state,state)
    before_roaming=state.roaming
    if not observe_hold(logic, state):
        logic.roaming.tick(state,logic.movement,time.monotonic())
    if state.roaming is not before_roaming:
        emit({'type':'roaming_status',**state.roaming})
        if on_state:notify_state(on_state,state)
    before_tick=state.local_movement
    packets=([] if observe_hold(logic, state) else
             logic.movement.tick(state,time.monotonic()))
    for packet in packets:
        send_raw(packet)
        movement=decode_outbound_movement(packet)
        movement['sync_mode']=True
        state.apply(movement);emit(movement)
    before_portal=state.portal_travel
    held = observe_hold(logic, state)
    portal_packets=(logic.portal_travel.tick(state,logic.movement,time.monotonic())
                    if not held or logic.portal_travel.deadline is not None else [])
    for packet in portal_packets:
        send_raw(packet)
    if on_state and (state.local_movement is not before_tick or state.portal_travel is not before_portal):notify_state(on_state,state)

    before_flow=dict(state.automation)
    flow_packets=([] if observe_hold(logic, state) else
                  logic.flows.tick(logic,state,time.monotonic()))
    for packet in flow_packets:
        send_command(packet)
    if (flow_packets or state.automation!=before_flow) and on_state:notify_state(on_state,state)

    from wlre.services.time_cube import tick as tick_cube
    before_cube=dict(state.time_cube)
    held = observe_hold(logic, state)
    cube_packets=(tick_cube(state,logic.world_acknowledged and not held,time.monotonic())
                  if not held or state.time_cube['pending'] else [])
    for packet in cube_packets:send_command(packet)
    if (cube_packets or state.time_cube!=before_cube) and on_state:notify_state(on_state,state)

    from wlre.services.daily_tasks import tick as tick_daily
    before_daily=dict(state.daily_tasks)
    held = observe_hold(logic, state)
    daily_packets=(tick_daily(state,logic.world_acknowledged and not held,time.monotonic())
                  if not held or state.daily_tasks['pending'] else [])
    for packet in daily_packets:send_command(packet)
    if (daily_packets or state.daily_tasks!=before_daily) and on_state:notify_state(on_state,state)

    from wlre.services.social.guild_actions import tick as tick_guild
    before_guild=dict(state.guild_actions)
    held = observe_hold(logic, state)
    guild_packets=(tick_guild(state,logic.world_acknowledged and not held,time.monotonic())
                  if not held or state.guild_actions['pending'] else [])
    for packet in guild_packets:send_command(packet)
    if (guild_packets or state.guild_actions!=before_guild) and on_state:notify_state(on_state,state)

    from wlre.services.star_ark import tick as tick_ark
    before_ark=dict(state.star_ark)
    held = observe_hold(logic, state)
    ark_packets=(tick_ark(state,logic.world_acknowledged and not held,time.monotonic())
                  if not held or state.star_ark['pending'] else [])
    for packet in ark_packets:send_command(packet)
    if (ark_packets or state.star_ark!=before_ark) and on_state:notify_state(on_state,state)
