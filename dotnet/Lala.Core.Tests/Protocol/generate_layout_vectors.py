"""Offline, deterministic synthetic parity vectors for layout/social ports.
Run from repository root: python dotnet/Lala.Core.Tests/Protocol/generate_layout_vectors.py
Only imports retained Python decoders; no captures, accounts, network or runtime dependency.
"""
import json
import random
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.network.layouts import role_list, world_player, battle_unit
from wlre.network.protocol import decode
from wlre.network.social_protocol import decode_social
from wlre.network.wire import Packet, ProtocolError, Reader

rng = random.Random(126213)
PRIVATE = 'PRIVATE-NAMECARD-SYNTHETIC😀'
NAMES = ['', '星河😀\0', 'A\0B\0\0', 'ΩЖ한글', '界' * 127]


def pack(fmt, *values):
    return struct.pack('<' + fmt, *values)


def text(value):
    data = value.encode('utf-16le')
    return pack('B', len(data)) + data


def number(bits):
    return rng.choice([0, 1, (1 << bits) - 1, rng.randrange(1 << bits)])


def equipment(count):
    return b''.join(pack('HI', number(16), number(32)) for _ in range(count))


def role(name='星河😀\0', index=1, extreme=0):
    # Explicit signed extrema catch UInt32 aggregation and Int64 narrowing errors.
    base = 0 if extreme < 0 else (2**32 - 1 if extreme > 0 else number(32))
    bonus = 0 if extreme < 0 else (2**32 - 1 if extreme > 0 else number(32))
    star = -2**31 if extreme < 0 else (2**31 - 1 if extreme > 0 else -1234)
    return (pack('B', index) + text(name) + pack('BBIIIIqIBBIIBBHdB',
        number(8), number(8), base, number(32), base, number(32),
        rng.choice([-2**63, -1, 0, 2**63 - 1]), number(32), number(8), number(8),
        number(32), number(32), number(8), number(8), number(16),
        rng.choice([-123.5, 0.0, 45123.625, 1e100]), rng.choice([0, 1, 255])) +
        pack('IIIIHiiII', bonus, bonus, bonus, bonus, number(16) if extreme >= 0 else 0,
             star, star, bonus, bonus))


def world(name='星河😀\0', count=2, signature=PRIVATE):
    return (pack('IBHHHBBBIIBBB', number(32), number(8), number(16), number(16), number(16),
        number(8), number(8), number(8), number(32), number(32), number(8), rng.choice([0, 1, 255]), count) +
        equipment(count) + text(name) + bytes(range(11, 19)) + text(signature) + pack('H', number(16)))


def battle(name='星河😀\0', col=1, row=1):
    return (pack('BBIHIBBIHIHBBBBHHBBII', number(8), number(8), number(32), number(16),
        number(32), col, row, number(32), number(16), number(32), number(16),
        number(8), number(8), number(8), number(8), number(16), number(16),
        number(8), number(8), number(32), number(32)) + text(name) + equipment(9))


def nearby(name='星河😀\0', count=2, signature=PRIVATE):
    return (pack('IBBBHHH', number(32), number(8), number(8), number(8), number(16), number(16), number(16)) +
        bytes(range(13)) + pack('B', count) + equipment(count) + pack('BB', number(8), number(8)) +
        text(name) + bytes(range(21, 29)) + text(signature) + pack('H', number(16)))


LAYOUT_READERS = {'roles': role_list, 'world': world_player, 'battle': battle_unit}


def read(kind, payload, main=0, sub=0):
    if kind in LAYOUT_READERS:
        reader = Reader(payload)
        result = LAYOUT_READERS[kind](reader)
        reader.end()
        return result
    packet = Packet(main, sub, payload)
    if kind == 'layout_packet':
        return decode(packet)
    reader = Reader(payload)
    result = {'main': main, 'sub': sub}
    if not decode_social(packet, reader, result):
        return None
    reader.end()
    return result


