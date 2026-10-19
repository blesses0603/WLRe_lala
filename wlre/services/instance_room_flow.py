"""Guarded manual room join/leave: server-confirmed only, no blind retry."""
import time

from wlre.network.wire import ProtocolError
from wlre.network.instance_actions import join_main_room, join_coop_room, leave_room
from wlre.services.battle.party import own_team
from wlre.services.instance_creation import _validated_password

ROOM_LIST_MAX_AGE = 120.0
JOIN_TIMEOUT = 20.0
LEAVE_TIMEOUT = 20.0

MAIN_JOIN_ERRORS = {
    1: '房間已滿', 2: '等級不足', 3: '副本已開始', 4: '房間不存在',
    5: '副本已完成', 6: '無法進入', 7: '所屬組織不符',
    8: '私人房間密碼錯誤', 14: '已參加協力戰',
    15: '乘坐大型交通工具', 16: '所在場景不可進入',
    17: '活動場景不可進入', 255: '伺服器拒絕加入',
}
COOP_JOIN_ERRORS = {
    2: '房間人數已滿', 3: '房間不存在', 4: '已有其他房間',
    5: '活動已完成', 6: '門票不足', 8: '加入時扣點失敗',
    11: '目前位於其他副本', 12: '指定夥伴不符合要求',
    13: '指定夥伴狀態不可變更', 14: '私人房間密碼錯誤',
}


def _data(state, mode):
    if mode not in ('main', 'coop'):
        raise ProtocolError('未知副本類型')
    return state.instances[mode]


def _busy(state):
    return any(
        data.get('room') is not None
        or any(data.get(k) is not None for k in (
            'create_pending', 'join_pending', 'leave_pending', 'standby_pending'))
        or any(data.get(k) for k in (
            'create_uncertain', 'join_uncertain', 'leave_uncertain', 'standby_uncertain'))
        for data in state.instances.values()
    )


def _activity_guard(state, joining):
    if (state.phase != 'world_ready' or not state.initial_data_complete
            or not state.player.get('role_id')):
        raise ProtocolError('請先完成角色登入與世界同步')
    if state.battle.get('active') or state.event_flow.get('blocked'):
        raise ProtocolError('戰鬥或遊戲事件中不可操作副本房間')
    post = state.battle.get('post_event') or {}
    if post and post.get('status') != 'completed':
        raise ProtocolError('請先完成戰後事件')
    if any((state.auto_battle.get('enabled'), state.roaming.get('enabled'),
            state.alchemy.get('enabled'), state.crafting.get('auto_continue'),
            state.expedition.get('enabled'))):
        raise ProtocolError('請先停止自動戰鬥、移動、遠征、煉金與製作')
    if joining and state.activities:
        raise ProtocolError('請先結束其他活動')


def join(state, command, now=None):
    now = time.monotonic() if now is None else now
    mode = command.get('mode')
    data = _data(state, mode)
    _activity_guard(state, True)
    if _busy(state):
        raise ProtocolError('已在房間，或有創房／加入／離開結果待確認')
    if mode == 'coop':
        if own_team(state):
            raise ProtocolError('加入協力房間前請先退出一般隊伍')
        if (data.get('reward') or {}).get('open_reward'):
            raise ProtocolError('協力獎勵尚未領取，不能加入房間')
    updated = data.get('list_updated_at')
    if (not data.get('ready') or updated is None
            or not 0 <= now - updated <= ROOM_LIST_MAX_AGE):
        raise ProtocolError('房間清單已過期，請先手動更新房間')
    room_id = command.get('room_id')
    if isinstance(room_id, bool) or not isinstance(room_id, int):
        raise ProtocolError('請從伺服器房間清單選擇房間')
    sn = command.get('sn')
    room = next((r for r in data.get('rooms', ())
                 if r['room_id'] == room_id
                 and (mode == 'coop' or r['sn'] == sn)), None)
    if room is None:
        raise ProtocolError('該房間已不在最新房間清單，請更新')
    public = room['public']
    password = _validated_password(public, command.get('password'))
    if mode == 'main':
        packet = join_main_room(room_id, room['sn'], public=public,
                                password=password)
    else:
        if (room.get('capacity') is not None
                and room.get('members', 0) >= room['capacity']):
            raise ProtocolError('協力房間已滿，請更新列表')
        if command.get('confirm_cost') is not True:
            raise ProtocolError('協力加入可能消耗門票或點數，必須先確認')
        packet = join_coop_room(room_id, public=public, password=password)
    data['join_pending'] = {
        'room_id': room_id, 'started': now, 'accepted': False}
    data['join_result'] = None
    data['status'] = '已送出加入房間要求，等待伺服器確認'
    return [packet]


