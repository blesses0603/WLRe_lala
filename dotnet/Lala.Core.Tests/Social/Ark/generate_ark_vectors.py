"""Synthetic receive-only parity for decode_ark, _bool, _planet and _awards.
Run from the repository root. No captures, catalogs, accounts, planner or sends.
Every accepted vector retains every truncation outcome and an appended-byte outcome.
Uncompressed JSON partitions stay below 480 KiB; gzip byte literals are deterministic.
"""
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'TestSupport'))
from gzip_json_fixture import csharp_gzip_json
from wlre.network.wire import Packet, ProtocolError
from wlre.network.protocol import decode as decode_server
from wlre.services.star_ark import decode_ark

DEST = Path(__file__).parent
cases = []
rng = random.Random(1917524)


def pack(fmt, *values):
    return struct.pack('<' + fmt, *values)


def outcome(main, sub, payload):
    try:
        return {'expected': decode_ark(Packet(main, sub, payload))}
    except ProtocolError as exc:
        return {'error': str(exc)}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True).encode()).hexdigest()


def add(name, sub, payload, main=191):
    result = outcome(main, sub, payload)
    case = dict(name=name, main=main, sub=sub, hex=payload.hex(), **result)
    if 'error' in result:
        try:
            decode_server(Packet(main, sub, payload))
        except ProtocolError as exc:
            assert str(exc) == result['error'], name
        else:
            raise AssertionError('Dispatcher accepted malformed ' + name)
    if result.get('expected') is not None:
        assert decode_server(Packet(main, sub, payload)) == result['expected'], name
        case['prefixes'] = []
        for length in range(len(payload)):
            prefix = outcome(main, sub, payload[:length])
            case['prefixes'].append(prefix if 'error' in prefix else {'sha256': digest(prefix['expected'])})
        case['tail'] = outcome(main, sub, payload + b'\x7e')
    cases.append(case)


def snapshot(agents=(), total=0, awarded=0, remaining=0, boats=None, planet=1, explore=0):
    boats = {} if boats is None else boats
    return (pack('BHB', planet, explore, len(agents)) + b''.join(pack('BBBBB', *a) for a in agents)
            + pack('HhH', total, awarded, remaining)
            + b''.join(pack('BBB', *boats.get(p, (0, 0, 0))) for p in range(1, 21)))


def events(rows=None, new=0, main=False):
    rows = {} if rows is None else rows
    if main:
        return b''.join(pack('HB', *rows.get(i, (0, 0))) for i in range(1, 21))
    return b''.join(pack('HBB', *rows.get(i, (0, 0, 0))) for i in range(1, 13)) + pack('B', new)


def question(q=1, choices=(1, 2, 3, 4)):
    return pack('IBIIIIII', q, 255, 0xffffffff, 0x80000000, *choices)


for add_flag in (0, 1, 2, 127, 255):
    for show in (0, 1, 2, 255):
        add(f'starcoin_{add_flag}_{show}', 24, pack('IIBB', 0xffffffff, 0x80000000, add_flag, show), 75)
for value in (0, 1, 255):
    add(f'error_{value}', 0, pack('B', value))
add('snapshot_empty', 1, snapshot())
add('snapshot_idle_agent', 1, snapshot(((255, 255, 255, 255, 0),)))
add('snapshot_all_255_agents', 1, snapshot(tuple((i, i, 1, 255, 0) for i in range(1, 256))))
add('snapshot_active_first', 1, snapshot(((1, 1, 1, 1, 1),), 1, 1, 1, {1: (1, 0, 1)}))
add('snapshot_active_second', 1, snapshot(((255, 255, 255, 255, 20),), 65535, 219, 65535, {20: (0, 255, 1)}, 21, 10000))
add('snapshot_two_agents', 1, snapshot(((1, 1, 1, 255, 8), (255, 2, 255, 1, 8)), 300, 1, 0, {8: (1, 255, 1)}))
for planet in (0, 1, 20, 21, 22, 255):
    for explore in (0, 10000, 10001, 65535):
        add(f'snapshot_progress_{planet}_{explore}', 1, snapshot(planet=planet, explore=explore))
        add(f'explore_{planet}_{explore}', 17, pack('BH', planet, explore))
for name, agents in (
        ('zero_index', ((0, 1, 1, 1, 0),)), ('zero_id', ((1, 0, 1, 1, 0),)),
        ('zero_skill_first', ((1, 1, 0, 1, 0),)), ('zero_skill_second', ((1, 1, 1, 0, 0),)),
        ('bad_planet', ((1, 1, 1, 1, 21),)), ('max_planet', ((1, 1, 1, 1, 255),)),
        ('duplicate_index', ((1, 1, 1, 1, 0), (1, 2, 1, 1, 0))),
        ('duplicate_id_allowed', ((1, 1, 1, 1, 0), (2, 1, 1, 1, 0))),
        ('unassigned_planet', ((1, 1, 1, 1, 1),))):
    add('snapshot_' + name, 1, snapshot(agents))
