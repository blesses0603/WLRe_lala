"""Safe inbound S85/S186 room/status decoders and read-only list requests.

Based on 1262 Lua/Logic/Dungeon.lua, CooperateEventManger.lua and
Lua/Logic/Protocols/Protocols_{085,186}.lua. Mutating client commands are
intentionally NOT exposed; a received success is not implied by a send.
"""
from wlre.network.wire import Packet, Reader, Writer, ProtocolError


def list_request(mode):
    if mode == 'main':
        return Packet(85, 1)
    if mode == 'coop':
        return Packet(186, 17)
    raise ProtocolError('未知副本模式')


def member_request(mode, room_id):
    if not isinstance(room_id, int) or isinstance(room_id, bool) or not (1 <= room_id <= 65535):
        raise ProtocolError('需要已確認的副本房間 ID')
    if mode == 'main':
        return Packet(85, 4, Writer().u16(room_id).build())
    if mode == 'coop':
        return Packet(186, 8, Writer().u16(room_id).build())
    raise ProtocolError('未知副本模式')


def _main(packet):
    r = Reader(packet.payload)
    sub = packet.sub
    if sub == 1:
        count = r.u8()
        if count > 200:
            raise ProtocolError('S85-1 房間筆數異常')
        rows = []
        for _ in range(count):
            rows.append({'room_id': r.u16(), 'manager': r.unicode8(),
                         'members': r.u8(), 'organization': r.unicode8(),
                         'public': r.u8() == 1, 'sn': r.u16()})
        event = {'type': 'instance_room_list', 'mode': 'main', 'rooms': rows}
    elif sub in (2, 3):
        event = {'type': 'instance_result', 'mode': 'main',
                 'action': 'create' if sub == 2 else 'join', 'code': r.u8()}
    elif sub == 4:
        room_id = r.u16()
        count = r.u8()
        if count > 16:
            raise ProtocolError('S85-4 成員數量異常')
        event = {'type': 'instance_members', 'mode': 'main', 'room_id': room_id,
                 'members': [{'role_id': r.u32()} for _ in range(count)]}
    elif sub == 5:
        kind = r.u8()
        event = {'type': 'instance_phase', 'mode': 'main', 'kind': kind}
        if kind == 1:
            event.update(phase=r.u8(), room_id=r.u16(), count=r.u8(),
                         host_id=r.u32())
        elif kind == 5:
            event['kicked_role_id'] = r.u32()
        elif kind not in (2, 3, 4):
            return None
    elif sub == 7:
        event = {'type': 'instance_member_joined', 'mode': 'main',
                 'count': r.u8(), 'role_id': r.u32(), 'room_id': r.u16()}
    elif sub == 9:
        kind = r.u8()
        if kind != 1:
            return None
        event = {'type': 'instance_time', 'mode': 'main', 'minutes': r.u32()}
    elif sub == 10:
        # 1262 Protocols_085.lua, Dungeon.KillEnemy / Set*Score.
        kind = r.u8()
        if kind == 1:
            event = {'type': 'instance_objective', 'mode': 'main', 'kind': kind,
                     'index': r.u8(), 'kills': r.u8(), 'killer': r.unicode8()}
        elif kind == 2:
            event = {'type': 'instance_objective', 'mode': 'main', 'kind': kind,
                     'defeated': r.u8() == 1, 'killer': r.unicode8()}
        elif kind == 3:
            event = {'type': 'instance_objective', 'mode': 'main', 'kind': kind,
                     'index': r.u8(), 'required': r.u8(), 'npc_id': r.u16()}
        elif kind == 4:
            event = {'type': 'instance_objective', 'mode': 'main', 'kind': kind,
                     'npc_id': r.u16()}
        elif kind in (5, 6):
            count = r.u8()
            if count > 16:
                raise ProtocolError('S85-10 積分人數異常')
            event = {'type': 'instance_objective', 'mode': 'main', 'kind': kind,
                     'role_ids': [r.u32() for _ in range(count)]}
        else:
            return None
    elif sub == 12:
        event = {'type': 'instance_member_left', 'mode': 'main',
                 'count': r.u8(), 'role_id': r.u32(), 'host_id': r.u32(),
                 'kicked': r.u32() == 1}
    elif sub == 15:
        event = {'type': 'instance_completed', 'mode': 'main'}
    elif sub == 17:
        event = {'type': 'instance_min_players', 'mode': 'main'}
    elif sub == 21:
        kind = r.u8()
        if kind == 0:
            event = {'type': 'instance_new_info', 'mode': 'main',
                     'kind': kind, 'dungeon_kind': r.u8(), 'phase': r.u8(),
                     'scene': r.u16(), 'host_id': r.u32(),
                     'organization_only': r.u8() != 0, 'remaining': r.u32()}
        elif kind == 1:
            event = {'type': 'instance_new_info', 'mode': 'main',
                     'kind': kind, 'phase': r.u8(), 'remaining': r.u32()}
        elif kind == 2:
            event = {'type': 'instance_new_info', 'mode': 'main',
                     'kind': kind, 'count': r.u32()}
        elif kind == 3:
            event = {'type': 'instance_new_info', 'mode': 'main', 'kind': kind,
                     'index': r.u8(), 'npc_id': r.u16(),
                     'required': r.u8(), 'kills': r.u8()}
        elif kind == 4:
            event = {'type': 'instance_new_info', 'mode': 'main', 'kind': kind,
                     'index': r.u8(), 'member_count': r.u8(),
                     'killer': r.unicode8()}
        elif kind == 5:
            event = {'type': 'instance_new_info', 'mode': 'main', 'kind': kind,
                     'npc_id': r.u16()}
        elif kind == 98:
            event = {'type': 'instance_new_info', 'mode': 'main', 'kind': kind,
                     'text_id': r.u16(), 'player_name': r.unicode8(),
                     'npc_id': r.u16()}
        elif kind == 100:
            # DungeonInfo:SetRecordInfo, count * [role:u32,boss:u8,normal:u8].
            count = r.u8()
            if count > 16:
                raise ProtocolError('S85-21-100 結算人數異常')
            rows = [{'role_id': r.u32(), 'boss': r.u8(), 'normal': r.u8()}
                    for _ in range(count)]
            event = {'type': 'instance_new_info', 'mode': 'main',
                     'kind': kind, 'records': rows}
        elif kind in (6, 99, 101, 102):
            event = {'type': 'instance_new_info', 'mode': 'main', 'kind': kind}
        else:
            return None
    else:
        return None
    r.end()
    return event


