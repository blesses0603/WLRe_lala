"""Deterministic offline differential vectors from the retained Python live_data.py.
Run from repository root: python dotnet/Lala.Core.Tests/Protocol/generate_live_data_vectors.py
Synthetic data only: no captures, accounts, network, or Python dependency during .NET tests.
"""
import json
import random
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.network.live_data import item_save, companion, player_info, decode_live
from wlre.network.protocol import decode as decode_packet
from wlre.network.wire import Packet, ProtocolError, Reader

rng = random.Random(126223140)
NAMES = ['', '星河😀\0', 'A\0B\0\0', 'ΩЖ한글', '界' * 127]


def pack(fmt, *values):
    return struct.pack('<' + fmt, *values)


def number(bits):
    return rng.choice([0, 1, (1 << bits) - 1, rng.randrange(1 << bits)])


def signed(bits):
    return rng.choice([-(1 << (bits - 1)), -1, 0, (1 << (bits - 1)) - 1])


def text(value):
    raw = value.encode('utf-16le')
    return pack('B', len(raw)) + raw


def item(equip=False, locked=None):
    data = pack('H', number(16))
    if not equip:
        data += pack('B', number(8))
    data += pack('BBI', number(8), number(8), number(32))
    if not equip:
        data += pack('II', number(32), number(32))
    data += pack('HddBBH', number(16), rng.choice([-0.0, -123.5, 1e100, 1e-100]),
                 rng.choice([0.0, -1e100, 45123.625, 1e-100]), number(8), number(8), number(16))
    if not equip:
        data += pack('H', number(16))
    data += pack('BHI', number(8), number(16), number(32))
    data += b''.join(pack('BH', number(8), number(16)) for _ in range(4))
    data += pack('BBB', number(8) if locked is None else locked, number(8), number(8))
    if not equip:
        data += pack('B', number(8))
    return data


def pet(simple=False, name='星河😀\0', exp=None):
    if simple:
        data = pack('BHHHHHBI', number(8), 101, 202, 303, 404, 505,
                    number(8), number(32) if exp is None else exp)
    else:
        data = pack('iBiHHHHHHBBBH', signed(32) if exp is None else exp, number(8), signed(32),
                    number(16), 303, 101, 202, 505, 404, number(8), number(8), number(8), number(16)) + text(name)
    data += b''.join(pack('BI', number(8), number(32)) for _ in range(5))
    if simple:
        data += pack('B', number(8))
    data += b''.join(item(True) for _ in range(9))
    if not simple:
        data += pack('B', number(8))
    data += pack('BBBH', number(8), number(8), number(8), number(16))
    if not simple:
        data += pack('B', number(8))
    return data + pack('H', number(16))


def player(count):
    return (pack('BIHHHHHHBIHHIH', number(8), number(32), number(16), 101, 202, 303, 404, 505,
                 number(8), number(32), number(16), number(16), number(32), number(16)) +
            pack('IIIIII', *(number(32) for _ in range(6))) + bytes(range(12)) + pack('H', count) +
            b''.join(pack('HBI', number(16), number(8), number(32)) for _ in range(count)) +
            pack('HHBBB', number(16), number(16), number(8), number(8), number(8)))


def read(kind, payload, main=0, sub=0, index=None, npc_id=0):
    reader = Reader(payload)
    if kind in ('item', 'equip'):
        result = item_save(reader, index, kind == 'equip')
    elif kind in ('companion', 'simple_companion'):
        result = companion(reader, index, npc_id, kind == 'simple_companion')
    elif kind == 'player':
        result = player_info(reader)
    elif kind == 'packet':
        packet = Packet(main, sub, payload)
        result = {'main': main, 'sub': sub}
        if not decode_live(packet, reader, result):
            return None
    else:
        raise AssertionError(kind)
    reader.end()
    return result


valid = []
invalid = []