valid = []
invalid = []


def add(name, kind, payload, main=0, sub=0):
    expected = read(kind, payload, main, sub)
    accepted_prefixes = []
    for length in range(len(payload)):
        try:
            read(kind, payload[:length], main, sub)
            accepted_prefixes.append(length)
        except ProtocolError:
            pass
    try:
        trailing = read(kind, payload + b'\x7e', main, sub)
        accepts_tail = True
        assert trailing == expected
    except ProtocolError:
        accepts_tail = False
    valid.append(dict(name=name, kind=kind, main=main, sub=sub, hex=payload.hex().upper(),
        expected=expected, accepted_prefixes=accepted_prefixes, accepts_tail=accepts_tail))


def bad(name, kind, payload, main=0, sub=0):
    try:
        read(kind, payload, main, sub)
    except ProtocolError:
        invalid.append(dict(name=name, kind=kind, main=main, sub=sub, hex=payload.hex().upper()))
    else:
        raise AssertionError('Python accepted malformed case ' + name)


add('roles_empty', 'roles', b'')
add('roles_positive_extreme', 'roles', role(extreme=1))
add('roles_negative_extreme', 'roles', role(extreme=-1))
add('roles_two', 'roles', role(index=1) + role(index=2))
add('roles_repeated_index_preserved', 'roles', role(index=1) + role(index=1))
for i in range(16):
    name = NAMES[i % len(NAMES)]
    add(f'roles_{i}', 'roles', role(name, i % 2 + 1))
    add(f'world_{i}', 'world', world(name, [0, 1, 9, 255][i % 4]))
    add(f'battle_slot_{i}', 'battle', battle(name, i // 4 + 1, i % 4 + 1))

add('role_list_event_empty', 'layout_packet', b'', 63, 1)
add('role_list_event', 'layout_packet', role() + role(index=2, extreme=1), 63, 1)
add('world_event', 'layout_packet', world(), 3, 1)
add('battle_start_event', 'layout_packet', b'\xff\x7f\x02' + battle() + battle(col=4, row=4), 11, 250)
add('battle_units_event', 'layout_packet', b'\x02' + battle() + battle(col=4, row=4), 11, 5)
add('battle_start_empty', 'layout_packet', b'\x00\xff\x00', 11, 250)
add('battle_units_empty', 'layout_packet', b'\x00', 11, 5)

for sub in (1, 4, 9):
    for value in (0, 2**32 - 1):
        add(f'team_{sub}_{value}', 'social', pack('I', value), 13, sub)
for sub in (3, 10):
    for answer in (0, 1, 2, 255):
        add(f'team_answer_{sub}_{answer}', 'social', pack('BI', answer, 2**32 - 1), 13, sub)
add('team_join', 'social', pack('II', 2**32 - 1, 0), 13, 5)
add('team_empty', 'social', b'', 13, 6)
add('team_solo', 'social', pack('IB', 1, 0), 13, 6)
add('team_full', 'social', pack('IBIII', 1, 3, 2, 3, 2**32 - 1), 13, 6)
add('team_multiple', 'social', pack('IB', 7, 0) + pack('IBII', 9, 2, 11, 12), 13, 6)
add('team_repeated_leader_across_records', 'social', pack('IB', 7, 0) * 2, 13, 6)
add('leader_offer', 'social', pack('BI', 1, 2**32 - 1), 13, 15)
for answer in (0, 1, 2, 255):
    add(f'leader_answer_{answer}', 'social', pack('BB', 2, answer) + (pack('I', 2**32 - 1) if answer == 2 else b''), 13, 15)
add('new_leader', 'social', pack('BII', 3, 4, 5), 13, 15)
for value in (0, 1, 2, 255):
    add(f'team_notice_{value}', 'social', pack('B', value), 13, 16)
    add(f'team_flag_{value}', 'social', pack('BBBB', 9, 8, value, 7), 33, 2)
    add(f'team_flag_extension_{value}', 'social', pack('BBBB', 9, 8, value, 7) + b'opaque-tail', 33, 2)
    add(f'social_rejected_{value}', 'social', pack('B', value), 33, 1)
    payload = pack('B', value) + (b'\xff' if value == 1 else b'')
    add(f'alchemy_space_{value}', 'social', payload, 23, 120)
    add(f'alchemy_space_extension_{value}', 'social', payload + b'opaque-tail', 23, 120)
for i, name in enumerate(NAMES):
    add(f'nearby_{i}', 'social', nearby(name, [0, 1, 2, 9, 255][i]), 4, 1)
add('nearby_leave', 'social', pack('I', 2**32 - 1), 1, 1)
add('alchemy_result', 'social', pack('HB', 2**16 - 1, 255), 23, 13)
for main, sub in ((255, 255), (13, 0), (13, 2), (13, 14), (33, 3), (23, 119)):
    add(f'unknown_{main}_{sub}', 'social', b'opaque-unknown', main, sub)
for kind in (0, 4, 255):
    add(f'unknown_leader_kind_{kind}', 'social', pack('B', kind) + b'opaque', 13, 15)

for index in (0, 3, 255):
    bad(f'role_index_{index}', 'roles', role(index=index))
for col, row in ((0, 1), (5, 1), (1, 0), (1, 5), (255, 255)):
    bad(f'battle_slot_{col}_{row}', 'battle', battle(col=col, row=row))
for count in (4, 255):
    bad(f'team_size_{count}', 'social', pack('IB', 1, count) + pack('I', 2) * count, 13, 6)
for values in ((0, 0), (1, 1, 0), (1, 1, 1), (1, 2, 2, 2)):
    leader, count, *members = values
    bad(f'team_members_{values}', 'social', pack('IB', leader, count) + b''.join(pack('I', x) for x in members), 13, 6)
bad('leader_answer_missing_role', 'social', b'\x02\x02', 13, 15)
bad('alchemy_missing_needed', 'social', b'\x01', 23, 120)
for kind, factory, main, sub in (('roles', role, 0, 0), ('world', world, 0, 0),
                                ('battle', battle, 0, 0), ('social', nearby, 4, 1)):
    for label, replacement in (('odd', b'\x01\x00'), ('high_surrogate', b'\x02\x00\xd8'),
                               ('low_surrogate', b'\x02\x00\xdc'), ('odd_max', b'\xff' + bytes(255))):
        payload = factory().replace(text('星河😀\0'), replacement, 1)
        bad(f'{kind}_name_{label}', kind, payload, main, sub)
for kind, factory, main, sub in (('world', world, 0, 0), ('social', nearby, 4, 1)):
    for label, replacement in (('odd', b'\x01\x00'), ('high_surrogate', b'\x02\x00\xd8'),
                               ('low_surrogate', b'\x02\x00\xdc')):
        payload = factory().replace(text(PRIVATE), replacement, 1)
        bad(f'{kind}_private_signature_{label}', kind, payload, main, sub)

def section(values):
    return ',\n'.join(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) for value in values)

payload = '{\n\"valid\":[\n' + section(valid) + '\n],\n\"invalid\":[\n' + section(invalid) + '\n]\n}'
Path(__file__).with_name('PythonLayoutVectors.cs').write_text(
    '// Generated by generate_layout_vectors.py; deterministic synthetic Python parity only.\n'
    'namespace Lala.Core.Tests.Protocol;\ninternal static class PythonLayoutVectors\n{\n'
    '    internal const string Json = """\n' + payload + '\n""";\n}\n', encoding='utf-8')
print(f'Generated {len(valid)} valid and {len(invalid)} malformed cases, '
      f'{sum(len(bytes.fromhex(c["hex"])) for c in valid)} prefix boundaries.')
