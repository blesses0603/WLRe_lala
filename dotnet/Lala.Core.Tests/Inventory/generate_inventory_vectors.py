"""Deterministic receive-only Python oracle; synthetic packets, no accounts or resources.
Run from repository root: python dotnet/Lala.Core.Tests/Inventory/generate_inventory_vectors.py
The actual Python dispatcher is also checked for all recognized results and protocol errors.
Runtime selection uses injected synthetic rows; no official runtime is activated or inferred.
"""
import json
import random
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.network.wire import Packet, ProtocolError
from wlre.network.protocol import decode as decode_server
from wlre.services.items.room_storage import decode_storage
from wlre.services.items.recovery import decode_recovery
from wlre.services.items.crafting import decode_crafting

rng = random.Random(622320864)
CONTEXTS = {
    'legacy': None,
    'empty': [],
    'all_legacy': [{'item_id': 1}, {'item_id': 65535}],
    'recipes': [{'recipe_id': 1, 'item_id': 500}, {'recipe_id': 65535, 'item_id': 500},
                {'recipe_id': 42, 'item_id': 65535}],
    'mixed': [{'recipe_id': 1, 'item_id': 500}, {'item_id': 100}],
    'duplicate': [{'recipe_id': 1, 'item_id': 500}, {'recipe_id': 1, 'item_id': 100}],
    'zero_recipe': [{'recipe_id': 0, 'item_id': 500}],
    'zero_item': [{'recipe_id': 1, 'item_id': 0}],
    'large_recipe': [{'recipe_id': 65536, 'item_id': 500}],
    'large_item': [{'recipe_id': 1, 'item_id': 65536}],
}
valid, invalid, ignored, boundaries = [], [], [], []


def pack(fmt, *values):
    return struct.pack('<' + fmt, *values)


def item():
    return (pack('HBBBIIIHddBBHHBHI', 65535, 255, 254, 253, 0xffffffff,
                 0x80000000, 0, 65535, -123.5, 1e-100, 255, 254, 65535, 65534,
                 253, 65533, 0xffffffff) +
            b''.join(pack('BH', i, 65535 - i) for i in range(4)) + pack('BBBB', 3, 255, 254, 253))


def schedule(index=1, identity=42, elapsed=0xffffffff, count=255, base=0xffffffff):
    return pack('BHIBI', index, identity, elapsed, count, base)


def furniture(index=65535):
    return (pack('HHHHHBH', index, 65535, 0, 32768, 65535, 255, 65534)
            + pack('11H', *range(11)) + pack('BB', 255, 254) + b'PRIVATE')


def outcome(family, main, sub, payload, context='legacy', dispatcher=False):
    rows = CONTEXTS[context]
    runtime = None if rows is None else SimpleNamespace(recipe_catalog=rows)
    with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime', return_value=runtime):
        try:
            fn = decode_server if dispatcher else {'storage': decode_storage, 'recovery': decode_recovery, 'crafting': decode_crafting}[family]
            return {'expected': fn(Packet(main, sub, payload))}
        except ProtocolError as exc:
            return {'error': str(exc), 'error_kind': 'protocol'}
        except ValueError as exc:
            return {'error': str(exc), 'error_kind': 'context'}


def add(name, family, main, sub, payload, context='legacy'):
    row = dict(name=name, family=family, main=main, sub=sub, hex=payload.hex(), context=context)
    result = outcome(family, main, sub, payload, context)
    row.update(result)
    if 'error' in result:
        # Nonselected services have no dispatcher precedence claim.
        if family == 'crafting' or main == 62 or (main, sub) == (23, 208):
            assert outcome(family, main, sub, payload, context, True) == result, name
        invalid.append(row)
    elif result['expected'] is None:
        ignored.append(row)
    else:
        assert outcome(family, main, sub, payload, context, True) == result, name
        row['prefixes'] = {str(n): outcome(family, main, sub, payload[:n], context) for n in range(len(payload))}
        row['tail'] = outcome(family, main, sub, payload + b'\x7e', context)
        valid.append(row)


for count in (0, 1, 3):
    add(f'garage_initial_{count}', 'storage', 62, 7, pack('B', count) + b''.join(pack('B', i) + item() for i in range(count)))
add('garage_add', 'storage', 62, 11, b'\xff' + item())
for sub, payload in ((13, b'\x00\xff'), (71, b'\xff'), (72, pack('BHH', 255, 65535, 65535)),
                     (73, b'\x00'), (74, pack('H', 65535)), (75, pack('H', 0)), (25, b'\x01\xff')):
    add(f'storage_{sub}', 'storage', 62, sub, payload)
for count in (0, 1, 4):
    add(f'materials_initial_{count}', 'storage', 62, 57,
        pack('BBH', 1, 1, count) + b''.join(pack('HHH', i, 65535 - i, 0 if i == 0 else 65535) for i in range(count)))
