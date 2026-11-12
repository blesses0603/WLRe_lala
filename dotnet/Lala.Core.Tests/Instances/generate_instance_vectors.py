"""Deterministic synthetic parity for instances.py; no live packets or accounts.

Run from any working directory. Expected events/errors come from the unchanged
Python decoder, not a second interpretation of its fields.
"""
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.network.instances import decode_instances
from wlre.network.wire import Packet, ProtocolError

rng = random.Random(85186)
cases = []


def raw(size):
    return rng.randbytes(size)


def u16(value):
    return struct.pack('<H', value)


def u32(value):
    return struct.pack('<I', value)


def name():
    text = rng.choice(['', '房主', '協力😀', 'A\0B\0\0', '團', 'x' * 127])
    value = text.encode('utf-16le')
    return bytes([len(value)]) + value


def add(label, main, sub, payload=b''):
    case = dict(label=label, main=main, sub=sub, hex=payload.hex())
    try:
        case['expected'] = decode_instances(Packet(main, sub, payload))
    except ProtocolError:
        case['error'] = True
    cases.append(case)


def main_room():
    return raw(2) + name() + raw(1) + name() + bytes([rng.choice([0, 1, 2, 255])]) + raw(2)


def coop_member(role_id):
    return u32(role_id) + raw(17)


for iteration in range(4):
    prefix = f'sample-{iteration}'
    count = iteration
    add(prefix + '-main-rooms', 85, 1, bytes([count]) + b''.join(main_room() for _ in range(count)))
    for sub in (2, 3):
        add(prefix + f'-result-{sub}', 85, sub, raw(1))
    add(prefix + '-main-members', 85, 4, raw(2) + bytes([count]) + raw(4 * count))
    for kind in range(1, 6):
        add(prefix + f'-phase-{kind}', 85, 5, bytes([kind]) + raw({1: 8, 5: 4}.get(kind, 0)))
    add(prefix + '-joined', 85, 7, raw(7))
    add(prefix + '-time', 85, 9, b'\x01' + raw(4))
    for kind in range(1, 7):
        if kind == 1:
            payload = raw(2) + name()
        elif kind == 2:
            payload = bytes([iteration]) + name()
        elif kind in (3, 4):
            payload = raw({3: 4, 4: 2}[kind])
        else:
            payload = bytes([count]) + raw(4 * count)
        add(prefix + f'-objective-{kind}', 85, 10, bytes([kind]) + payload)
    add(prefix + '-left', 85, 12, raw(9) + u32([0, 1, 2, 0xffffffff][iteration]))
    add(prefix + '-completed', 85, 15)
    add(prefix + '-min-players', 85, 17)
    for kind in (0, 1, 2, 3, 4, 5, 6, 98, 99, 100, 101, 102):
        if kind == 4:
            payload = raw(2) + name()
        elif kind == 98:
            payload = raw(2) + name() + raw(2)
        elif kind == 100:
            payload = bytes([count]) + raw(count * 6)
        else:
            payload = raw({0: 13, 1: 5, 2: 4, 3: 5, 5: 2}.get(kind, 0))
        add(prefix + f'-new-info-{kind}', 85, 21, bytes([kind]) + payload)
    for code in (0, 1, 16, 19, 255):
        add(prefix + f'-coop-result-{code}', 186, 2, bytes([code]) + (raw(4) if code in (16, 19) else b''))
    for code in (17, 18):
        count = iteration + 1
        if code == 17:
            payload = b''.join(raw(16) + name() for _ in range(count))
        else:
            payload = raw(count * 8)
        add(prefix + f'-coop-match-{code}', 186, 2, bytes([code, count]) + payload)
    capacity = iteration
    roles = [[0], [0xffffffff], [0, 123], [123, 0, 123]][iteration][:capacity]
    header = bytes([iteration, 3 - iteration]) + raw(2) + bytes([iteration]) + raw(2) + bytes([capacity])
    add(prefix + '-coop-members', 186, 3, header + b''.join(coop_member(role_id) for role_id in roles))
    for sub, size in ((6, 2), (11, 5), (13, 0), (15, 1)):
        add(prefix + f'-coop-{sub}', 186, sub, raw(size))
    add(prefix + '-coop-awards', 186, 10, raw(9 * iteration))
    add(prefix + '-coop-rooms', 186, 17, u16(iteration) + raw(iteration * 11))
    add(prefix + '-coop-standby', 186, 20, bytes([iteration]))

