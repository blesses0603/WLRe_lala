"""Deterministic synthetic receive-only parity for decode_tent and _camp.
Run from repository root. No state reduction, runtime resources or commands.
Every accepted vector retains every truncation outcome and appended-byte outcome.
Fixture partitions stay below 480 KiB.
"""
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from wlre.network.wire import Packet, ProtocolError
from wlre.network.protocol import decode as decode_server
from wlre.services.world.tent import decode_tent

DEST = Path(__file__).parent
cases = []
rng = random.Random(650703)


def outcome(main, sub, payload):
    try:
        return {'expected': decode_tent(Packet(main, sub, payload))}
    except ProtocolError as exc:
        return {'error': str(exc)}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def add(name, sub, payload, main=65):
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


def camp(owner=0xffffffff, tent=65535, x=0x80000000, y=0xffffffff, kind=255, make=255):
    return struct.pack('<IHIIBB', owner, tent, x, y, kind, make)


for name, payload in (('zero', bytes(16)), ('max', camp()), ('mixed', camp(1, 2, 3, 4, 5, 6))):
    add('added_' + name, 1, payload)
for count in (0, 1, 2, 16, 256):
    payload = b''.join(camp(i, i, i * 131, i * 157, i % 256, (255 - i) % 256) for i in range(count))
    add(f'list_{count}', 3, payload)
add('list_duplicate_owners_allowed', 3, camp() * 2)
for owner in (0, 1, 0x80000000, 0xffffffff):
    add(f'removed_{owner}', 4, struct.pack('<I', owner))
# Both boolean fields intentionally accept all byte values, with distinct meanings.
for value in range(256):
    add(f'access_byte_{value}', 7, bytes([value, (255 - value)]))
for access in (0, 1, 2, 127, 255):
    for show in (0, 1, 2, 127, 255):
        add(f'access_pair_{access}_{show}', 7, bytes([access, show]))
for code in (0, 1, 2, 127, 255):
    add(f'error_{code}', 16, bytes([code]))
for kind in (0, 1, 127, 255):
    for make in (0, 1, 127, 255):
        add(f'appearance_{kind}_{make}', 18, bytes([kind, make]))
for sub in (2, 5, 8):
    for length in (0, 1, 2, 16, 257):
        add(f'signal_{sub}_{length}', sub, bytes([255]) * length)
# Length guards precede reads; test short, exact and overlong data for each known layout.
for sub in (1, 3, 4, 7, 16, 18):
    for length in (0, 1, 2, 3, 4, 5, 15, 16, 17, 31, 32, 33):
        add(f'length_{sub}_{length}', sub, bytes(rng.randrange(256) for _ in range(length)))
known = {1, 2, 3, 4, 5, 7, 8, 16, 18}
for sub in range(256):
    if sub not in known:
        add(f'unknown_{sub}', sub, b'\xff')
for main in range(256):
    if main != 65:
        add(f'wrong_main_{main}', 1, b'\xff', main)

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
for stale in DEST.glob('PythonTentVectors.Part*.cs'):
    stale.unlink()
for index, part in enumerate(parts, 1):
    (DEST / f'PythonTentVectors.Part{index:02}.cs').write_text(
        'namespace Lala.Core.Tests.World.Tent;\ninternal static partial class PythonTentVectors\n{\n'
        f'    private const string Part{index:02} = """\n' + part + '\n""";\n}\n', encoding='utf-8')
(DEST / 'PythonTentVectors.cs').write_text(
    'namespace Lala.Core.Tests.World.Tent;\ninternal static partial class PythonTentVectors\n{\n'
    '    internal static readonly string[] JsonParts = [' + ', '.join(f'Part{i:02}' for i in range(1, len(parts) + 1)) + '];\n}\n', encoding='utf-8')
print(f'Tent: {len(cases)} cases, {sum(c.get("expected") is not None for c in cases)} accepted, '
      f'{sum("error" in c for c in cases)} malformed, {len(parts)} fixture partitions')
