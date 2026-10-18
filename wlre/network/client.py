"""User-entered credentials, observed handshake, and manual game commands.

Actual-server interoperability is capture-verified, but a live login from this
implementation still needs to be tested by the account owner.
"""
from wlre.network.service_scheduler import advance_services
from wlre.network.connection_health import ConnectionHealth, configure_keepalive
import queue
from wlre.network.state_updates import StatePublisher, notify_state
import socket
import threading
import time
from wlre.network.wire import FrameDecoder, Packet, encode, ProtocolError
from wlre.services.world.portal_travel import PortalTravel
from wlre.services.battle.party import team_command, own_team, expire as expire_team
from wlre.services.battle.attribute_points import allocation as build_allocation, begin as begin_allocation, expire as expire_allocation
from wlre.services.battle.companions import command as companion_command
from wlre.services.expedition import Expedition
from wlre.services.items.alchemy import AutoAlchemy
from wlre.services.items.crafting import Crafting
from wlre.services.items.field_supply import FieldSupply
from wlre.services.items.post_battle_maintenance import PostBattleMaintenance
from wlre.services.items.recovery import storage_plan, storage_packet
from wlre.services.social.chat import chat_packet, sent_event
from wlre.network.protocol import login, select_role, decode, attack, cast_skill, use_battle_item, use_field_item
from wlre.services.items.combat_resources import learned_command, food_command, reserve, field_context
import copy
from wlre.network.protocol import decode_outbound_movement
from wlre.core.state import State
from wlre.core.maintenance import PeriodicCleanup
from wlre.services.world.movement import Movement
from wlre.services.world.roaming import Roaming
from wlre.services.battle.auto_battle import AutoBattle
from wlre.services.battle.party_guard import validate as validate_party_guard
from wlre.services.battle.combat import normal_skill, NORMALS
from wlre.services.battle.battle_commands import plan_round, action_command, owned_units, slot


from wlre.network.commands import dispatch
from wlre.services.items import reservations


class LoginRejected(ProtocolError):
    pass


def _send(connection, packet, key, emit):
    connection.sendall(encode(packet, key))
    emit({'type': 'sent', 'main': packet.main, 'sub': packet.sub, 'payload': 'redacted'})


def _send_command_packet(connection,packet,key,state,emit,on_state):
    _send(connection,packet,key,emit)
    if packet.main==50 and packet.sub in (1,2):
        data=packet.payload
        event={'type':'battle_command_sent','col':data[0],'row':data[1],
               'target_col':data[2],'target_row':data[3],
               'skill_id':int.from_bytes(data[4:6],'little') if packet.sub==1 else 10024}
        if packet.sub==2:event.update(item_id=int.from_bytes(data[4:6],'little'),bag_index=data[8])
        state.apply(event);emit(event)
        if on_state:notify_state(on_state,state)
    if (packet.main,packet.sub)==(23,15):
        event={'type':'field_item_sent','bag_index':packet.payload[0],'item_id':int.from_bytes(packet.payload[1:3],'little'),'npc_index':packet.payload[7]}
        state.apply(event);emit(event)
        if on_state:notify_state(on_state,state)
    if (packet.main,packet.sub)==(23,147):
        event={'type':'field_storage_sent','resource':'hp' if packet.payload[0]==3 else 'sp','npc_index':packet.payload[2],'amount':int.from_bytes(packet.payload[3:5],'little')}
        state.apply(event);emit(event)
        if on_state:notify_state(on_state,state)
    if packet.main==2 and packet.sub in (1,2,3,5,6):emit(sent_event(packet))
    movement=decode_outbound_movement(packet)
    if movement:
        state.apply(movement);emit(movement)
        if on_state:notify_state(on_state,state)


