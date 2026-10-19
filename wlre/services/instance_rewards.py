"""1262 instance completion and cooperative free reward lifecycle.

No client-side instant finish. Normal dungeon completion is S85-15 or
S85-21-100; cooperative win progress/claim is S186-11 and S186-10.
Free rewards use C186-10 only. Paid rewards are never purchased automatically.
A full/reliability-unknown bag stops automatic claims. No blind resend.
"""
import time
from wlre.network.wire import Packet, ProtocolError

REWARD_TIMEOUT = 25.0
ROOM_OPERATIONS = ('create', 'join', 'leave', 'standby', 'start', 'enter')
REWARD_OPS = ('claim', 'cancel')


def _coop(state):
    return state.instances['coop']


def _safe_bag(state):
    bag = state.inventory
    if not bag.get('ready') or not bag.get('reliable'):
        return False
    capacity = bag.get('capacity')
    items = bag.get('items')
    if type(capacity) is not int or not 1 <= capacity <= 255 or not isinstance(items, dict):
        return False
    # The server receipt can have up to four distinct awards; do not infer
    # stackability before knowing actual IDs. This is deliberately conservative.
    if capacity - len(items) < 4:
        return False
    if any(bag.get(k) for k in ('holds', 'alchemy_slots', 'expedition_slots',
                               'maintenance_slots')):
        return False
    if any(v for v in (bag.get('reserved') or {}).values()):
        return False
    if (bag.get('field_supply') or {}).get('pending'):
        return False
    return True


def _guard(state):
    if (state.phase != 'world_ready' or not state.initial_data_complete
            or not state.player.get('role_id')):
        raise ProtocolError('角色或世界同步未完成，不能領取獎勵')
    if state.battle.get('active') or state.event_flow.get('blocked'):
        raise ProtocolError('戰鬥或伺服器事件進行中，禁止領獎')
    post = state.battle.get('post_event') or {}
    if post and post.get('status') != 'completed':
        raise ProtocolError('請等到戰後事件確實完成才可領獎')
    if any((state.maintenance.get('pending'), state.maintenance.get('uncertain'),
            state.expedition.get('pending'), state.alchemy.get('pending'),
            state.crafting.get('pending'))):
        raise ProtocolError('仍有背包／其他工作中的操作待確認，暫停領獎')
    if state.instances['main'].get('room') is not None:
        raise ProtocolError('仍在一般副本房間，不能操作協力領獎')
    for data in state.instances.values():
        for key in ROOM_OPERATIONS:
            if data.get(key + '_pending') is not None or data.get(key + '_uncertain'):
                raise ProtocolError('仍有副本操作未確認，暫停領獎')
    for key in REWARD_OPS:
        if _coop(state).get(key + '_pending') is not None:
            raise ProtocolError('上次領獎／取消仍待伺服器確認')
    if _coop(state).get('reward_uncertain'):
        raise ProtocolError('上次領獎結果不明，禁止再次操作')


def _reward(state):
    value = _coop(state).get('reward')
    if not isinstance(value, dict):
        raise ProtocolError('尚未取得 S186-11 伺服器協力獎勵狀態')
    if type(value.get('open_reward')) is not int:
        raise ProtocolError('協力寶箱種類尚未同步')
    return value


def _fingerprint(value):
    return (value['reward_count'], value['win_stage'], value['open_reward'],
            value['reward_mark'], value['npc_id'])


def set_auto(state, command):
    """Opt in on this login only. Never persisted across accounts/restarts."""
    if command.get('mode') != 'coop' or type(command.get('enabled')) is not bool:
        raise ProtocolError('僅能明確開啟／關閉協力免費獎勵自動領取')
    data = _coop(state)
    if command['enabled']:
        if state.phase != 'world_ready' or not state.initial_data_complete:
            raise ProtocolError('請先登入並完成角色資料同步')
        if data.get('reward_uncertain'):
            raise ProtocolError('領獎結果不明，請重新登入同步')
    data['auto_claim_enabled'] = command['enabled']
    data['auto_claim_note'] = ('已啟用：僅在有免費寶箱且確認包包有四個空位時，自動領取一次'
                               if command['enabled'] else '已關閉免費獎勵自動領取')
    return []


def claim(state, command, now=None):
    if command.get('mode') != 'coop' or command.get('action') != 'free':
        raise ProtocolError('只有協力免費寶箱可使用 C186-10')
    _guard(state)
    reward = _reward(state)
    if reward['open_reward'] != 1:
        raise ProtocolError('伺服器目前沒有可領取的免費協力寶箱')
    if reward['reward_mark'] & 1 == 0:
        raise ProtocolError('伺服器尚未標記可領取的一般獎勵')
    if not _safe_bag(state):
        raise ProtocolError('包包尚未可靠同步／空位不足四格／有保留中的物品，不能安全領取')
    data = _coop(state)
    fingerprint = _fingerprint(reward)
    if data.get('reward_handled_fingerprint') == fingerprint:
        raise ProtocolError('相同寶箱已操作過，尚未收到新的伺服器獎勵狀態')
    now = time.monotonic() if now is None else now
    data['claim_pending'] = {'fingerprint': fingerprint, 'started': now}
    data['claim_result'] = None
    # Never treat awards from a previous successful chest as a new receipt.
    data['received_awards'] = []
    data['reward_handled_fingerprint'] = fingerprint
    data['status'] = '已要求領取免費協力獎勵，等待 S186-10／S186-11；不可重複領取'
    return [Packet(186, 10)]