def add(name, kind, payload, main=0, sub=0, index=None, npc_id=0):
    args = (main, sub, index, npc_id)
    expected = read(kind, payload, *args)
    if kind == 'packet' and expected is not None:
        assert decode_packet(Packet(main, sub, payload)) == expected
    prefixes = []
    prefix_results = {}
    for length in range(len(payload)):
        try:
            prefix_results[str(length)] = read(kind, payload[:length], *args)
            prefixes.append(length)
        except ProtocolError:
            pass
    try:
        tail = read(kind, payload + b'\x7e', *args)
        accepts_tail = True
        assert tail == expected
    except ProtocolError:
        accepts_tail = False
    valid.append(dict(name=name, kind=kind, main=main, sub=sub, index=index, npc_id=npc_id,
                      hex=payload.hex().upper(), expected=expected,
                      accepted_prefixes=prefixes, prefix_results=prefix_results, accepts_tail=accepts_tail))


def bad(name, kind, payload, main=0, sub=0, index=None, npc_id=0):
    try:
        read(kind, payload, main, sub, index, npc_id)
    except ProtocolError:
        invalid.append(dict(name=name, kind=kind, main=main, sub=sub, index=index, npc_id=npc_id,
                            hex=payload.hex().upper()))
    else:
        raise AssertionError('Python accepted malformed case ' + name)


for equip in (False, True):
    for locked in (0, 1, 2, 3, 128, 254, 255):
        add(f'item_{equip}_locked_{locked}', 'equip' if equip else 'item', item(equip, locked),
            index=None if equip else 255)
for i in range(10):
    add(f'companion_{i}', 'companion', pet(name=NAMES[i % len(NAMES)], exp=signed(32)), index=i, npc_id=65535)
    add(f'simple_companion_{i}', 'simple_companion', pet(True, exp=[0, 1, 2**31, 2**32 - 1][i % 4]), npc_id=2**32 - 1)
for count in (0, 1, 5, 255, 256):
    add(f'player_{count}', 'player', player(count))
for exp in (-2**63, -1, 0, 2**63 - 1):
    add(f'star_{exp}', 'packet', pack('BBq', 255, 128, exp) + bytes(range(30)), 5, 47)
add('bag_empty', 'packet', b'\xff', 23, 5)
add('bag_multiple_duplicate_index', 'packet', b'\x00' + b'\xff' + item() + b'\xff' + item(), 23, 5)
add('bag_add', 'packet', b'\xff' + item() + pack('H', 65535), 23, 6)
for count in (0, 1, 9, 10):
    add(f'player_equips_{count}', 'packet', b''.join(item(True) for _ in range(count)), 23, 11)
add('companions_empty', 'packet', b'', 15, 8)
add('companions_duplicate_index', 'packet', (pack('BH', 255, 65535) + pet()) * 2, 15, 8)
add('companion_add', 'packet', pack('II', 2**32 - 1, 2**32 - 1) + pet(True, exp=2**32 - 1) + b'\xff', 15, 1)
add('player_combat', 'packet', player(7), 5, 3)
for value in (0, 1, 255):
    add(f'bag_delete_{value}', 'packet', bytes([value]) * 3, 23, 9)
    add(f'purchase_{value}', 'packet', bytes([value]), 27, 1)
    add(f'sale_notice_{value}', 'packet', bytes([value]), 27, 8)
    add(f'bag_sell_{value}', 'packet', pack('IBB', 2**32 - 1, value, value), 27, 6)
    add(f'player_damage_{value}', 'packet', bytes([value]) * 2, 23, 27)
    add(f'companion_damage_{value}', 'packet', bytes([value]) * 3, 23, 28)
    add(f'equip_broken_{value}', 'packet', pack('BH', value, 65535), 23, 35)
    add(f'companion_delete_{value}', 'packet', pack('IBB', 2**32 - 1, value, value), 15, 2)
    add(f'battle_equip_{value}', 'packet', pack('IBBHI', 2**32 - 1, value, value, 65535, 2**32 - 1), 11, 252)
