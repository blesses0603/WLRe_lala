"""NPC 1262 protocol helpers. Manual, single-shot and fail closed."""
from wlre.network.wire import Packet, Reader, Writer, ProtocolError
from wlre.services.world.npc_catalog import NPCIndex


def decode_effect(payload):
    """Official EventManager.ReceiveEventResult S20-1..6 fixed 18-byte header."""
    if len(payload) < 18:
        return None
    r = Reader(payload)
    result = {
        'diagnosis': r.u8(), 'group': r.u16(), 'number': r.u8(),
        'effect_type': r.u8(), 'role_class': r.u8(),
        'parameter': r.u16(), 'style': r.u8(), 'value': r.u32(),
        'mean_number': r.u16(), 'condition': r.u8(), 'event_no': r.u16(),
    }
    result['extension_bytes'] = r.remaining
    return result


def request_npc(state, command):
    """Send one C20-1 only for a verified EventData index in current scene."""
    if command.get('confirmed') is not True:
        raise ProtocolError('請確認本次 NPC 互動；事件可能觸發戰鬥')
    if state.phase != 'world_ready' or not state.player.get('role_id'):
        raise ProtocolError('尚未完成登入及角色同步')
    scene = state.player.get('scene')
    if type(scene) is not int or type(command.get('scene')) is not int or command['scene'] != scene:
        raise ProtocolError('目前場景已改變，請重新選擇 NPC')
    location = state.location
    if not location.get('confirmed_is_current') or (location.get('confirmed') or {}).get('scene') != scene:
        raise ProtocolError('目前位置尚未經伺服器確認')
    if (state.battle.get('active') or state.event_flow.get('blocked')
            or state.npc_dialogue.get('active')
            or (state.battle.get('post_event') or {}).get('status') not in (None, 'completed')):
        raise ProtocolError('戰鬥／事件尚未結束，禁止觸發新 NPC')
    if state.roaming.get('enabled') or (state.local_movement or {}).get('status') in ('running', 'finished'):
        raise ProtocolError('請先停止移動並等待伺服器座標同步')
    from wlre.services.battle.party import own_team
    team = own_team(state)
    if team and team['leader_id'] != state.player['role_id']:
        raise ProtocolError('非隊長不可自行觸發 NPC')
    index, npc_id = command.get('npc_index'), command.get('npc_id')
    if type(index) is not int or type(npc_id) is not int:
        raise ProtocolError('NPC 索引或身分無效')
    try:
        rows = NPCIndex().for_scene(scene)
    except (OSError, ValueError, UnicodeError, EOFError) as exc:
        raise ProtocolError('無法驗證內建官方 NPC 資料，已拒絕互動') from exc
    npc = next((row for row in rows if row['index'] == index and row['npc_id'] == npc_id), None)
    if npc is None or npc['event_count'] == 0:
        raise ProtocolError('NPC 無可用一般事件，或身分／索引未核對')
    if (type(command.get('x')) is not int or type(command.get('y')) is not int
            or (npc['x'], npc['y']) != (command['x'], command['y'])):
        raise ProtocolError('NPC 座標已改變，請重新選取')
    # Unity distance 1.6 has no verified map-grid conversion in LaLa.
    # Never auto-walk: the server's S20-74 checks real interaction distance.
    state.npc_dialogue = {
        'active': True, 'phase': 'requesting', 'scene': scene,
        'npc_id': npc_id, 'npc_index': index,
    }
    state.event_flow = {**state.event_flow, 'blocked': True,
                        'awaiting_response': True, 'last_source': 'C20-1 手動 NPC'}
    return [Packet(20, 1, Writer().u16(index).build())]


def advance_npc(state):
    """Manual one-step C20-6 00. Unknown choices never produce C20-9."""
    info = state.npc_dialogue
    if (not info.get('active') or info.get('phase') not in ('talk', 'continue')
            or state.player.get('scene') != info.get('scene')
            or state.battle.get('active')):
        raise ProtocolError('目前沒有可手動接續的 NPC 對話')
    state.npc_dialogue = {**info, 'phase': 'awaiting_reply'}
    state.event_flow = {**state.event_flow, 'blocked': True,
                        'awaiting_response': True,
                        'last_source': 'C20-6 NPC 手動接續',
                        'requests_sent': state.event_flow.get('requests_sent', 0) + 1}
    return [Packet(20, 6, b'\x00')]
