"""Owner-only normal dungeon C85-7 challenge start (WLRE 1262).

Lua: UICheckPlayerList.OnClick_Event_Confirm, Dungeon.SendStartDungeon.
C85-7 carries NO payload. S85-5 kind=3 is the server's sole start ACK.
The co-op start/match flow is handled by C186-7 in instance_standby.py;
there must never be a duplicate C186 start command.
"""
import time

from wlre.network.wire import Packet, ProtocolError
from wlre.services.instance_browser import entries_for
from wlre.services.instance_room_flow import _activity_guard

START_TIMEOUT = 20.0
OPERATIONS = ('create', 'join', 'leave', 'standby', 'start')


def _pending_or_uncertain(state):
    for part in state.instances.values():
        for name in OPERATIONS:
            if part.get(name + '_pending') is not None:
                raise ProtocolError('副本操作正在等待伺服器回覆，不可重複開始')
            if part.get(name + '_uncertain'):
                raise ProtocolError('前次副本操作結果不明，請重新登入同步')


def start(state, command, now=None):
    if command.get('mode') != 'main':
        raise ProtocolError('協力開始請使用房主準備／開始配對，不能重送另一個開始指令')
    _activity_guard(state, False)
    _pending_or_uncertain(state)
    if state.instances['coop'].get('room') is not None:
        raise ProtocolError('已參加協力房間，不能開始一般副本')
    data = state.instances['main']
    room = data.get('room') or {}
    if data.get('phase') != 'waiting':
        raise ProtocolError('目前不是一般副本等待階段')
    room_id = room.get('room_id')
    if type(room_id) is not int or not 1 <= room_id <= 65535:
        raise ProtocolError('尚未取得伺服器確認的副本房間 ID')
    if room.get('host_id') != state.player.get('role_id'):
        raise ProtocolError('只有房主可以開始副本')
    row = next((r for r in entries_for('main')
                if r.get('kind') == 1 and r.get('map_id') == room_id), None)
    if row is None:
        raise ProtocolError('此副本不在已驗證的 1262 官方一般副本清單')
    members = data.get('members') or ()
    # S85-4 is the authoritative roster; refuse stale/partial snapshots.
    expected_count = room.get('members')
    if (type(expected_count) is not int or expected_count < 1
            or expected_count != len(members)
            or not any(m.get('role_id') == state.player.get('role_id')
                       for m in members)):
        raise ProtocolError('房間成員資料不完整，請先等待伺服器成員同步')
    if len(members) < row['min_members']:
        raise ProtocolError('副本人數未達最低要求（至少 %d 人）' % row['min_members'])
    if len(members) > row['max_members']:
        raise ProtocolError('房間人數超出官方副本上限，請先同步成員')
    # Use an explicit user click. No autonomous trigger in a worker/timer.
    now = time.monotonic() if now is None else now
    data['start_pending'] = {'room_id': room_id, 'started': now}
    data['start_result'] = None
    data['status'] = '房主已送出開始挑戰指令，等待伺服器確認（不可重送）'
    return [Packet(85, 7)]


def resolve(state, event):
    if event.get('mode') != 'main':
        return
    data = state.instances['main']
    pending = data.get('start_pending')
    if pending is None or event.get('type') != 'instance_phase':
        return
    kind = event.get('kind')
    if kind == 3:
        if data.get('room') and data['room'].get('room_id') == pending['room_id']:
            data['start_pending'] = None
            data['start_result'] = 'confirmed'
            data['status'] = '伺服器已確認開始副本，等待後續入場狀態'
    elif kind in (2, 4):
        # The room disappeared while awaiting start ACK. Avoid blind retry.
        data['start_pending'] = None
        data['start_uncertain'] = True
        data['status'] = '副本房間已結束／被移出，開始結果不明；禁止重送'


def expire(state, now=None):
    data = state.instances['main']
    pending = data.get('start_pending')
    now = time.monotonic() if now is None else now
    if pending is None or now < pending['started'] + START_TIMEOUT:
        return False
    data['start_pending'] = None
    data['start_uncertain'] = True
    data['status'] = '開始副本逾時且結果不明；禁止重送，請重新登入同步'
    return True


def disconnect(state):
    data = state.instances['main']
    if data.get('start_pending') is not None:
        data['start_pending'] = None
        data['start_uncertain'] = True
        data['status'] = '開始副本期間連線中斷，結果不明；重新登入同步'
