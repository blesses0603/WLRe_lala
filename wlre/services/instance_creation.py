"""Safely start exactly one manual dungeon room creation per game session.

All state is owned by the network thread. Pending is NOT completion. Unknown
results are frozen for the rest of this login to avoid duplicate spending.
"""
import time
from wlre.network.wire import ProtocolError
from wlre.network.instance_actions import create_main_room, create_coop_room
from wlre.services.instance_browser import entries_for
from wlre.services.battle.party import own_team

CREATE_TIMEOUT = 20.0
COOP_REJECTIONS = {
    1: '房間額滿', 2: '人數額滿', 3: '房間不存在', 4: '已有房間',
    5: '今日活動已完成', 6: '門票不足', 7: '建立房間扣點失敗',
    8: '扣點失敗', 11: '目前正在副本', 12: '指定出戰夥伴不符合',
    13: '指定夥伴狀態不符', 14: '私人房間密碼錯誤',
}
MAIN_REJECTIONS = {
    1: '房間額滿', 2: '等級不足', 3: '已完成挑戰', 4: '冷卻中',
    7: '副本時間已到', 8: '目前場景不可傳送', 9: '目前狀態不可傳送',
    11: '副本尚未開放', 13: '訊息不合規', 14: '已參加協力戰',
    15: '乘坐大型交通工具', 16: '目前為組織活動場景', 17: '活動場景禁止操作',
}


def _validated_password(public, password):
    if type(public) is not bool:
        raise ProtocolError('請明確選擇公開或私人')
    if public:
        if password not in (None, '', '0'):
            raise ProtocolError('公開房間不得填密碼')
        return 0
    if not isinstance(password, str) or len(password) != 4 or not password.isascii() or not password.isdecimal():
        raise ProtocolError('私人房間密碼必須是四位 ASCII 數字')
    if password == '0000':
        raise ProtocolError('私人房間密碼不可為 0000')
    return int(password)


def create(state, command, now=None):
    now = time.monotonic() if now is None else now
    if state.phase != 'world_ready' or not state.initial_data_complete or not state.player.get('role_id'):
        raise ProtocolError('請先完成角色及世界資料同步')
    mode = command.get('mode')
    if mode not in ('main', 'coop'):
        raise ProtocolError('副本類型無效')
    if any(part.get('room') is not None or any(
           part.get(k) is not None for k in ('create_pending', 'join_pending', 'leave_pending', 'standby_pending', 'start_pending', 'claim_pending', 'cancel_pending', 'enter_pending'))
           or any(part.get(k) for k in ('create_uncertain','join_uncertain','leave_uncertain','standby_uncertain','start_uncertain', 'reward_uncertain', 'enter_uncertain'))
           for part in state.instances.values()):
        raise ProtocolError('已有房間／創房結果待確認；請勿重複建立')
    if state.battle.get('active') or state.event_flow.get('blocked'):
        raise ProtocolError('戰鬥或事件進行中不可創房')
    if state.battle.get('post_event') and state.battle['post_event'].get('status') != 'completed':
        raise ProtocolError('請先完成戰後事件')
    if (state.auto_battle.get('enabled') or state.roaming.get('enabled')
            or state.alchemy.get('enabled') or state.crafting.get('auto_continue')
            or state.expedition.get('enabled')):
        raise ProtocolError('請先停止自動戰鬥、移動、製作、煉金或遠征')
    if mode == 'coop' and own_team(state):
        raise ProtocolError('協力創房前請先離開一般隊伍')
    if (mode == 'coop' and (state.instances['coop'].get('reward') or {}).get('open_reward')):
        raise ProtocolError('協力獎勵待處理，不可建立房間')
    public = command.get('public')
    password = _validated_password(public, command.get('password'))
    if mode == 'main':
        map_id = command.get('map_id')
        row = next((x for x in entries_for('main')
                    if x['kind'] == 1 and x['map_id'] == map_id), None)
        if row is None:
            raise ProtocolError('請選擇經 1262 官方確認的一般副本')
        packet = create_main_room(map_id, public=public, password=password)
        expected = {'map_id': map_id, 'kind': 1}
    else:
        dungeon_id = command.get('dungeon_id')
        row = next((x for x in entries_for('coop')
                    if x['id'] == dungeon_id), None)
        if row is None:
            raise ProtocolError('請選擇經官方確認的協力活動')
        if command.get('confirm_cost') is not True:
            raise ProtocolError('協力創房可能消耗門票或點數，請確認後再送出')
        # Cooperate creation never deploys, rests, or swaps companions.
        # The client's current normal active companion remains unchanged.
        # Optional follower bonuses (if introduced in later game versions)
        # must not be represented as automatically granted.
        capacity = command.get('player_count')
        packet = create_coop_room(dungeon_id, capacity, public=public, password=password)
        # Match the exact C186-1 / S186-3 event NPC index. Named events
        # (IDs 27 and 28) use 1 and 2, not zero.
        expected = {'dungeon_id': dungeon_id, 'kind': row['variant'],
                    'npc_id': row['npc_id'] if row['variant'] == 2 else 0}
        # Keep only public activity identity for late, server-proven recovery.
        state.instances[mode]['create_attempt'] = dict(expected)
    state.instances[mode]['create_pending'] = {
        **expected, 'started': now, 'ack': False, 'public': public}
    state.instances[mode]['create_result'] = None
    state.instances[mode]['status'] = '已提交創房指令，等待伺服器確認（請勿重複操作）'
    return [packet]