add('materials_add', 'storage', 62, 57, pack('BBHHH', 1, 2, 0, 0, 0))
add('materials_delete', 'storage', 62, 57, pack('BHH', 2, 65535, 65535))
add('garage_duplicate', 'storage', 62, 7, b'\x02\x00' + item() + b'\x00' + item())
add('garage_duplicate_truncated_second', 'storage', 62, 7, b'\x02\x00' + item() + b'\x00' + item()[:-1])
add('materials_duplicate', 'storage', 62, 57, pack('BBH6H', 1, 1, 2, 0, 1, 2, 0, 2, 3))
add('materials_duplicate_before_tail', 'storage', 62, 57, pack('BBH6H', 1, 1, 2, 0, 1, 2, 0, 2, 3) + b'x')
add('materials_count_before_duplicate', 'storage', 62, 57, pack('BBH6H', 1, 1, 3, 0, 1, 2, 0, 2, 3))
add('garage_duplicate_before_tail', 'storage', 62, 7, b'\x02\x00' + item() + b'\x00' + item() + b'x')
for payload in (b'', b'\x00', b'\x01', b'\x01\x00', b'\x01\xff', b'\x03', b'\x01\x02', b'\x01\x01\xff\xff', b'\x01\x01\x00\x00x'):
    add('materials_bad_' + payload.hex(), 'storage', 62, 57, payload)
for kind in (0, 2, 255):
    for suffix in (b'', b'\xff', b'PRIVATE'):
        add(f'storage_other_error_{kind}_{len(suffix)}', 'storage', 62, 25, bytes([kind]) + suffix)
for value in (float('nan'), float('inf'), float('-inf')):
    payload = bytearray(b'\x01' + item())
    payload[20:28] = pack('d', value)
    add(f'garage_nonfinite_{value}', 'storage', 62, 11, bytes(payload))

for kind in (3, 4):
    for bottle in (0, 1, 2, 3, 4, 5, 255):
        for value in (-2147483648, -1, 0, 2147483647):
            add(f'balance_{kind}_{bottle}_{value}', 'recovery', 23, 208, pack('BBi', kind, bottle, value))
for bottle in (0, 1, 2, 3, 4, 5, 255):
    for count in (0, 3):
        add(f'used_{bottle}_{count}', 'recovery', 23, 208, pack('BBB', 5, bottle, count) + bytes([255, 0, 255][:count]))
for kind in (1, 2):
    for bottle in (0, 255):
        for durable in (-2147483648, 0, 2147483647):
            payload = bytes([kind]) + (bytes([bottle]) if kind == 1 else b'') + pack('Bi', 0, durable) + (b'\xff' if kind == 1 else b'')
            add(f'item_update_{kind}_{bottle}_{durable}', 'recovery', 23, 208, payload)
for kind in (0, 6, 255):
    add(f'recovery_unknown_{kind}', 'recovery', 23, 208, bytes([kind]))

for context in ('legacy', 'recipes'):
    for elapsed in (0, 1, 999, 1000, 0x80000000, 0xffffffff):
        add(f'craft_elapsed_{context}_{elapsed}', 'crafting', 64, 16,
            schedule(255, 42, elapsed, 1, 0), context)
for context in CONTEXTS:
    add(f'context_before_payload_{context}', 'crafting', 64, 1, b'', context)
    add(f'context_not_read_for_non_schedule_{context}', 'crafting', 64, 2, b'\x00', context)
    add(f'context_not_read_for_unknown_{context}', 'crafting', 64, 255, b'PRIVATE', context)
    for sub, payload in ((1, b'\x00'), (1, schedule(identity=1) + schedule(255, 65535) + b'\x7f'), (16, schedule())):
        add(f'craft_{context}_{sub}_{len(payload)}', 'crafting', 64, sub, payload, context)
for context in ('legacy', 'recipes'):
    for values in ((0, 42, 1), (1, 0, 1), (1, 42, 0), (1, 2, 1)):
        index, identity, count = values
        add(f'craft_invalid_row_{context}_{values}', 'crafting', 64, 16, schedule(index, identity, count=count), context)
    add('craft_duplicate_' + context, 'crafting', 64, 1, schedule() * 2 + b'\x00', context)
    add('craft_duplicate_and_truncated_' + context, 'crafting', 64, 1, schedule() * 2, context)
    add('craft_invalid_row_before_unknown_' + context, 'crafting', 64, 16, schedule(0, 2), context)
    add('craft_truncated_before_unknown_' + context, 'crafting', 64, 16, schedule(1, 2)[:-1], context)
    for size in (0, 2, 11, 12, 14, 24):
        add(f'craft_bad_length_{context}_{size}', 'crafting', 64, 1, bytes(size), context)
