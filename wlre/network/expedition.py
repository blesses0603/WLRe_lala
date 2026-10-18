"""S31 expedition and outpost layouts from ExpeditionMgr.lua 1262."""
from wlre.network.wire import Reader, ProtocolError


def outpost(r):
    d = {'index': r.u8(), 'npc_id': r.u16(), 'state': r.u8()}
    d['stats'] = {key: r.u16() for key in ('str', 'con', 'int', 'wis', 'agi')}
    d['stats']['level'] = r.u8()
    r.take(5)  # skill levels
    d['faith'] = r.u8()
    d['exp'] = r.u32()
    d['sport_exp'] = r.u8()
    d['use_up_stats'] = r.u16()
    d['stats'].update(degree=r.u8(), potential=r.u8())
    d['modeling'] = r.u16()
    return d


def team(r):
    return {'index': r.u8(), 'minutes': r.u16(),
            'members': [r.u16() for _ in range(4)], 'items': [r.u16() for _ in range(4)],
            'quest': r.u16()}


def decode_expedition(packet):
    if packet.main != 31:
        return None
    r = Reader(packet.payload)
    sub = packet.sub
    if sub == 6:
        event = {'type': 'outpost_snapshot', 'capacity': r.u8()}
        event['roles'] = [outpost(r) for _ in range(r.u8())]
    elif sub in (3, 24):
        event = {'type': 'outpost_role', 'role': outpost(r)}
    elif sub in (5, 26):
        event = {'type': 'outpost_remove', 'index': r.u8()}
    elif sub == 12:
        event = {'type': 'outpost_status', 'index': r.u8(), 'state': r.u8()}
    elif sub == 27:
        event = {'type': 'outpost_faith', 'index': r.u8(), 'faith': r.u8(), 'show': r.u8()}
    elif sub == 35:
        event = {'type': 'outpost_attribute', 'index': r.u8(), 'kind': r.u8(), 'value': r.i32()}
    elif sub == 13:
        event = {'type': 'expedition_snapshot', 'teams': [team(r) for _ in range(10)],
                 'quests': [r.u16() for _ in range(50)]}
        r.take(125 + 15)
        event.update(level=r.u8(), exp=r.u32())
        r.take(27)
    elif sub == 15:
        event = {'type': 'expedition_started'}
    elif sub == 16:
        event = {'type': 'expedition_result', 'result': r.u8(), 'index': r.u8(),
                 'journal': r.u16(), 'history': r.u16()}
        if r.remaining % 9:
            raise ProtocolError('遠征獎勵資料長度錯誤')
        event['rewards'] = [{'kind': r.u8(), 'id': r.u32(), 'value': r.u32()} for _ in range(r.remaining // 9)]
    elif sub == 17:
        event = {'type': 'expedition_time', 'index': r.u8(), 'minutes': r.u16()}
    elif sub == 18:
        event = {'type': 'expedition_team', 'team': team(r)}
    elif sub == 19:
        event = {'type': 'expedition_quests', 'quests': {str(r.u8()): r.u16() for _ in range(50)}}
    elif sub in (20, 25):
        event = {'type': 'expedition_rejected', 'code': r.u8(), 'source': sub}
    elif sub == 21:
        event = {'type': 'expedition_level', 'level': r.u8(), 'exp': r.u32()}
    else:
        return None
    r.end()
    return event
