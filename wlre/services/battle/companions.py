"""Manual companion deployment: UIPartner.lua, OnClick_Event_Confirm/Rest."""
from wlre.network.wire import Packet, Writer, ProtocolError


def ambiguous_identity(knowledge, npc_id):
    """S19 reports NPC ID but not the companion slot index.

    If duplicates exist, do not infer which copy is active or send a command
    that can unintentionally affect a different companion of the same kind.
    """
    return sum(
        profile.get('ready') is True and profile.get('npc_id') == npc_id
        for profile in knowledge.get('companions', {}).values()
    ) > 1


def problem(state, index, npc_id, action):
    if action not in ('deploy', 'rest'):
        return '不支援的夥伴操作'
    if state.get('phase') != 'world_ready':
        return '請先登入並完成角色資料同步'
    knowledge = state.get('knowledge', {})
    if not knowledge.get('companions_ready'):
        return '等待夥伴清單同步'
    profile = knowledge.get('companions', {}).get(str(index))
    if (type(index) is not int or type(npc_id) is not int or not 1 <= npc_id <= 0xffffffff
            or not profile or not profile.get('ready') or profile.get('npc_id') != npc_id):
        return '夥伴資料已變更，請重新選取'
    if ambiguous_identity(knowledge, npc_id):
        return '存在相同 NPC ID 的多隻夥伴；伺服器未回傳格位身份，暫停切換以免操作錯誤'
    if state.get('battle', {}).get('active'):
        return '請於戰鬥結束後切換夥伴'
    if state.get('event_flow', {}).get('blocked') or (state.get('battle_count') and state.get('battle', {}).get('post_event', {}).get('status') != 'completed'):
        return '請等待伺服器事件結束'
    if state.get('activities'):
        return '請先結束目前活動再操作夥伴'
    if any(state.get(key, {}).get('enabled') for key in ('auto_battle', 'roaming')):
        return '請先停止自動戰鬥與徘徊'
    if state.get('crafting', {}).get('pending') or state.get('crafting', {}).get('auto_continue'):
        return '請先停止製作並等待目前操作回覆'
    active = knowledge.get('active_npc_id') == npc_id
    if action == 'rest' and not active:
        return '此夥伴目前未出戰'
    if action == 'deploy':
        if active:
            return '此夥伴已在出戰中'
        if profile.get('stats', {}).get('can_grow') == 0:
            return '此夥伴僅能跟隨，無法出戰'
    return ''


def command(state, value):
    data = state.snapshot()
    reason = problem(data, value.get('index'), value.get('npc_id'), value.get('action'))
    if reason:
        raise ProtocolError(reason)
    # Use NPC ID, not the companion's bag/index number. Never change local
    # active_npc_id here; S19-1/2/4 remains authoritative.
    return Packet(19, 1, Writer().u32(value['npc_id']).build()) if value['action'] == 'deploy' else Packet(19, 2, b'')
