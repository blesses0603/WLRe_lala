"""Read-only roster decoding from 1262 Guild.lua; no guessed guild requests."""
from wlre.network.wire import Reader, ProtocolError


def _profile(r):
    name = r.unicode8()
    r.take(6 + 8 + 1)  # level/job/degree/element/sex/head, palettes, frame
    r.take(r.u8() * 6)  # equipment: UInt16 item + UInt32 design
    r.take(4 + 3 + 1)  # area/birthday, MaxInterest=3, card setting
    r.unicode8()  # signature
    r.take(8)  # last online OADate
    return name


def decode_guild(packet):
    if packet.main != 39 or packet.sub not in (2, 6, 7, 8, 10, 60):
        return None
    r = Reader(packet.payload)
    event = {'main': 39, 'sub': packet.sub}
    if packet.sub == 2:
        name, chief = r.unicode8(), r.unicode8()
        members = {}
        for _ in range(r.u8()):
            rid = r.u32()
            member_name = _profile(r)
            r.take(1 + 4 + 4 + 1 + 2 + 1)  # rank/development/state/score/index
            if not rid or str(rid) in members:
                raise ProtocolError('invalid or duplicate guild member ID')
            members[str(rid)] = {'role_id': rid, 'name': member_name}
        r.unicode8()  # rules
        r.take(1 + 1 + 1 + 16)  # ally/badge/level, four UInt32 values
        r.take(3 + 1 + 6)  # hashtags, auto accept, building levels
        r.take(1 + 1 + 2 + 4 + 1 + 1 + 1)  # box/exp/wins/party/abyss/level limit
        serial = r.u32()
        event.update(type='guild_roster', name=name, chief=chief,
                     serial=serial, members=members)
    elif packet.sub == 60:
        event.update(type='guild_member_profile', role_id=r.u32(), name=_profile(r))
    elif packet.sub in (6, 8):
        event.update(type='guild_member_removed' if packet.sub == 6 else 'guild_member_added',
                     role_id=r.u32())
    elif packet.sub == 7:
        event.update(type='guild_leave_result', result=r.u8(), role_id=r.u32())
    else:
        event.update(type='guild_disband_result', result=r.u8())
    r.end()
    return event


def apply_guild(state, event):
    kind = event['type']
    if kind == 'guild_roster':
        state.guild = {'ready': True, 'name': event['name'], 'serial': event['serial'],
                       'members': {key: dict(value) for key, value in event['members'].items()}}
    elif kind == 'guild_member_profile':
        member = state.guild.get('members', {}).get(str(event['role_id']))
        if member is not None:
            member['name'] = event['name']
    elif kind == 'guild_member_added' and state.guild.get('ready'):
        state.guild['members'].setdefault(str(event['role_id']),
                                         {'role_id': event['role_id'], 'name': ''})
    elif kind == 'guild_member_removed':
        state.guild.get('members', {}).pop(str(event['role_id']), None)
    elif ((kind == 'guild_leave_result' and event['result'] == 0
           and event['role_id'] == state.player.get('role_id'))
          or (kind == 'guild_disband_result' and event['result'] == 0)):
        state.guild = {}