def _coop(packet):
    r = Reader(packet.payload)
    sub = packet.sub
    if sub == 2:
        code = r.u8()
        if code in (16, 19):
            role_id = r.u32()
        elif code in (17, 18):
            # CooperateEventManger.RevPKNPCInfo / RevPKPlayerInfo (1262).
            count = r.u8()
            if not 1 <= count <= 8:
                raise ProtocolError('S186-2 協力配對人數異常')
            if code == 17:
                opponents = []
                for _ in range(count):
                    role_id = r.u32()
                    r.take(4)  # level, element, sex, head
                    r.take(8)  # palettes 1 and 5
                    r.unicode8()
                    opponents.append(role_id)
            else:
                first = [r.u32() for _ in range(count)]
                second = [r.u32() for _ in range(count)]
                opponents = first + second
            event = {'type': 'instance_coop_match', 'mode': 'coop',
                     'kind': code, 'opponent_count': count,
                     'roster_role_ids': opponents}
            r.end()
            return event
        else:
            role_id = None
        event = {'type': 'instance_result', 'mode': 'coop', 'code': code,
                 'role_id': role_id}
    elif sub == 3:
        is_created, is_joined = r.u8() != 0, r.u8() != 0
        room_id, standby, kind, npc_id, capacity = r.u16(), r.u8(), r.u8(), r.u8(), r.u8()
        if capacity > 8:
            raise ProtocolError('S186-3 成員容量異常')
        members = []
        for _ in range(capacity):
            entry = {'role_id': r.u32(), 'status': r.u8(),
                     'hp': r.u32(), 'max_hp': r.u32(),
                     'sp': r.u32(), 'max_sp': r.u32()}
            if entry['role_id']:
                members.append(entry)
        event = {'type': 'instance_members', 'mode': 'coop', 'room_id': room_id,
                 'created': is_created, 'joined': is_joined,
                 'standby': standby != 0, 'kind': kind, 'npc_id': npc_id,
                 'capacity': capacity, 'members': members}
    elif sub == 6:
        event = {'type': 'instance_member_refresh_request', 'mode': 'coop',
                 'room_id': r.u16()}
    elif sub == 10:
        # Protocols_186.lua: up to 4 AwardData; kind:u8,id:u32,value:u32.
        # Empty means only a closed dialog, NOT evidence of real awards.
        if r.remaining % 9 or r.remaining > 36:
            raise ProtocolError('S186-10 獎勵格式異常（必須為 0～4 筆各 9 位元組）')
        rewards = [{'kind': r.u8(), 'id': r.u32(), 'value': r.u32()}
                   for _ in range(r.remaining // 9)]
        event = {'type': 'instance_reward_receipt', 'mode': 'coop', 'awards': rewards}
    elif sub == 11:
        event = {'type': 'instance_reward_status', 'mode': 'coop',
                 'reward_count': r.u8(), 'win_stage': r.u8(),
                 'open_reward': r.u8(), 'reward_mark': r.u8(),
                 'npc_id': r.u8()}
    elif sub == 13:
        event = {'type': 'instance_phase', 'mode': 'coop', 'kind': 2}
    elif sub == 15:
        event = {'type': 'instance_fight_count', 'mode': 'coop', 'count': r.u8()}
    elif sub == 17:
        count = r.u16()
        if count > 1000:
            raise ProtocolError('S186-17 房間筆數異常')
        rooms = []
        for _ in range(count):
            rooms.append({'public': r.u8() != 0, 'kind': r.u8(),
                          'npc_id': r.u8(), 'room_id': r.u16(),
                          'capacity': r.u8(), 'members': r.u8(), 'host_id': r.u32()})
        event = {'type': 'instance_room_list', 'mode': 'coop', 'rooms': rooms}
    elif sub == 20:
        event = {'type': 'instance_standby', 'mode': 'coop', 'standby': r.u8() != 0}
    else:
        return None
    r.end()
    return event


def decode_instances(packet):
    if packet.main == 85:
        return _main(packet)
    if packet.main == 186:
        return _coop(packet)
    return None
