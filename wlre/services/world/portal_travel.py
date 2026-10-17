"""Walk to a selected exit, then run Role.SendMeetDoor exactly once.

Door indices are matched against Eve NewDoor data, never list row numbers.
Server S7-1/S12-1 remains authoritative for the resulting map and position.
"""
import math
from wlre.services.world.portals import Portals
from wlre.services.world.portal_policy import destination_problem
from wlre.network.wire import Packet, Writer, ProtocolError
from wlre.services.world.navigation import NavigationError


class PortalTravel:
    timeout = 15.0

    def __init__(self, catalog=None):
        self.catalog = catalog
        self.pending = None
        self.deadline = None
        self.event_finished = False
        self.request_flow = None

    def status(self, state, status, reason):
        state.portal_travel = {**state.portal_travel, 'status': status, 'reason': reason}

    def release_request_wait(self, state):
        # Only release our unanswered request, never a server event or battle gate.
        # Every authoritative event transition replaces event_flow with a new dict.
        if self.request_flow is not None and state.event_flow is self.request_flow:
            state.event_flow = {**state.event_flow, 'blocked': False,
                                'awaiting_response': False, 'last_source': '傳點請求等待已結束'}
        self.request_flow = None

    def cancel(self, state, reason='使用者停止傳點移動'):
        if self.pending:
            self.status(state, 'cancelled', reason)
        self.release_request_wait(state)
        self.pending = None
        self.deadline = None
        self.event_finished = False

    def start(self, state, movement, portal_id, now):
        if self.pending:
            if self.pending['id'] == portal_id:
                return  # repeated list clicks cannot restart or re-send a trigger
            raise ProtocolError('傳點移動尚未結束，請先停止移動')
        self.catalog = self.catalog or Portals()
        portal = next((p for p in self.catalog.for_scene(state.player.get('scene'))
                       if p['id'] == portal_id), None)
        if portal is None:
            raise ProtocolError('傳點不屬於目前地圖，請重新選取')
        problem = destination_problem(portal)
        if problem:raise ProtocolError(problem)
        scene, x, y = self.catalog.target(portal, state.player.get('scene'))
        points = portal.get('approach_points') or [(x, y)]
        error = None
        for x, y in points:
            try:
                movement.start(state, x, y, now)
                break
            except NavigationError as exc:
                error = exc
        else:
            raise ProtocolError('無法從目前位置走到此出口的已確認入口範圍：'+str(error))
        self.pending = dict(portal, x=x, y=y, role_id=state.player['role_id'])
        self.deadline = None
        self.event_finished = False
        state.portal_travel = {'status': 'moving', 'reason': portal['transition_note'],
                               'portal_id': portal['id'], 'name': portal['name'],
                               'scene': scene, 'destination': portal.get('destination'),
                               'door_index': portal.get('door_index'),
                               'walk_target': {'x': x, 'y': y}}

    def start_direct(self, state, movement, portal_id, now):
        if self.pending:
            if self.pending['id'] == portal_id:
                return []
            raise ProtocolError('已有出口請求等待回覆，請勿連續切換傳點')
        if not state.player.get('role_id'):
            raise ProtocolError('尚未確認本機角色，不能觸發出口')
        if state.battle.get('active'):
            raise ProtocolError('戰鬥中不能觸發出口')
        if state.event_flow.get('blocked'):
            raise ProtocolError('等待目前伺服器事件結束後再觸發出口')
        self.catalog = self.catalog or Portals()
        portal = next((p for p in self.catalog.for_scene(state.player.get('scene'))
                       if p['id'] == portal_id), None)
        if portal is None:
            raise ProtocolError('傳點不屬於目前地圖，請重新選取')
        problem = destination_problem(portal)
        if problem:raise ProtocolError(problem)
        index = self.catalog.direct_target(portal, state.player.get('scene'))
        # No path construction, coordinates, position reports, or local map edits.
        movement.stop(state, '已停止步行，改為直接觸發出口')
        self.pending = dict(portal, role_id=state.player['role_id'], mode='direct',
                            origin_x=state.player.get('x'), origin_y=state.player.get('y'))
        self.deadline = now + self.timeout
        self.event_finished = False
        state.portal_travel = {'mode':'direct','status':'awaiting_map',
            'reason':'已直接送出出口觸發指令，等待伺服器確認；未執行尋路',
            'portal_id':portal['id'],'name':portal['name'],'scene':portal['scene'],
            'destination':portal.get('destination'),'door_index':index,'walk_target':None}
        state.event_flow = {**state.event_flow,'blocked':True,'awaiting_response':True,
                            'last_source':f'C20-8 direct door={index}'}
        self.request_flow = state.event_flow
        return [Packet(20, 8, Writer().u16(index).build())]

    def observe(self, event, state, movement):
        p = self.pending
        if not p:
            return
        kind = event['type']
        if kind == 'position_snapshot' and event['role_id'] == p['role_id']:
            if self.deadline is not None:
                expected = p.get('destination')
                if p.get('mode') == 'direct' and event['scene'] == p['scene']:
                    # A same-map location sync alone does not prove a transfer.
                    if expected != p['scene'] or (event['x'],event['y']) == (p['origin_x'],p['origin_y']):
                        return
                matched = expected is None or event['scene'] == expected
                self.status(state, 'completed' if matched else 'different_map',
                            '伺服器已確認換圖與抵達座標' if matched else '伺服器傳送至其他地圖，以實際回覆為準')
                state.portal_travel['arrival'] = {k: event[k] for k in ('scene', 'x', 'y')}
                self.release_request_wait(state)
                self.pending = None; self.deadline = None
                return
            self.cancel(state, '收到本機位置校正，請重新選取傳點')
        elif kind == 'event_rejected' and self.deadline is not None:
            self.status(state, 'rejected', event['reason'])
            self.release_request_wait(state)
            self.pending = None; self.deadline = None
        elif kind == 'event_end' and self.deadline is not None:
            # Resolve after the receive batch; a map notification can follow S20-8.
            self.event_finished = True
        elif (state.player.get('role_id') != p['role_id'] or
              state.player.get('scene') != p['scene'] or kind == 'world_player'):
            self.cancel(state, '角色或地圖已改變')
        elif state.battle.get('active'):
            self.cancel(state, '遇戰，已取消傳點觸發；戰後請重新選取')
        elif self.deadline is None and state.local_movement and state.local_movement.get('status') == 'stopped':
            self.cancel(state, state.local_movement.get('reason', '移動已停止'))

    def tick(self, state, movement, now):
        p = self.pending
        if not p:
            return []
        if self.deadline is not None:
            if self.event_finished:
                self.status(state, 'no_transfer', '出口事件已結束，尚未收到換圖通知；可能需要任務或其他條件')
                self.release_request_wait(state)
                self.pending = None; self.deadline = None
                return []
            if now >= self.deadline:
                self.release_request_wait(state)
                reason = ('伺服器事件仍在進行，等待 S20-8' if state.event_flow.get('blocked')
                          else '未收到換圖確認，已解除本機傳點等待；伺服器可能未接受遠距觸發')
                self.status(state, 'timeout', '等候換圖逾時，未自動重送；'+reason)
                self.pending = None; self.deadline = None
            return []
        local = state.local_movement or {}
        if (state.player.get('role_id') != p['role_id'] or state.player.get('scene') != p['scene']
                or state.battle.get('active') or state.event_flow.get('blocked')
                or state.navigation.get('stale') or local.get('status') == 'stopped'):
            self.cancel(state, '移動、戰鬥、事件或導航狀態改變，已取消出口觸發')
            return []
        if movement.active or local.get('status') != 'finished':
            return []
        if (local.get('scene') != p['scene'] or
                local.get('target', {}).get('x') != p['x'] or local.get('target', {}).get('y') != p['y'] or
                math.hypot(local.get('x', -999999)-p['x'], local.get('y', -999999)-p['y']) > 2):
            self.cancel(state, '終點與選取出口不符，未觸發出口')
            return []
        index = p.get('door_index')
        if not index:
            self.status(state, 'walk_only', p['transition_note'])
            self.pending = None
            return []
        bounds = p.get('trigger_bounds')
        if bounds and not (bounds[0]-1e-6 <= local['x'] <= bounds[2]+1e-6 and
                           bounds[1]-1e-6 <= local['y'] <= bounds[3]+1e-6):
            self.cancel(state, '終點未進入已確認的出口範圍，未觸發出口')
            return []
        # Role.TriggerDoorEvent -> SendMeetDoor UInt16; wait for server event/map.
        self.deadline = now + self.timeout
        self.status(state, 'awaiting_map', '已抵達出口並送出觸碰指令，等待伺服器換圖')
        state.event_flow = {**state.event_flow, 'blocked': True, 'awaiting_response': True,
                            'last_source': f'C20-8 door={index}'}
        self.request_flow = state.event_flow
        return [Packet(20, 8, Writer().u16(index).build())]