def leave(state, command, now=None):
    now = time.monotonic() if now is None else now
    mode = command.get('mode')
    data = _data(state, mode)
    _activity_guard(state, False)
    for part in state.instances.values():
        if any(part.get(k) is not None
               for k in ('create_pending', 'join_pending', 'leave_pending', 'standby_pending', 'start_pending')):
            raise ProtocolError('房間操作仍待確認，不能離房或重複送出')
        if any(part.get(k)
               for k in ('create_uncertain', 'join_uncertain', 'leave_uncertain', 'standby_uncertain', 'start_uncertain')):
            raise ProtocolError('房間操作結果不明，請重新登入同步')
    room = data.get('room')
    if not isinstance(room, dict) or not room.get('room_id'):
        raise ProtocolError('目前沒有已確認的房間')
    if mode == 'main' and data.get('phase') != 'waiting':
        raise ProtocolError('一般副本僅可於等待階段離開房間')
    if mode == 'coop' and data.get('standby'):
        raise ProtocolError('協力準備中不能直接離房，請先取消準備')
    data['leave_pending'] = {'room_id': room['room_id'], 'started': now}
    data['leave_result'] = None
    data['status'] = '已要求離開房間，等待伺服器確認'
    return [leave_room(mode)]


def resolve(state, event):
    mode = event.get('mode')
    if mode not in ('main', 'coop'):
        return
    data = state.instances[mode]
    kind = event.get('type')
    pending = data.get('join_pending')
    if pending:
        if mode == 'main':
            if kind == 'instance_result' and event.get('action') == 'join':
                code = event['code']
                if code == 0:
                    pending['accepted'] = True
                    data['status'] = '伺服器接受加入要求，等待房間狀態'
                else:
                    data['join_pending'] = None
                    data['join_result'] = code
                    data['status'] = ('伺服器拒絕加入：'
                        + MAIN_JOIN_ERRORS.get(code, '拒絕代碼 %d' % code))
            elif (kind == 'instance_phase' and event.get('kind') == 1
                  and event.get('room_id') == pending['room_id']):
                data['join_pending'] = None
                data['join_result'] = 0
                data['status'] = '已加入一般副本房間（伺服器確認）'
        elif kind == 'instance_result':
            code = event['code']
            if code == 10:
                pending['accepted'] = True
                data['status'] = '伺服器確認協力加入／扣點，等待成員名單'
            elif code in COOP_JOIN_ERRORS:
                data['join_pending'] = None
                data['join_result'] = code
                data['status'] = ('伺服器拒絕協力加入：'
                    + COOP_JOIN_ERRORS[code])
        elif (kind == 'instance_members' and event.get('room_id') == pending['room_id']
              and event.get('joined') is True
              and any(m.get('role_id') == state.player.get('role_id')
                      for m in event.get('members', ()))):
            data['join_pending'] = None
            data['join_result'] = 10
            data['status'] = '已加入協力房間（伺服器成員名單確認）'
    if data.get('leave_pending') is None:
        return
    if mode == 'main':
        confirmed = ((kind == 'instance_phase' and event.get('kind') in (2, 4))
                     or (kind == 'instance_member_left'
                         and event.get('role_id') == state.player.get('role_id')))
    else:
        confirmed = kind == 'instance_phase' and event.get('kind') == 2
    if confirmed:
        data['leave_pending'] = None
        data['leave_result'] = 'success'
        data['status'] = '已離開副本房間（伺服器確認）'


def expire(state, now=None):
    now = time.monotonic() if now is None else now
    changed = False
    for data in state.instances.values():
        for operation, timeout in (('join', JOIN_TIMEOUT), ('leave', LEAVE_TIMEOUT)):
            key = operation + '_pending'
            pending = data.get(key)
            if pending is not None and now >= pending['started'] + timeout:
                data[key] = None
                data[operation + '_uncertain'] = True
                data['status'] = ('加入' if operation == 'join' else '離開') + (
                    '結果逾時不明，已禁止重送；請重新登入同步')
                changed = True
    return changed


def disconnect(state):
    for data in state.instances.values():
        for operation in ('join', 'leave'):
            key = operation + '_pending'
            if data.get(key) is not None:
                data[key] = None
                data[operation + '_uncertain'] = True
                data['status'] = '連線中斷，副本房間結果不明；請重新登入同步'
