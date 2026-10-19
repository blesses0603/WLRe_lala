"""1262-verified candidate room packet construction.

Layouts: Lua/Logic/Dungeon.lua C85-{3,5,6,7,9}; Lua/Logic/
CooperateEventManger.lua C186-{1,4,5,7,10}. Packet builders themselves never send. Only the guarded manual
instance_create command (with authoritative ACK and timeout handling) can
send creation packets. Join/leave and combat remain disabled. No passwords
or recruitment text are logged.
"""
from wlre.network.wire import Packet, Writer, ProtocolError
from wlre.services.instance_browser import entries_for


def _int(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ProtocolError('%s 超出允許範圍' % label)
    return value


def _password(public, password, maximum):
    if not isinstance(public, bool):
        raise ProtocolError('公開／私人設定必須明確指定')
    if public:
        if password not in (0, None):
            raise ProtocolError('公開房間不可附帶私人密碼')
        return 0
    return _int(password, 1, maximum, '私人房間密碼')


def _main_stage(map_id):
    map_id = _int(map_id, 1, 65535, '副本場景 ID')
    if not any(row['kind'] == 1 and row['map_id'] == map_id
               for row in entries_for('main')):
        raise ProtocolError('不是已核對的 1262 一般副本場景')
    return map_id


def _coop_details(dungeon_id):
    dungeon_id = _int(dungeon_id, 1, 65535, '協力副本 ID')
    row = next((r for r in entries_for('coop') if r['id'] == dungeon_id), None)
    if row is None:
        raise ProtocolError('不是已核對的 1262 協力副本')
    if row['variant'] not in (1, 2):
        raise ProtocolError('不支援的協力活動種類')
    npc_idx = row['npc_id'] if row['variant'] == 2 else 0
    return row, row['variant'], _int(npc_idx, 0, 255, '協力活動索引')


def create_main_room(map_id, *, public, password=0):
    """C85-3. Recruit flag is explicitly zero, no unverified Unicode message."""
    map_id = _main_stage(map_id)
    password = _password(public, password, 65535)
    payload = Writer().u16(map_id).u8(int(public)).u16(password)
    if public:
        payload.u8(0)  # isRecruit=false; private format has no recruit byte
    return Packet(85, 3, payload.build())


def create_coop_room(dungeon_id, player_count, *, public, password=0):
    """C186-1. User must confirm any admission cost before this is sent."""
    row, kind, npc_idx = _coop_details(dungeon_id)
    player_count = _int(player_count, row['min_members'], row['max_members'],
                        '協力房間人數')
    password = _password(public, password, 4294967295)
    return Packet(186, 1, Writer().u8(player_count).u8(kind).u8(npc_idx)
                  .u8(int(public)).u32(password).u8(0).build())


def join_main_room(room_id, sn, *, public, password=0):
    """C85-5. SN must be taken from the actual S85-1 room listing."""
    room_id = _int(room_id, 1, 65535, '副本房間 ID')
    sn = _int(sn, 0, 65535, '伺服器房間 SN')
    password = _password(public, password, 65535)
    data = Writer().u16(room_id).u16(sn)
    if not public:
        data.u16(password)
    return Packet(85, 5, data.build())


def join_coop_room(room_id, *, public, password=0):
    """C186-4. Room ID and privacy must come from S186-17."""
    room_id = _int(room_id, 1, 65535, '協力房間 ID')
    password = _password(public, password, 4294967295)
    return Packet(186, 4, Writer().u16(room_id).u32(password).build())


def leave_room(mode):
    if mode == 'main':
        return Packet(85, 6)
    if mode == 'coop':
        return Packet(186, 5)
    raise ProtocolError('未知副本類型')
