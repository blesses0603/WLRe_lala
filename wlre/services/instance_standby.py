"""1262 co-op host standby toggle, using the normal deployed companion.

Official UICheckPlayerList.lua permits the ROOM HOST to toggle standby only
when every slot is occupied. C186-7 sends room ID and status, NOT an NPC ID.
Never deploy, rest, or substitute a companion in this service. The authoritative
S186-3 room snapshot confirms the state; S186-20 alone is informational.
"""
import time

from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.instance_room_flow import _activity_guard

TIMEOUT = 20.0
_OPERATIONS = ('create', 'join', 'leave', 'standby', 'start', 'enter', 'claim', 'cancel')


def _no_unresolved_room_actions(state):
    for data in state.instances.values():
        if data.get('reward_uncertain'):
            raise ProtocolError('協力領獎結果不明，暫停其他副本操作')
        for operation in _OPERATIONS:
            if data.get(operation + '_pending') is not None:
                raise ProtocolError('房間操作尚待伺服器確認，暫不可切換協力準備')
            if data.get(operation + '_uncertain'):
                raise ProtocolError('房間操作結果不明，請重新登入同步後再操作')


def set_standby(state, command, now=None):
    """Return one C186-7 only after a deliberate owner click and strict checks."""
    now = time.monotonic() if now is None else now
    if command.get('mode') != 'coop':
        raise ProtocolError('此準備操作僅支援協力房間')
    desired = command.get('standby')
    if type(desired) is not bool:
        raise ProtocolError('必須明確設定準備或取消準備')
    _activity_guard(state, False)
    _no_unresolved_room_actions(state)
    data = state.instances['coop']
    if state.instances['main'].get('room') is not None:
        raise ProtocolError('目前仍在一般副本房間')
    room = data.get('room') or {}
    room_id = room.get('room_id')
    capacity = room.get('capacity')
    members = data.get('members') or []
    if type(room_id) is not int or not 1 <= room_id <= 65535:
        raise ProtocolError('請先加入伺服器確認的協力房間')
    if data.get('phase') != 'waiting':
        raise ProtocolError('協力房間尚未進入可準備狀態')
    if type(capacity) is not int or not 1 <= capacity <= 8:
        raise ProtocolError('協力房間人數尚未同步')
    # Original UI uses MyRoom.Member[1].ID as the host identity.
    host_id = room['host_id'] if 'host_id' in room else (
        members[0].get('role_id') if members else None)
    if (not members or host_id != state.player.get('role_id')
            or members[0].get('role_id') != host_id):
        raise ProtocolError('只有伺服器確認的房主可以準備／取消準備')
    if len(members) != capacity:
        raise ProtocolError('需要全員到齊才能切換準備狀態')
    current = room.get('standby')
    if type(current) is not bool:
        raise ProtocolError('協力房間準備狀態尚未同步')
    if current is desired:
        raise ProtocolError('伺服器已是相同準備狀態')
    data['standby_pending'] = {
        'room_id': room_id, 'target': desired, 'started': now
    }
    data['status'] = ('準備指令已送出' if desired else '取消準備指令已送出') + '，等待房間資料確認'
    return [Packet(186, 7, Writer().u16(room_id).u8(int(desired)).build())]


def resolve(state, event):
    if event.get('mode') != 'coop':
        return
    data = state.instances['coop']
    pending = data.get('standby_pending')
    if pending is None:
        return
    if event.get('type') == 'instance_members':
        if (event.get('room_id') == pending['room_id']
                and event.get('standby') is pending['target']):
            data['standby_pending'] = None
            data['standby_result'] = pending['target']
            data['status'] = ('協力準備已由伺服器確認'
                              if pending['target'] else '協力取消準備已由伺服器確認')
    elif event.get('type') == 'instance_phase' and event.get('kind') == 2:
        data['standby_pending'] = None
        data['standby_uncertain'] = True
        data['status'] = '房間已退出，準備要求結果不明；本連線禁止重試'


def expire(state, now=None):
    now = time.monotonic() if now is None else now
    data = state.instances['coop']
    pending = data.get('standby_pending')
    if pending is None or now < pending['started'] + TIMEOUT:
        return False
    data['standby_pending'] = None
    data['standby_uncertain'] = True
    data['status'] = '協力準備狀態逾時不明；禁止重送，請重新登入同步'
    return True


def disconnect(state):
    data = state.instances['coop']
    if data.get('standby_pending') is not None:
        data['standby_pending'] = None
        data['standby_uncertain'] = True
        data['status'] = '協力準備時斷線，狀態不明；請重新登入同步'
