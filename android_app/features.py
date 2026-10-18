"""Mobile capability contract: only supported core operations cross IPC."""
import copy
import json

GAME_COMMANDS = frozenset(('chat', 'team', 'start_alchemy', 'stop_alchemy', 'craft',
    'reset_efficiency', 'walk', 'stop_walk', 'portal_walk', 'portal_direct',
    'field_item', 'field_storage', 'learned_action', 'battle_item', 'battle_submit',
    'battle_action', 'set_party_guard'))
STATE_FIELDS = ('phase', 'player', 'knowledge', 'inventory', 'potion_storage', 'party',
    'alchemy', 'crafting', 'furniture', 'efficiency', 'battle', 'battle_units', 'battle_count',
    'auto_battle', 'roaming', 'portal_travel', 'event_flow', 'activities', 'location',
    'local_movement', 'movement_check', 'navigation', 'guild', 'attributes')


def checked_command(command):
    if not isinstance(command, dict) or command.get('type') not in GAME_COMMANDS:
        raise ValueError('不支援的操作')
    if len(json.dumps(command, ensure_ascii=False).encode()) > 65536:
        raise ValueError('操作內容過長')
    return copy.deepcopy(command)


def project(state):
    return {key: copy.deepcopy(state[key]) for key in STATE_FIELDS if key in state}


def detail(session):
    from wlre.services.social.chat_names import name_scope
    chat = []
    for row in session.chat_history:
        chat.append({**row, 'name': session.names.name(row.get('role_id', 0), name_scope(row))})
    return dict(state=copy.deepcopy(session.game_state), chat=chat,
                log=list(session.log_history), ai_settings=copy.deepcopy(session.ai_settings),
                preferences=copy.deepcopy(session.preferences), revision=session.detail_revision)