for sub in (2, 3, 5):
    for index in (0, 255):
        add(f'craft_index_{sub}_{index}', 'crafting', 64, sub, bytes([index]))
for sub in (4, 6, 7, 8):
    add(f'craft_result_{sub}', 'crafting', 64, sub, pack('BH', 0, 65535))
add('craft_human', 'crafting', 64, 10, pack('BI', 255, 0xffffffff))
for success in (0, 1, 2, 255):
    add(f'craft_swap_{success}', 'crafting', 64, 25, bytes([success]) + (b'\x00\xff' if success == 1 else b''))
    add(f'craft_swap_tail_{success}', 'crafting', 64, 25, bytes([success, 1, 2]))
for count in (0, 1, 3):
    add(f'furniture_snapshot_{count}', 'crafting', 62, 4, pack('I', 0xffffffff) + furniture() * count)
for kind in (0, 1, 2, 255):
    add(f'furniture_add_{kind}', 'crafting', 62, 1, bytes([kind]) + furniture())
    add(f'furniture_tool_{kind}', 'crafting', 62, 5, pack('BHHH', kind, 0, 65535, 65535))
for sub in (2, 76):
    add(f'furniture_index_{sub}', 'crafting', 62, sub, b'\xff\xff')
for size in (0, 1, 3, 5, 47, 49):
    add(f'furniture_bad_length_{size}', 'crafting', 62, 4, bytes(size))

for family, main, sub in (('storage', 0, 7), ('storage', 62, 1), ('storage', 62, 255),
                           ('recovery', 0, 208), ('recovery', 23, 207),
                           ('crafting', 0, 1), ('crafting', 64, 255), ('crafting', 62, 3)):
    add(f'unknown_{family}_{main}_{sub}', family, main, sub, b'PRIVATE\xff')
for family, keys in (('storage', [(62, s) for s in (7, 11, 13, 25, 57, 71, 72, 73, 74, 75)]),
                     ('recovery', [(23, 208)]), ('crafting', [(64, s) for s in (1, 2, 3, 4, 5, 6, 7, 8, 10, 16, 25)] + [(62, s) for s in (1, 2, 4, 5, 76)])):
    for i in range(48):
        main, sub = rng.choice(keys)
        add(f'fuzz_{family}_{i}', family, main, sub, rng.randbytes(rng.randrange(0, 72)))

# Max counts are generated compactly instead of retaining a multi-megabyte expanded fixture.
for family, main, sub, pattern, count in (
    ('storage', 62, 7, 'garage', 255), ('storage', 62, 57, 'materials', 65535),
    ('recovery', 23, 208, 'targets', 255), ('crafting', 64, 1, 'schedule', 255),
    ('crafting', 62, 4, 'furniture', 1500)):
    if pattern == 'garage':
        payload = bytes([count]) + b''.join(bytes([i]) + item() for i in range(count))
    elif pattern == 'materials':
        payload = pack('BBH', 1, 1, count) + b''.join(pack('HHH', i, 65535, 65535) for i in range(count))
    elif pattern == 'targets':
        payload = pack('BBB', 5, 4, count) + bytes(range(count))
    elif pattern == 'schedule':
        payload = b''.join(schedule(i + 1) for i in range(count)) + b'\xff'
    else:
        payload = pack('I', 0xffffffff) + b''.join(furniture(i) for i in range(count))
    result = outcome(family, main, sub, payload)['expected']
    field = {'garage': 'items', 'materials': 'items', 'targets': 'targets', 'schedule': 'rows', 'furniture': 'furniture'}[pattern]
    boundaries.append(dict(name='maximum_' + pattern, family=family, main=main, sub=sub, pattern=pattern,
                           count=count, field=field, type=result['type'], first=result[field][0], last=result[field][-1],
                           truncated=outcome(family, main, sub, payload[:-1]), tail=outcome(family, main, sub, payload+b'\x7e')))

data = dict(contexts=CONTEXTS, item_hex=item().hex(), schedule_hex=schedule().hex(), furniture_hex=furniture().hex(),
            valid=valid, invalid=invalid, ignored=ignored, boundaries=boundaries)
encoded = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
target = Path(__file__).with_name('PythonInventoryVectors.cs')
target.write_text('// Generated synthetic data from retained Python receive decoders.\nnamespace Lala.Core.Tests.Inventory;\ninternal static class PythonInventoryVectors\n{\n    internal const string Json = """\n' + encoded + '\n""";\n}\n', encoding='utf-8')
print(f'{len(valid)} valid; {len(invalid)} invalid; {len(ignored)} ignored; {len(boundaries)} count boundaries; {len(encoded)} JSON chars')
