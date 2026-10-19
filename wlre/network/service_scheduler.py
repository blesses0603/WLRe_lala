"""Advance independent services in a stable order within the network thread."""
import time
from wlre.network.state_updates import notify_state
from wlre.network.protocol import decode_outbound_movement
from wlre.services.battle.party import expire as expire_team
from wlre.services.instance_creation import expire as expire_instance_create
from wlre.services.instance_room_flow import expire as expire_instance_room
from wlre.services.instance_standby import expire as expire_instance_standby
from wlre.services.instance_start import expire as expire_instance_start

def advance_services(logic,state,send_command,send_raw,emit,on_state):
    state.assert_writer()
    before_maintenance=state.maintenance
    for packet in logic.maintenance.tick(state,logic,time.monotonic()):
        send_command(packet)
    if state.maintenance != before_maintenance:
        emit({'type':'maintenance_status',**state.maintenance})
        if on_state:notify_state(on_state,state)
    before_expedition = (state.expedition['status'], state.expedition['pending'], state.expedition['enabled'])
    for packet in logic.expedition.tick(state,time.monotonic()):
        send_command(packet)
    if before_expedition != (state.expedition['status'], state.expedition['pending'], state.expedition['enabled']) and on_state:
        notify_state(on_state,state)
    if expire_instance_create(state) and on_state:
        notify_state(on_state,state)
    if expire_instance_room(state) and on_state:
        notify_state(on_state,state)
    if expire_instance_standby(state) and on_state:
        notify_state(on_state,state)
    if expire_instance_start(state) and on_state:
        notify_state(on_state,state)
    before_craft=(state.crafting['status'],state.crafting['pending'],state.crafting['revision'],state.crafting['auto_continue'],repr(state.crafting.get('local_plan')))
    for packet in logic.crafting.tick(state,time.monotonic()):send_command(packet)
    if before_craft!=(state.crafting['status'],state.crafting['pending'],state.crafting['revision'],state.crafting['auto_continue'],repr(state.crafting.get('local_plan'))) and on_state:notify_state(on_state,state)
    supply_event=logic.field_supply.tick(state,time.monotonic())
    if supply_event:
        emit(supply_event)
        if logic.field_supply.uncertain:
            logic.auto_battle.stop(state,supply_event['reason'])
            logic.roaming.stop(state,logic.movement,'補給結果未確認')
            emit({'type':'auto_battle_status',**state.auto_battle})
        if on_state:notify_state(on_state,state)
    before_ai=state.auto_battle
    ai_packets=logic.auto_battle.tick(state,logic,time.monotonic())
    if state.auto_battle is not before_ai:
        emit({'type':'auto_battle_status',**state.auto_battle})
        if on_state:notify_state(on_state,state)
    for packet in ai_packets:send_command(packet)
    before_services=(state.alchemy['status'],state.alchemy['pending'],state.alchemy['completed'],state.party['status'])
    service_packets=logic.alchemy.tick(state,time.monotonic())
    expired=expire_team(state)
    for packet in service_packets:send_command(packet)
    after_services=(state.alchemy['status'],state.alchemy['pending'],state.alchemy['completed'],state.party['status'])
    if (expired or before_services!=after_services) and on_state:notify_state(on_state,state)
    before_roaming=state.roaming
    logic.roaming.tick(state,logic.movement,time.monotonic())
    if state.roaming is not before_roaming:
        emit({'type':'roaming_status',**state.roaming})
        if on_state:notify_state(on_state,state)
    before_tick=state.local_movement
    packets=logic.movement.tick(state,time.monotonic())
    for packet in packets:
        send_raw(packet)
        movement=decode_outbound_movement(packet)
        movement['sync_mode']=True
        state.apply(movement);emit(movement)
    before_portal=state.portal_travel
    for packet in logic.portal_travel.tick(state,logic.movement,time.monotonic()):
        send_raw(packet)
    if on_state and (state.local_movement is not before_tick or state.portal_travel is not before_portal):notify_state(on_state,state)