for total, awarded, remaining in ((0, -32768, 0), (0, -1, 0), (0, 1, 0), (0, 0, 1),
                                   (300, 2, 0), (301, 2, 302), (65535, 220, 0), (1, 32767, 0)):
    add(f'snapshot_ship_{total}_{awarded}_{remaining}', 1,
        snapshot(((1, 1, 1, 1, 1),), total, awarded, remaining, {1: (1, 0, 1)}))
for total in (0, 1, 299, 300, 301, 65535):
    for awarded in sorted({0, (total + 299) // 300}):
        add(f'snapshot_duration_{total}_{awarded}', 1,
            snapshot(((1, 1, 1, 1, 1),), total, awarded, total, {1: (1, 0, 1)}))
for name, agents, total, boats in (
        ('invalid_boat', (), 0, {1: (0, 0, 2)}),
        ('max_boat', (), 0, {20: (0, 0, 255)}),
        ('agent_no_boat', ((1, 1, 1, 1, 1),), 1, {1: (1, 0, 0)}),
        ('unknown_agent', (), 1, {1: (1, 0, 1)}),
        ('wrong_planet', ((1, 1, 1, 1, 2),), 1, {1: (1, 0, 1)}),
        ('duplicate_assignment', ((1, 1, 1, 1, 1),), 1, {1: (1, 1, 1)}),
        ('two_boats', ((1, 1, 1, 1, 1),), 1, {1: (1, 0, 1), 20: (0, 0, 1)}),
        ('boat_without_agent', (), 1, {1: (0, 0, 1)}),
        ('time_without_boat', (), 1, {}),
        ('boat_without_time', (), 0, {1: (0, 0, 1)}),
        ('missing_second_assignment', ((1, 1, 1, 1, 1), (2, 2, 1, 1, 1)), 1, {1: (1, 0, 1)})):
    add('snapshot_' + name, 1, snapshot(agents, total, 0, total, boats))
add('events_empty', 2, events())
add('events_all_kinds', 2, events({i: (i, (i - 1) % 4 + 1, (i - 1) % 20 + 1) for i in range(1, 13)}, 1))
for id_ in (0, 1, 9999, 10000, 65535):
    for kind in (0, 1, 4, 5, 255):
        add(f'event_id_kind_{id_}_{kind}', 2, events({12: (id_, kind, 20 if id_ else 0)}))
        add(f'main_event_id_kind_{id_}_{kind}', 16, events({20: (id_, kind)}, main=True))
for planet in (0, 1, 20, 21, 255):
    add(f'event_planet_{planet}', 2, events({1: (1, 1, planet)}))
    add(f'empty_event_planet_{planet}', 2, events({1: (0, 0, planet)}))
for flag in (0, 1, 2, 127, 255):
    add(f'events_new_{flag}', 2, events(new=flag))
for planet in (0, 1, 20, 21, 255):
    for ship in (0, 1, 2, 255):
        add(f'dispatch_planet_ship_{planet}_{ship}', 3, pack('BBBBH', planet, ship, 1, 0, 65535))
        add(f'collect_end_{planet}_{ship}', 5, pack('BB', planet, ship))
for first, second, total in ((0, 0, 1), (1, 1, 1), (255, 255, 65535), (0, 255, 65535), (255, 0, 1), (1, 255, 0), (1, 255, 1)):
    add(f'dispatch_agents_{first}_{second}_{total}', 3, pack('BBBBH', 1, 1, first, second, total))
for count in (0, 1, 32, 255):
    add(f'collect_reward_{count}', 4, pack('HB', 65535, count) + b''.join(pack('HH', i, 65535 - i) for i in range(count)))
for index in (0, 1, 255):
    for skill in (0, 1, 2, 3, 255):
        for level in (0, 1, 255):
            add(f'skill_{index}_{skill}_{level}', 6, pack('BBB', index, skill, level))
    for id_ in (0, 1, 255):
        add(f'agent_{index}_{id_}', 7, pack('BB', index, id_))
for index in (0, 1, 12, 13, 20, 21, 255):
    for id_ in (0, 1, 9999, 10000, 65535):
        add(f'complete_{index}_{id_}', 10, pack('BH', index, id_))
for q in (0, 1, 0xffffffff):
    for n, choices in enumerate(((1, 2, 3, 4), (0, 2, 3, 4), (1, 1, 2, 3), (0xffffffff, 1, 0x80000000, 2))):
        add(f'question_{q}_{n}', 11, question(q, choices))
for correct in (0, 1, 2, 127, 255):
    for answer in (0, 1, 4, 5, 255):
        add(f'answer_{correct}_{answer}', 12, pack('BB', correct, answer))
for won in (0, 1, 2, 255):
    add(f'fight_flag_{won}', 15, pack('B', won))
for count in (0, 1, 31, 32, 33, 255):
    for id_ in (0, 65535):
        add(f'fight_awards_{count}_{id_}', 15, pack('BHB', 1, id_, count)
            + b''.join(pack('BII', i, 0xffffffff - i, i) for i in range(count)))
add('main_events_empty', 16, events(main=True))
add('main_events_all_kinds', 16, events({p: (10000 + p, (p - 1) % 4 + 1) for p in range(1, 21)}, main=True))
for planet in (0, 1, 20, 21, 255):
    for id_ in (0, 9999, 10000, 65535):
        for kind in (0, 1, 4, 5, 255):
            add(f'main_added_{planet}_{id_}_{kind}', 18, pack('BHB', planet, id_, kind))
for ship in (0, 1, 2, 255):
    for count in (-32768, -1, 0, 1, 32767):
        add(f'collect_count_{ship}_{count}', 19, pack('Bh', ship, count))
# Explicit partial semantic failures verify validation order, not merely error type.
for name, sub, payload in (
        ('snapshot_bad_progress_prefix', 1, pack('BH', 0, 0)),
        ('snapshot_bad_agent_planet_precedes_zero_index', 1, pack('BHBBBBBB', 1, 0, 1, 0, 0, 0, 0, 21)),
        ('snapshot_duplicate_precedes_missing_ship', 1, pack('BHB', 1, 0, 2) + bytes([1, 1, 1, 1, 0]) * 2),
        ('snapshot_ship_validation_precedes_planets', 1, pack('BHBHhH', 1, 0, 0, 0, -1, 0)),
        ('event_bad_planet_precedes_bad_id', 2, pack('HBB', 10000, 255, 0)),
        ('dispatch_bad_planet_prefix', 3, b'\0'), ('end_bad_planet_prefix', 5, b'\0'),
        ('answer_bad_bool_prefix', 12, b'\xff'), ('main_added_bad_planet_prefix', 18, b'\0'),
        ('fight_awards_bound_before_rows', 15, pack('BHB', 1, 1, 33))):
    add(name, sub, payload)
# Deterministic one-byte mutations also exercise combinations not hand-selected above.
seeds = [c for c in cases if c.get('expected') is not None and c['hex']]
for i in range(100):
    seed = rng.choice(seeds)
    data = bytearray.fromhex(seed['hex'])
    offset = rng.randrange(len(data))
    data[offset] ^= 1 << rng.randrange(8)
    add(f'mutation_{i}_{seed["name"]}_{offset}', seed['sub'], bytes(data), seed['main'])
known = {0, 1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 15, 16, 17, 18, 19}
for sub in range(256):
    if sub not in known:
        add(f'unknown_191_{sub}', sub, b'\xff')
    if sub != 24:
        add(f'unknown_75_{sub}', sub, b'\xff', 75)
for main in range(256):
    if main not in (75, 191):
        add(f'wrong_main_{main}', 1, b'\xff', main)

# Pack complete cases, never truncate or split a JSON case. Keep review units bounded.
assert len({c["name"] for c in cases}) == len(cases), "Duplicate fixture names"
parts, current = [], []
size = 2
for case in cases:
    row = json.dumps(case, ensure_ascii=True, separators=(',', ':'))
    assert len(row.encode()) < 480 * 1024, case['name']
    if size + len(row) + 1 > 480 * 1024 and current:
        parts.append('[' + ','.join(current) + ']')
        current, size = [], 2
    current.append(row)
    size += len(row) + 1
if current:
    parts.append('[' + ','.join(current) + ']')
for stale in DEST.glob('PythonArkVectors.Part*.cs'):
    stale.unlink()
for index, part in enumerate(parts, 1):
    (DEST / f'PythonArkVectors.Part{index:02}.cs').write_text(
        '// Generated by generate_ark_vectors.py; deterministic gzip bytes preserve the exact JSON.\n'
        'namespace Lala.Core.Tests.Social.Ark;\ninternal static partial class PythonArkVectors\n{\n'
        # A property avoids static field initialization order across partial-class files.
        f'    private static string Part{index:02} => ' + csharp_gzip_json(part) + ';\n}\n', encoding='utf-8')
(DEST / 'PythonArkVectors.cs').write_text(
    'namespace Lala.Core.Tests.Social.Ark;\ninternal static partial class PythonArkVectors\n{\n'
    '    internal static readonly string[] JsonParts = [' + ', '.join(f'Part{i:02}' for i in range(1, len(parts) + 1)) + '];\n}\n', encoding='utf-8')
print(f'Ark: {len(cases)} cases, {sum(c.get("expected") is not None for c in cases)} accepted, '
      f'{sum("error" in c for c in cases)} malformed, {len(parts)} fixture partitions')
