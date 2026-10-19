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
from wlre.services.battle.party import own_team
from wlre.services.battle.attribute_points import expire as expire_allocation
from wlre.services.expedition import Expedition
from wlre.services.items.alchemy import AutoAlchemy
from wlre.services.items.crafting import Crafting
from wlre.services.items.field_supply import FieldSupply
from wlre.services.items.post_battle_maintenance import PostBattleMaintenance
from wlre.services.social.chat import sent_event
from wlre.network.protocol import login, select_role, decode
from wlre.network.instances import member_request
from wlre.network.command_envelope import validate_command, rejected_command_type
from wlre.network.outbound_observations import observed_outbound
from wlre.core.state import State
from wlre.core.maintenance import PeriodicCleanup
from wlre.services.world.movement import Movement
from wlre.services.world.roaming import Roaming
from wlre.services.battle.auto_battle import AutoBattle


from wlre.network.commands import dispatch
from wlre.services.items import reservations


class LoginRejected(ProtocolError):
    pass


def _send(connection, packet, key, emit):
    connection.sendall(encode(packet, key))
    emit({'type': 'sent', 'main': packet.main, 'sub': packet.sub, 'payload': 'redacted'})


def _send_command_packet(connection, packet, key, state, emit, on_state):
    # Reject malformed candidate command packets BEFORE socket.sendall.
    # An observation records a local send only after the send succeeds.
    observed = observed_outbound(packet)
    _send(connection, packet, key, emit)
    if observed is not None:
        state.apply(observed)
        emit(observed)
        if on_state:
            notify_state(on_state, state)
    if packet.main == 2 and packet.sub in (1, 2, 3, 5, 6):
        emit(sent_event(packet))


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
        self.last_main_roster_room = None
        self.last_coop_roster_refresh = (None, float('-inf'))

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
        # Original Dungeon.SetPlayerDungeonInfo immediately asks C85-4 for
        # authoritative roster after S85-5 kind 1; once per joined room.
        if kind == 'instance_phase' and event.get('mode') == 'main':
            if event.get('kind') in (2, 4):
                self.last_main_roster_room = None
            elif (event.get('kind') == 1 and self.world_acknowledged
                  and event.get('room_id') != self.last_main_roster_room):
                self.last_main_roster_room = event['room_id']
                outgoing.append(member_request('main', event['room_id']))
        # Original S186-6 asks client to request C186-8 for its own room.
        if kind == 'instance_member_refresh_request' and self.world_acknowledged:
            room = state.instances['coop'].get('room') or {}
            rid = event.get('room_id')
            if rid == room.get('room_id') and rid:
                moment = time.monotonic()
                old_room, old_time = self.last_coop_roster_refresh
                if rid != old_room or moment - old_time >= 1:
                    outgoing.append(member_request('coop', rid))
                    self.last_coop_roster_refresh = (rid, moment)

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
        validate_command(command)
        return dispatch(self, command, state)


    def disconnect(self,state):
        """Freeze uncertain bag requests and disable intent before final publication."""
        state.assert_writer()
        from wlre.services.instance_creation import disconnect as instance_disconnect
        instance_disconnect(state)
        from wlre.services.instance_room_flow import disconnect as room_disconnect
        room_disconnect(state)
        from wlre.services.instance_standby import disconnect as standby_disconnect
        standby_disconnect(state)
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
                        if command.get('type') in ('team','start_alchemy','stop_alchemy','reset_efficiency','craft','start_expedition','stop_expedition','allocate_points','instance_create','instance_join','instance_leave','instance_coop_standby') and on_state:notify_state(on_state,state)
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
                        emit({'type': 'command_rejected',
                              'command_type': rejected_command_type(command),
                              'error': str(exc)})
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