def verify_account(endpoint, profile, account, password, emit, stop_event, timeout=10):
    """Perform ELogin.ServerList=0 verification using freshly entered credentials."""
    parser = FrameDecoder(profile['rx_xor'])
    deadline = time.monotonic() + timeout
    with socket.create_connection((endpoint['host'], endpoint['port']), timeout=min(5, timeout)) as connection:
        connection.settimeout(0.25)
        if stop_event.wait(0.1): raise ProtocolError('verification cancelled')
        request = login(account, password, 0, profile['platform'], profile['language'])
        _send(connection, request, profile['tx_xor'], emit)
        while not stop_event.is_set() and time.monotonic() < deadline:
            try: raw = connection.recv(65536)
            except socket.timeout: continue
            if not raw: raise ProtocolError('verification server closed before a result')
            for packet in parser.feed(raw):
                if (packet.main, packet.sub) == (1, 23):
                    _send(connection, Packet(63, 5), profile['tx_xor'], emit)
                elif (packet.main, packet.sub) == (63, 7):
                    event = decode(packet)
                    emit(dict(event, type='verification_result'))
                    if event['login_kind'] != 0: raise ProtocolError('unexpected verification login kind')
                    if event['result'] != 0: raise LoginRejected(f"account verification rejected: result {event['result']}")
                    return
    raise ProtocolError('verification cancelled' if stop_event.is_set() else 'account verification timed out')


class SessionLogic:
    """Deterministic reactions shared by network operation and tests."""
    def __init__(self, role_index=None):
        self.last_chat_time = None
        self.last_companion_time = None
        self.field_supply = FieldSupply()
        self.maintenance = PostBattleMaintenance()
        self.expedition = Expedition()
        self.expedition_time_requested = False
        self.crafting = Crafting()
        self.alchemy = AutoAlchemy()
        self.movement = Movement()
        self.portal_travel = PortalTravel()
        self.roaming = Roaming()
        self.auto_battle = AutoBattle()
        self.role_index = role_index
        self.authenticated = False
        self.selected = False
        self.world_acknowledged = False
        self.sent_units = set()
        self.round_key = None
        self.pending_event = False
        self.post_battle_due = None
        self.battle_exit_key = None
        self.announced_war_style = None

    def receive(self, event, state):
        state.assert_writer()
        outgoing = []
        kind = event['type']
        self.expedition.observe(event,state)
        self.field_supply.observe(event,state)
        self.maintenance.observe(event,state)
        self.crafting.observe(event,state)
        self.alchemy.observe(event,state)
        if kind in ('team_join','team_list','team_new_leader'):
            team=own_team(state)
            if team and team['leader_id']!=state.player.get('role_id'):
                self.movement.stop(state,'隊員跟隨隊長，暫停自主移動')
                self.portal_travel.cancel(state,'隊員跟隨隊長')
        self.movement.observe(event,state)
        self.portal_travel.observe(event,state,self.movement)
        if (self.world_acknowledged and kind == "position_snapshot"
                and event["role_id"] == state.player.get("role_id")):
            # Stage.ReceiveChangeMap / Role.OnPlayerAppear. Own packets only.
            previous_scene = getattr(self, "acknowledged_scene", None)
            if previous_scene != event["scene"]:
                outgoing.append(Packet(12, 1))
            outgoing.append(Packet(3, 2))
            self.acknowledged_scene = event["scene"]
        if kind=='war_style':self.announced_war_style=event['value']
        elif kind=='battle_start':
            if self.post_battle_due is not None:self.pending_event=False
            self.post_battle_due=None
            if self.announced_war_style is not None:
                state.battle['war_style']=self.announced_war_style
                self.announced_war_style=None
        if kind=='event_continue_permission':self.pending_event=True
        elif kind=='event_end':
            self.pending_event=False
            self.post_battle_due=None
            if state.battle.get('post_event'):
                state.battle['post_event']['status']='completed'
        pid=state.player.get('role_id')
        own_exit=(kind=='fight_exit' and pid is not None and event['role_id']==pid)
        if kind=='battle_unit_exit':
            unit=state.battle_units.get(f"{event['col']}:{event['row']}",{})
            own_exit=pid is not None and unit.get('pid')==pid
        key=(state.battle_count,pid)
        if own_exit and state.battle_count>0 and key!=self.battle_exit_key:
            self.battle_exit_key=key
            self.announced_war_style=None
            state.battle['active']=False
            # FightOver waits EndTime=2.5, then SendServerEvent calls C20-6 00.
            # Cooperative event fights have an additional wait-UI/count branch.
            if state.battle.get('war_style')==16:
                state.battle['post_event']={'status':'cooperative_wait',
                    'reason':'協力事件戰鬥的等待／場次分支尚未實作，未自動回覆'}
            else:
                self.post_battle_due=time.monotonic()+2.5
                state.battle['post_event']={'status':'exit_delay','source':kind,'delay_seconds':2.5}
                state.event_flow={**state.event_flow,'blocked':True,
                    'last_source':'本機戰鬥退場，準備 C20-6 00'}
        self.roaming.observe(event,state,self.movement)
        if kind == 'heartbeat_request': outgoing.append(Packet(63, 5))
        elif kind == 'login_result':
            if event['result'] != 0: raise LoginRejected(f"login rejected: result {event['result']}")
            if event['login_kind'] != 2: raise ProtocolError('unexpected formal login kind')
            self.authenticated = True
        elif kind == 'role_list_available' and self.role_index is not None:
            outgoing += self.command({'type': 'select_role', 'index': self.role_index}, state)
        if state.player and state.initial_data_complete and not self.world_acknowledged:
            outgoing.extend([Packet(12, 1), Packet(3, 2)])
            self.world_acknowledged = True
            state.phase = 'world_ready'
            self.acknowledged_scene = state.player.get('scene')
        if (self.world_acknowledged and state.expedition['ready'] and state.expedition['outpost_ready']
                and not self.expedition_time_requested):
            outgoing.append(Packet(31, 28))  # ExpeditionMgr.RequestTime; no paid refresh
            self.expedition_time_requested = True
        return outgoing

    def flush_events(self,state):
        state.assert_writer()
        # Lua grants set one boolean; its Update sends once after the packet batch.
        if self.post_battle_due is not None:
            if time.monotonic()<self.post_battle_due:return []
            self.post_battle_due=None
            self.pending_event=True
        if not self.pending_event or not self.world_acknowledged:return []
        self.pending_event=False
        if state.battle.get('post_event'):
            state.battle['post_event']['status']='awaiting_response'
        state.event_flow={**state.event_flow,'blocked':True,'awaiting_response':True,
                          'requests_sent':state.event_flow['requests_sent']+1}
        return [Packet(20,6,b'\x00')]

    def command(self, command, state):
        state.assert_writer()
        return dispatch(self,command,state)


    def disconnect(self,state):
        """Freeze uncertain bag requests and disable intent before final publication."""
        state.assert_writer()
        if any(state.inventory.get('holds',{}).values()):
            state.inventory['reliable']=False
            for owner in list(state.inventory['holds']):reservations.uncertain(state.inventory,owner)
        if self.field_supply.pending:
            self.field_supply.uncertain=True
            self.field_supply.status(state,'uncertain','連線結束，補給結果未確認，請重新登入同步')
        if self.maintenance.pending:
            self.maintenance.uncertain=True
            self.maintenance.status(state,'連線結束，修理／整理結果未確認',checking=False)
        if self.expedition.pending:state.expedition['uncertain']=True
        self.expedition.stop(state,'連線結束，遠征自動派遣已停止')
        self.crafting.disconnect(state)
        self.alchemy.stop(state,'連線結束')
        self.portal_travel.cancel(state,'連線結束，已取消傳點移動')
        self.auto_battle.stop(state,'連線結束')
        self.roaming.stop(state,self.movement,'連線結束')