def resolve(state, event):
    mode = event.get('mode')
    if mode not in ('main', 'coop'):
        return
    data = state.instances[mode]
    pending = data.get('create_pending')
    attempt = pending or data.get('create_attempt')
    if not attempt:
        return
    kind = event.get('type')
    if mode == 'main':
        if not pending:
            return
        if kind == 'instance_result' and event.get('action') == 'create':
            code = event['code']
            data['create_result'] = code
            if code:
                data['create_pending'] = None
                data['status'] = '伺服器拒絕創房：' + MAIN_REJECTIONS.get(code, '代碼 %d' % code)
            else:
                pending['ack'] = True
                data['status'] = '伺服器已接受建立要求，等待房間資訊'
        elif (kind == 'instance_phase' and event.get('kind') == 1
              and event.get('room_id') == pending['map_id']
              and event.get('host_id') == state.player.get('role_id')):
            # S85-5 contains the authoritative host and map ID; the explicit
            # host match distinguishes create from an unrelated room join.
            data['create_pending'] = None
            data['create_result'] = 0
            data['status'] = '建立副本房間成功（已確認房主與房間 ID）'
    else:
        if kind == 'instance_result' and pending:
            code = event['code']
            if code in COOP_REJECTIONS:
                data['create_result'] = code
                data['create_pending'] = None
                data['create_attempt'] = None
                data['status'] = '伺服器拒絕協力創房：' + COOP_REJECTIONS[code]
            elif code == 9:
                pending['ack'] = True
                data['create_result'] = 9
                data['status'] = '協力創房／扣點回覆成功，等待房間同步'
        elif kind == 'instance_members':
            members = event.get('members') or ()
            host_id = event.get('host_id')
            if host_id is None and members:
                host_id = members[0].get('role_id')
            # A trusted S186-3 room roster proves successful creation even
            # when the first created=True notification was missed. Only the
            # matching activity AND first-slot host can resolve a timeout.
            if (type(event.get('room_id')) is int and event['room_id'] > 0
                    and event.get('kind') == attempt['kind']
                    and event.get('npc_id') == attempt['npc_id']
                    and host_id == state.player.get('role_id')
                    and members and members[0].get('role_id') == host_id):
                data['create_pending'] = None
                data['create_uncertain'] = False
                data['create_attempt'] = None
                data['create_result'] = 9
                data['status'] = '協力創房成功，已由伺服器房主與活動資訊確認'


def expire(state, now=None):
    now = time.monotonic() if now is None else now
    changed = False
    for data in state.instances.values():
        pending = data.get('create_pending')
        if pending is not None and now >= pending['started'] + CREATE_TIMEOUT:
            data['create_pending'] = None
            data['create_uncertain'] = True
            data['status'] = '創房逾時且結果不明；已禁止重送，請重新登入同步房間狀態'
            changed = True
    return changed


def disconnect(state):
    for data in state.instances.values():
        if data.get('create_pending') is not None:
            data['create_pending'] = None
            data['create_uncertain'] = True
            data['status'] = '連線中斷且創房結果不明；下次登入需重新同步'
