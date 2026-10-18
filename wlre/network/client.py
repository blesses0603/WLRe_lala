"""User-entered credentials, observed handshake, and manual game commands.

Actual-server interoperability is capture-verified, but a live login from this
implementation still needs to be tested by the account owner.
"""
from wlre.network.connection_health import ConnectionHealth, configure_keepalive
import queue
from wlre.network.state_updates import StatePublisher, notify_state
import socket
import threading
import time
from wlre.network.wire import FrameDecoder, Packet, encode, ProtocolError
from wlre.services.world.portal_travel import PortalTravel
from wlre.services.battle.party import team_command, own_team, expire as expire_team
from wlre.services.items.alchemy import AutoAlchemy
from wlre.services.items.crafting import Crafting
from wlre.services.items.field_supply import FieldSupply
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
        self.field_supply = FieldSupply()
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
        outgoing = []
        kind = event['type']
        self.field_supply.observe(event,state)
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
        return outgoing

    def flush_events(self,state):
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
        kind = command.get('type')
        if kind == 'select_role':
            index = command['index']
            if not self.authenticated or self.selected or state.phase != 'role_selection':
                raise ProtocolError('role selection is not available')
            role = next((r for r in state.roles if r['index'] == index), None)
            if role is None or role['locked']: raise ProtocolError('role is unavailable or locked')
            packet = select_role(index)
            self.selected = True
            state.phase = 'role_selected_awaiting_world'
            return [packet]
        if not self.world_acknowledged: raise ProtocolError('world initialization has not completed')
        if kind in ('start_auto_battle','start_roaming','battle_item'):self.field_supply.check()
        if kind=='craft':return self.crafting.command(state,command)
        if kind in ('start_roaming','start_auto_battle','start_alchemy','field_item','field_storage','learned_action','battle_item') and (state.crafting.get('pending') or state.crafting.get('auto_continue')):
            raise ProtocolError('請先停止製作接續，並等待目前製作操作回覆')
        if kind=='reset_efficiency':
            from wlre.core.efficiency import defaults, observe
            state.efficiency=defaults();observe(state,{'type':'reset_efficiency'})
            return []
        if kind=='chat':
            packet=chat_packet(command,state)
            now=time.monotonic()
            if self.last_chat_time is not None and now-self.last_chat_time<2:raise ProtocolError('發話間隔至少 2 秒，請稍候再試')
            self.last_chat_time=now
            return [packet]
        if kind=='team':return team_command(command,state)
        if kind=='start_alchemy':return self.alchemy.start(state,command)
        if kind=='stop_alchemy':
            self.alchemy.stop(state)
            return []
        if kind in ('start_roaming','walk','portal_walk','portal_direct'):
            team=own_team(state)
            if team and team['leader_id']!=state.player.get('role_id'):raise ProtocolError('隊員跟隨隊長，請先離隊再自主移動')
        if kind == 'set_party_guard':
            self.auto_battle.settings['party_guard']=validate_party_guard(command.get('settings',{}))
            self.auto_battle.status(state,state.auto_battle.get('status','armed'),'必要隊員設定已更新，下次可下令時套用')
            return []
        if kind == 'start_auto_battle':
            self.auto_battle.start(state,command.get('settings',{}))
            return []
        if kind == 'stop_auto_battle':
            self.auto_battle.stop(state)
            return []
        if kind == 'portal_walk':
            if self.roaming.enabled:self.roaming.stop(state,self.movement,'改為前往傳送點')
            self.portal_travel.start(state,self.movement,command['portal_id'],time.monotonic())
            return []
        if kind == 'portal_direct':
            packets = self.portal_travel.start_direct(state,self.movement,command['portal_id'],time.monotonic())
            if packets and self.roaming.enabled:
                self.roaming.stop(state,self.movement,'改為直接觸發出口')
            return packets
        if kind == 'start_roaming':
            self.portal_travel.cancel(state,'改為自動徘徊')
            self.roaming.start(state,self.movement,now=time.monotonic())
            return []
        if kind in ('stop_roaming','stop_walk'):
            self.portal_travel.cancel(state)
            self.roaming.stop(state,self.movement)
            return []
        if kind == 'walk':
            self.portal_travel.cancel(state,'改為手動移動')
            if command.get('scene') is not None and command['scene']!=state.player.get('scene'):
                raise ProtocolError('目的地所屬地圖已變更，請重新選點')
            self.movement.start(state,int(command['x']),int(command['y']),time.monotonic())
            if self.roaming.enabled:self.roaming.manual=True
            return []
        if kind in ('field_item','field_storage'):
            self.field_supply.check()
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
                self.field_supply.begin_storage(state,plan,unit)
                self.movement.stop(state,'等待儲存槽補給回覆')
                return [packet]
            plan=food_command(context,actor,command.get('resource','hp'),command.get('item_id'),target,True,index=command.get('bag_index'))
            self.field_supply.begin(state,plan,context['battle_units'][target])
            self.movement.stop(state,'等待補給回覆')
            reserve(state,plan['resource_reservations'])
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
            if self.round_key!=key:self.round_key,self.sent_units=key,set()
            if (actor['col'],actor['row']) in self.sent_units:raise ProtocolError('本單位本回合已下令')
            target=f"{command['target_col']}:{command['target_row']}"
            if kind=='learned_action':
                plan=learned_command(state.snapshot(),actor,int(command['skill_id']),target)
                packet=cast_skill(actor['col'],actor['row'],plan['target_col'],plan['target_row'],plan['skill_id'])
            else:
                plan=food_command(state.snapshot(),actor,command.get('resource','hp'),int(command['item_id']),target,index=int(command['bag_index']))
                packet=use_battle_item(actor['col'],actor['row'],plan['target_col'],plan['target_row'],plan['item_id'],plan['bag_index'])
            reserve(state,plan['resource_reservations']);self.sent_units.add((actor['col'],actor['row']))
            return [packet]
        if kind == 'battle_submit':
            if (command.get('battle_count'),command.get('round')) != (state.battle_count,state.battle.get('round')):
                raise ProtocolError('戰場或回合已變更，請確認後重新送出')
            for actor in owned_units(state.snapshot()):
                if command.get('actor_pids',{}).get(slot(actor))!=actor['pid']:
                    raise ProtocolError('出戰單位已變更，請確認後重新送出')
            excluded={f'{c}:{r}' for c,r in self.sent_units} if self.round_key==(state.battle_count,state.battle.get('round')) else set()
            plans=plan_round(state.snapshot(),command.get('modes'),command.get('target_slot'),excluded)
            previous_key,previous_units=self.round_key,set(self.sent_units)
            previous_reserved=copy.deepcopy(state.inventory['reserved'])
            try:
                packets=[]
                for action in plans:packets.extend(self.command(action,state))
                return packets
            except (ValueError,KeyError,TypeError):
                self.round_key,self.sent_units=previous_key,previous_units
                state.inventory['reserved']=previous_reserved
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
            if key != self.round_key:
                self.round_key, self.sent_units = key, set()
            if (col, row) in self.sent_units: raise ProtocolError('this unit already submitted a command this round')
            packet = attack(col, row, tc, tr, skill)
            self.sent_units.add((col, row))
            return [packet]
        raise ProtocolError('unknown manual command')


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
                        if command.get('type') in ('team','start_alchemy','stop_alchemy','reset_efficiency','craft') and on_state:notify_state(on_state,state)
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
                before_craft=(state.crafting['status'],state.crafting['pending'],state.crafting['revision'],state.crafting['auto_continue'],repr(state.crafting.get('local_plan')))
                for packet in logic.crafting.tick(state,time.monotonic()):_send_command_packet(connection,packet,profile['tx_xor'],state,emit,on_state)
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
                for packet in ai_packets:_send_command_packet(connection,packet,profile['tx_xor'],state,emit,on_state)
                before_services=(state.alchemy['status'],state.alchemy['pending'],state.alchemy['completed'],state.party['status'])
                service_packets=logic.alchemy.tick(state,time.monotonic())
                expired=expire_team(state)
                for packet in service_packets:_send_command_packet(connection,packet,profile['tx_xor'],state,emit,on_state)
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
                    _send(connection,packet,profile['tx_xor'],emit)
                    movement=decode_outbound_movement(packet)
                    movement['sync_mode']=True
                    state.apply(movement);emit(movement)
                before_portal=state.portal_travel
                for packet in logic.portal_travel.tick(state,logic.movement,time.monotonic()):
                    _send(connection,packet,profile['tx_xor'],emit)
                if on_state and (state.local_movement is not before_tick or state.portal_travel is not before_portal):notify_state(on_state,state)
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
        logic.crafting.disconnect(state)
        logic.alchemy.stop(state,'連線結束')
        logic.portal_travel.cancel(state,'連線結束，已取消傳點移動')
        logic.auto_battle.stop(state,'連線結束')
        logic.roaming.stop(state,logic.movement,'連線結束')
        last_phase = state.phase
        state.phase = 'disconnected'
        if on_state:notify_state(on_state,state,force=True)
        if closed_error is None and stop_event.is_set():closed_reason='stopped'
        health.close(closed_reason,closed_error)
        emit({'type': 'connection_closed', 'last_phase': last_phase, 'reason': closed_reason})
    return state