# All count limits, zero-count cases, UInt32 extremes and exact boolean semantics.
for count in (0, 200):
    add(f'main-room-bound-{count}', 85, 1, bytes([count]) + b'\xff\xff\x00\xff\x00\x02\xff\xff' * count)
for count in (0, 16):
    add(f'main-member-bound-{count}', 85, 4, b'\xff\xff' + bytes([count]) + b'\xff' * (4 * count))
    for kind in (5, 6):
        add(f'objective-bound-{kind}-{count}', 85, 10, bytes([kind, count]) + b'\xff' * (4 * count))
    add(f'record-bound-{count}', 85, 21, bytes([100, count]) + b'\xff' * (6 * count))
for count in (0, 1000):
    add(f'coop-room-bound-{count}', 186, 17, u16(count) + b'\xff' * (11 * count))
for count in (0, 8):
    add(f'coop-members-bound-{count}', 186, 3, b'\xff' * 7 + bytes([count]) + b'\xff' * (21 * count))
for code in (17, 18):
    payload = (b'\xff' * 16 + b'\x00') * 8 if code == 17 else b'\xff' * 64
    add(f'coop-match-bound-{code}', 186, 2, bytes([code, 8]) + payload)
for count in (0, 4):
    add(f'award-bound-{count}', 186, 10, b'\xff' * (9 * count))
for main, sub, payload in ((85, 1, b'\xc9'), (85, 4, b'\x00\x00\x11'),
                           (85, 10, b'\x05\x11'), (85, 10, b'\x06\xff'),
                           (85, 21, b'\x64\x11'), (186, 17, u16(1001)),
                           (186, 17, u16(65535)), (186, 3, b'\x00' * 7 + b'\x09')):
    add(f'oversized-{main}-{sub}-{payload.hex()}', main, sub, payload)
for code in (17, 18):
    for count in (0, 9, 255):
        add(f'invalid-match-count-{code}-{count}', 186, 2, bytes([code, count]))
for size in (1, 8, 10, 35, 37, 45):
    add(f'invalid-award-size-{size}', 186, 10, raw(size))

# Every string position including the NPC name discarded by the cooperative decoder.
string_contexts = [(85, 1, b'\x01\x00\x00', b'\x00\x00\x00\x00\x00'),
                   (85, 1, b'\x01\x00\x00\x00\x00', b'\x00\x00\x00'),
                   (85, 10, b'\x01\x00\x00', b''), (85, 10, b'\x02\x01', b''),
                   (85, 21, b'\x04\x00\x00', b''), (85, 21, b'\x62\x00\x00', b'\x00\x00'),
                   (186, 2, b'\x11\x01' + b'\x00' * 16, b'')]
for index, (main, sub, prefix, suffix) in enumerate(string_contexts):
    for malformed in (b'\x01\x00', b'\x02\x00\xd8', b'\x02\x00\xdc', b'\xfe\x00'):
        add(f'malformed-string-{index}-{malformed.hex()}', main, sub, prefix + malformed + suffix)
for main, sub in ((0, 1), (255, 255), (85, 0), (85, 255), (186, 0), (186, 255)):
    add(f'unknown-{main}-{sub}', main, sub, b'\xff\xfe\xfd')
for sub in (5, 9, 10, 21):
    add(f'unknown-inner-{sub}', 85, sub, b'\xff\xfe\xfd')
    add(f'missing-inner-{sub}', 85, sub)

# Validate the fixtures intended as errors rather than silently accepting a bad generator.
for case in cases:
    if case['label'].startswith(('oversized-', 'invalid-', 'malformed-', 'missing-')):
        assert case.get('error'), case
source_hash = hashlib.sha256((ROOT / 'wlre/network/instances.py').read_bytes()).hexdigest()
output = '// Generated by generate_instance_vectors.py; synthetic data only.\n'
output += f'// instances.py SHA-256: {source_hash}\n'
output += 'namespace Lala.Core.Tests.Instances;\ninternal static class PythonInstanceVectors\n{\n'
output += '    internal const string Json = """\n' + json.dumps(cases, separators=(',', ':')) + '\n""";\n}\n'
Path(__file__).with_name('PythonInstanceVectors.cs').write_text(output, encoding='utf-8')
print(f'{len(cases)} instance vectors; source SHA-256 {source_hash}')