def cancel(state, command, now=None):
    """Explicit-only paid chest skip; never an automatic purchase or cancel."""
    if command.get('mode') != 'coop' or command.get('confirm_cancel') is not True:
        raise ProtocolError('取消協力獎勵前，必須再次明確確認')
    _guard(state)
    reward = _reward(state)
    if reward['open_reward'] not in (1, 2):
        raise ProtocolError('目前沒有可取消的協力寶箱')
    data = _coop(state)
    fingerprint = _fingerprint(reward)
    if data.get('reward_handled_fingerprint') == fingerprint:
        raise ProtocolError('此寶箱已操作，不能再取消')
    now = time.monotonic() if now is None else now
    data['cancel_pending'] = {'fingerprint': fingerprint, 'started': now}
    data['cancel_result'] = None
    data['reward_handled_fingerprint'] = fingerprint
    data['status'] = '已要求取消協力寶箱，等待官方獎勵狀態確認；不可重發'
    return [Packet(186, 21)]


def resolve(state, event):
    data = _coop(state)
    kind = event.get('type')
    if kind == 'instance_reward_receipt' and event.get('mode') == 'coop':
        # S186-10 carries 0..4 packed AwardData records of exactly 9 bytes.
        pending = data.get('claim_pending')
        if pending is not None and event['awards']:
            data['claim_pending'] = None
            data['claim_result'] = 'confirmed'
            data['received_awards'] = list(event['awards'])
            data['status'] = 'S186-10 獎勵內容已由伺服器確認（不代表所有包包格位已更新）'
        elif pending is not None:
            data['status'] = 'S186-10 未帶獎品，等待 S186-11 狀態回覆確認'
    elif kind == 'instance_reward_status' and event.get('mode') == 'coop':
        reward = _reward(state)
        if reward['reward_count'] > 0 and reward['win_stage'] >= reward['reward_count']:
            data['completed'] = True
            data['completion_source'] = 'S186-11'
        if reward['open_reward'] == 0:
            pending = data.get('claim_pending')
            canceled = data.get('cancel_pending')
            if pending is not None:
                data['claim_pending'] = None
                data['claim_result'] = ('confirmed' if data.get('received_awards')
                                        else 'server_closed_unverified_awards')
                data['status'] = 'S186-11 寶箱已結束；尚無獎品明細請檢查包包／信箱'
            elif canceled is not None:
                data['cancel_pending'] = None
                data['cancel_result'] = 'confirmed'
                data['status'] = '伺服器已確認取消協力寶箱'
            # Reset deduplication only after authoritative clear state.
            data['reward_handled_fingerprint'] = None
        elif data.get('claim_pending') is not None or data.get('cancel_pending') is not None:
            data['status'] = '等待協力獎勵回覆；不可重送'
        elif reward['open_reward'] == 2:
            data['status'] = '伺服器有付費協力寶箱，禁止自動領取或扣點'
        elif reward['open_reward'] == 1:
            data['status'] = '伺服器有免費協力寶箱；可手動或明確啟用自動領取'
    elif kind == 'instance_result' and event.get('mode') == 'coop' and event.get('code') == 15:
        data['mail_notice'] = True
        if data.get('claim_pending'):
            data['status'] = '伺服器通知獎勵已寄送信箱；仍待領獎結果同步'
    elif kind == 'instance_phase' and event.get('mode') == 'coop' and event.get('kind') == 2:
        if data.get('claim_pending') or data.get('cancel_pending'):
            data['reward_uncertain'] = True
            data['claim_pending'] = None
            data['cancel_pending'] = None
            data['status'] = '退出房間時獎勵操作結果不明；禁止重發'


def tick(state, now=None):
    data = _coop(state)
    if not data.get('auto_claim_enabled'):
        return []
    reward = data.get('reward')
    if not isinstance(reward, dict) or reward.get('open_reward') != 1:
        return []
    if not _safe_bag(state):
        data['auto_claim_note'] = '包包同步／空位不足，暫停自動領取（未送出封包）'
        return []
    try:
        return claim(state, {'mode': 'coop', 'action': 'free'}, now)
    except ProtocolError:
        return []


def expire(state, now=None):
    data = _coop(state)
    now = time.monotonic() if now is None else now
    for operation in REWARD_OPS:
        pending = data.get(operation + '_pending')
        if pending is not None and now >= pending['started'] + REWARD_TIMEOUT:
            data[operation + '_pending'] = None
            data['reward_uncertain'] = True
            data['status'] = '協力獎勵操作逾時，結果不明；禁止重送，請重新登入確認'
            return True
    return False


def disconnect(state):
    data = _coop(state)
    data['auto_claim_enabled'] = False
    if any(data.get(operation + '_pending') is not None for operation in REWARD_OPS):
        data['claim_pending'] = None
        data['cancel_pending'] = None
        data['reward_uncertain'] = True
        data['status'] = '領獎期間連線中斷，結果不明；請重新登入'