def run_client(host, port, profile, emit, *, account=None, password=None,
               login_kind=2, platform=None, language=None, role_index=None,
               duration=15, timeout=5, verify_first=False, stop_event=None,
               commands=None, on_state=None, snapshot_interval=0, tcp_keepalive=False):
    if duration is not None and duration <= 0 or timeout <= 0:
        raise ProtocolError('duration and timeout must be positive')
    if snapshot_interval<0:raise ProtocolError('snapshot_interval must not be negative')
    if on_state and snapshot_interval:
        on_state=StatePublisher(on_state,snapshot_interval)
    stop_event = stop_event or threading.Event()
    commands = commands or queue.Queue()
    profile = dict(profile)
    for key in ('rx_xor', 'tx_xor'):
        if not isinstance(profile[key], int) or not 0 <= profile[key] <= 255:
            raise ProtocolError('wire XOR values must be bytes')
    profile['platform'] = platform if platform is not None else profile.get('platform')
    profile['language'] = language if language is not None else profile.get('language')
    if account is not None:
        if login_kind != 2: raise ProtocolError('use verify_first for account verification; formal login kind must be 2')
        if profile['platform'] is None or profile['language'] is None:
            raise ProtocolError('login requires observed platform and language values')
        request = login(account, password, 2, profile['platform'], profile['language'])
        if verify_first:
            endpoint = profile.get('verification_endpoint')
            if not endpoint: raise ProtocolError('profile has no verification endpoint')
            emit({'type': 'verifying_account'})
            verify_account(endpoint, profile, account, password, emit, stop_event)
    else:
        request = None
    if stop_event.is_set(): return State()
    state = State(phase='connecting')
    parser, logic = FrameDecoder(profile['rx_xor']), SessionLogic(role_index)
    deadline = time.monotonic() + duration if duration is not None else float('inf')
    health = ConnectionHealth(emit)
    cleanup_timer = PeriodicCleanup()
    closed_reason = 'duration'; closed_error = None
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            if tcp_keepalive: health.keepalive = configure_keepalive(connection)
            connection.settimeout(0.05)
            health.publish(force=True)
            state.phase = 'connected'
            emit({'type': 'connected', 'server_compatibility_verified': False,
                  'wire_observed_in_capture': bool(profile.get('capture_sha256'))})
            if request:
                if stop_event.wait(0.1): return state
                _send(connection, request, profile['tx_xor'], emit)
            while not stop_event.is_set() and time.monotonic() < deadline:
                if cleanup_timer.due():
                    removed = state.clear_position_history()
                    emit({'type': 'periodic_cleanup', 'positions_removed': removed})
                health.publish()
                if expire_allocation(state) and on_state:notify_state(on_state,state)
                if isinstance(on_state,StatePublisher):on_state.flush(state)
                event_replies=logic.flush_events(state) if request else []
                for response in event_replies:_send(connection,response,profile['tx_xor'],emit)
                if event_replies and on_state:notify_state(on_state,state)
                for _ in range(20):
                    try: command = commands.get_nowait()
                    except queue.Empty: break
                    try:
                        for packet in logic.command(command, state):
                            _send_command_packet(connection,packet,profile['tx_xor'],state,emit,on_state)
                        if command.get('type') in ('team','start_alchemy','stop_alchemy','reset_efficiency','craft','start_expedition','stop_expedition','allocate_points') and on_state:notify_state(on_state,state)
                        if command.get('type') in ('start_auto_battle','stop_auto_battle','set_party_guard'):
                            emit({'type':'auto_battle_status',**state.auto_battle})
                            if on_state:notify_state(on_state,state)
                        if command.get('type') in ('start_roaming','stop_roaming'):
                            emit({'type':'roaming_status',**state.roaming})
                            if on_state:notify_state(on_state,state)
                        if command.get('type') in ('walk','stop_walk','portal_walk','portal_direct'):
                            emit({'type':'local_movement','status':state.local_movement['status'],
                                  'scene':state.player.get('scene'),'target':state.local_movement['target'],
                                  'reason':state.local_movement['reason']}) if state.local_movement else None
                            if on_state:notify_state(on_state,state)
                    except (ValueError, KeyError, TypeError) as exc:
                        emit({'type': 'command_rejected', 'command_type':command.get('type'), 'error': str(exc)})
                advance_services(logic,state,
                    lambda packet:_send_command_packet(connection,packet,profile['tx_xor'],state,emit,on_state),
                    lambda packet:_send(connection,packet,profile['tx_xor'],emit),emit,on_state)
                try: raw = connection.recv(65536)
                except socket.timeout: continue
                if not raw:
                    closed_reason = 'server_closed'
                    break
                for packet in parser.feed(raw):
                    event = decode(packet,state.player.get('role_id'))
                    health.received()
                    state.apply(event)
                    emit(event)
                    if request:
                        for response in logic.receive(event, state):
                            _send(connection, response, profile['tx_xor'], emit)
                    if on_state and event['type'] != 'unimplemented': notify_state(on_state,state)
                event_replies=logic.flush_events(state) if request else []
                for response in event_replies:_send(connection,response,profile['tx_xor'],emit)
                if event_replies and on_state:notify_state(on_state,state)
            if not stop_event.is_set(): parser.finish()
            else: closed_reason = 'stopped'
    except OSError as exc:
        closed_reason = 'network_error'; closed_error = exc
        raise
    except Exception as exc:
        closed_reason = 'client_error'; closed_error = exc
        raise
    finally:
        logic.disconnect(state)
        last_phase = state.phase
        state.phase = 'disconnected'
        if on_state:notify_state(on_state,state,force=True)
        if closed_error is None and stop_event.is_set():closed_reason='stopped'
        health.close(closed_reason,closed_error)
        emit({'type': 'connection_closed', 'last_phase': last_phase, 'reason': closed_reason})
    return state