for result in (0, 1, 2, 3, 255):
    add(f'item_use_{result}', 'packet', bytes([result]) + (pack('BH', 255, 65535) if result == 2 else b''), 23, 15)
for grid in (0, 1, 2, 3, 4, 255):
    for damage in (0, 2**32 - 1):
        add(f'damage_{grid}_{damage}', 'packet', pack('BBBIB', 1, grid, 255, damage, 254), 23, 140)
    add(f'broken_{grid}', 'packet', pack('BBBBH', 2, grid, 255, 254, 65535), 23, 140)
for value in (0, 255):
    add(f'damage_kind_4_{value}', 'packet', pack('BBBB', 4, value, value, 254), 23, 140)
for kind in (3, 5):
    add(f'time_kind_{kind}', 'packet', bytes([kind]) + bytes([255]) * (8 if kind == 3 else 16), 23, 140)
for sub in (1, 4):
    for npc in (0, 2**32 - 1):
        add(f'active_{sub}_{npc}', 'packet', pack('I', npc), 19, sub)
add('active_none', 'packet', b'', 19, 2)
for main, sub in ((255, 255), (23, 0), (23, 12), (15, 3), (19, 3), (5, 48), (27, 2), (11, 251)):
    add(f'unknown_{main}_{sub}', 'packet', b'opaque-unknown', main, sub)

# Nonfinite IEEE-754 times are invalid in both item variants and nested packets.
for equip in (False, True):
    offset = 10 if equip else 19
    for field in (0, 1):
        for label, bits in (('inf', 0x7ff0000000000000), ('negative_inf', 0xfff0000000000000),
                            ('nan', 0x7ff8000000000042)):
            data = bytearray(item(equip))
            struct.pack_into('<Q', data, offset + field * 8, bits)
            bad(f'time_{equip}_{field}_{label}', 'equip' if equip else 'item', bytes(data))
            payload = bytes(data) if equip else b'\x09\x01' + data
            bad(f'packet_time_{equip}_{field}_{label}', 'packet', payload, 23, 11 if equip else 5)
for kind in (0, 6, 255):
    bad(f'damage_unknown_kind_{kind}', 'packet', bytes([kind]) + bytes(32), 23, 140)
for label, replacement in (('odd', b'\x01\x00'), ('high_surrogate', b'\x02\x00\xd8'),
                            ('low_surrogate', b'\x02\x00\xdc'), ('odd_max', b'\xff' + bytes(255))):
    data = pet().replace(text('星河😀\0'), replacement, 1)
    bad(f'companion_name_{label}', 'companion', data)
    bad(f'packet_companion_name_{label}', 'packet', pack('BH', 1, 1) + data, 15, 8)
# Player learned-skill count is UInt16, never a byte or a count inferred from the tail.
data = bytearray(player(0))
struct.pack_into('<H', data, 68, 65535)
bad('player_missing_declared_skills', 'player', bytes(data))
bad('purchase_result_is_one_byte', 'packet', b'\x00\x00\x00\x00', 27, 1)
bad('item_use_unexpected_variant_fields', 'packet', b'\x01\xff\xff\xff', 23, 15)


def section(values):
    return ',\n'.join(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) for value in values)

payload = '{\n"valid":[\n' + section(valid) + '\n],\n"invalid":[\n' + section(invalid) + '\n]\n}'
Path(__file__).with_name('PythonLiveDataVectors.cs').write_text(
    '// Generated by generate_live_data_vectors.py; deterministic synthetic Python parity only.\n'
    'namespace Lala.Core.Tests.Protocol;\ninternal static class PythonLiveDataVectors\n{\n'
    '    internal const string Json = """\n' + payload + '\n""";\n}\n', encoding='utf-8')
print(f'Generated {len(valid)} valid and {len(invalid)} malformed cases, '
      f'{sum(len(bytes.fromhex(c["hex"])) for c in valid)} prefix boundaries.')
