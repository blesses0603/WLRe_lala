"""Source-exact offline allocation and reservation validation/proposal oracle.

Calls retained inventory.allocate, reserve and reservations.acquire on deep-copied
synthetic dictionaries only. No State, session, transport, resource activation or
execution. Catalog names are an explicit pinned synthetic map, never authority.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import sys
from types import SimpleNamespace

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'TestSupport'))
from gzip_json_fixture import csharp_gzip_json
from wlre.network.live_data import item_save
from wlre.network.wire import Reader
from wlre.services.items import inventory, reservations
from wlre.services.items.live_combat_catalog import _pinned

NAMES = {'42': '測試材料', '43': '', '65535': '邊界物品'}
_pinned.set(dict(items={key: {'name': value} for key, value in NAMES.items()},
                 skills={}, keys={}, npcs={}, characters=[], element_weights={}))
RNG = random.Random(202611080201)
SCENARIOS = []


def item(index=1, item_id=42, count=10, serial=9, version=2):
    raw = struct.pack('<HBBBIIIHddBBHHBHI', item_id, 1, 254, version, serial,
        0x80000000, 0xffffffff, 65535, -123.5, 1e-100, 255, 254, 65535, 65534,
        253, 65533, 0xffffffff)
    raw += b''.join(struct.pack('<BH', i, 65535-i) for i in range(4)) + bytes([3, 255, 254, 253])
    value = item_save(Reader(raw), index)
    value['count'] = count
    return value


def bag(**updates):
    state = dict(ready=True, reliable=True, capacity=255, revision=2**100, use_failed=True,
        sync_error='imported retained diagnostic', last_use_result=4,
        items={'10': item(10, count=7), '2': item(2, count=8), '1': item(1),
               '3': item(3, 43, 6), '4': item(4, 1, 6), '255': item(255, 65535, 255)},
        reserved={}, holds={}, field_supply={'nested': ['retained', {'quantity': 2**100}]},
        server_stackable={'42': True, '43': False})
    state.update(updates)
    return state


def hold(index=1, count=2, remaining=2, before=10, exclusive=False, uncertain=False,
         item_id=42, serial=9, version=2):
    return dict(index=str(index), count=count, remaining=remaining, before=before,
                exclusive=exclusive, uncertain=uncertain, identity=[item_id, serial, version])


def project(state):
    value = copy.deepcopy(state)
    for key in ['capacity', 'sync_error', 'last_use_result', 'field_supply',
                'alchemy_slots', 'expedition_slots', 'maintenance_slots', 'server_stackable']:
        value.setdefault(key, None)
    return dict(inventory=value, item_order=list(state['items']), hold_order=list(state['holds']),
        available={str(index): reservations.available(state, index) for index in [0, 1, 2, 3, 4, 255, 65535]})


class Scenario:
    def __init__(self, name, initial=None):
        self.name, self.state = name, copy.deepcopy(initial if initial is not None else bag())
        self.steps = [dict(operation=None, expected=project(self.state))]

    def apply(self, operation):
        before = copy.deepcopy(self.state)
        rows = error = None
        try:
            if operation['kind'] == 'allocate':
                rows = inventory.allocate(self.state, operation['item_id'], operation['count'])
                assert self.state == before
            else:
                # Verify the retained facade and underlying validator agree exactly.
                facade = SimpleNamespace(inventory=copy.deepcopy(self.state))
                inventory.reserve(facade, operation['allocations'], operation['owner'], exclusive=operation['exclusive'])
                reservations.acquire(self.state, operation['owner'], operation['allocations'], exclusive=operation['exclusive'])
                assert self.state == facade.inventory
        except (ValueError, TypeError, KeyError) as exc:
            error = dict(type=type(exc).__name__, message=str(exc))
            assert self.state == before, (self.name, operation, 'source failed after mutation')
        self.steps.append(dict(operation=copy.deepcopy(operation), rows=copy.deepcopy(rows),
                               error=error, expected=project(self.state)))
        return self

    def allocate(self, item_id=42, count=1):
        return self.apply(dict(kind='allocate', item_id=item_id, count=count))

    def reserve(self, allocations, owner='battle', exclusive=False):
        return self.apply(dict(kind='reserve', owner=owner, exclusive=exclusive, allocations=allocations))

    def finish(self):
        SCENARIOS.append((self.name, self.steps))
        return self


def request(index=1, count=1, item_id=42): return dict(index=index, count=count, item_id=item_id)

s = Scenario('allocation_numeric_sorting_partial_shortage_and_integer_edges')
for item_id in [42, 43, 1, 65535, 0, -1, 65536, 2**128]:
    for count in [0, 1, 8, 10, 11, 18, 25, 26, -1, -2**128, 2**128]:
        s.allocate(item_id, count)
s.finish()
for updates in [dict(ready=False), dict(reliable=False), dict(ready=False, reliable=False), dict(items={})]:
    s = Scenario('allocation_readiness_and_empty_' + str(len(SCENARIOS)), bag(**updates))
    for count in [0, 1, -1, 2**128]: s.allocate(count=count)
    for owner in ['battle', 'unknown', 'Battle', '']:
        s.reserve([], owner).reserve([request(count=False)], owner)
    s.finish()

for field in ['alchemy_slots', 'expedition_slots', 'maintenance_slots', 'exclusive', 'uncertain']:
    initial = bag()
    if field.endswith('_slots'): initial[field] = ['1', '2', '10', '65535', '1']
    else: initial['holds'] = {'crafting': [hold(index=i, remaining=0, **{field: True}) for i in [1, 2, 10]]}
    s = Scenario('allocation_and_reservation_lock_' + field, initial)
    for count in [0, 1, -1, 2**100]: s.allocate(count=count)
    for owner in ['crafting', 'battle', 'alchemy']:
        for index in [1, 65535]: s.reserve([request(index)], owner)
    s.finish()

s = Scenario('duplicate_batch_atomicity_and_first_seen_slot_order')
s.reserve([request(2, 3), request(1, 4), request('2', 2), request(10, 2)])
s.reserve([request(1, 2), request(2, 99), request(10, 1)])
s.reserve([request(10, 1), request(2, 1)], exclusive=True).allocate(count=2)
s.reserve([request(1, 6), request(1, 1)]).finish()

for owner in ['battle', 'field_supply', 'alchemy', 'crafting', 'expedition', 'maintenance', 'storage']:
    s = Scenario('owner_projection_and_repeat_' + owner)
    s.reserve([], owner).reserve([request(2, 1), request(1, 1), request(2, 2)], owner)
    s.reserve([request(1, 1)], owner, exclusive=True).reserve([], owner, exclusive=True)
    s.reserve([request(1, 1)], 'storage' if owner != 'storage' else 'battle').finish()

for flag in ['exclusive', 'uncertain']:
    s = Scenario('same_owner_' + flag + '_with_zero_remaining', bag(
        holds={'battle': [hold(remaining=0, **{flag: True})]}, reserved={'1': 0}))
    s.reserve([request()], 'battle').allocate(count=1).finish()

for mismatch in [dict(item_id=43), dict(serial=10), dict(version=3), dict(serial=None), dict(version=None)]:
    s = Scenario('identity_precedence_' + str(len(SCENARIOS)), bag(
        holds={'battle': [hold(**mismatch)], 'storage': [hold()]}, reserved={'1': 4}))
    s.reserve([request()], 'battle').reserve([request(item_id=43)], 'battle')
    s.reserve([request(count=0)], 'battle').finish()

s = Scenario('duplicate_existing_rows_first_identity_and_count_only', bag(
    holds={'storage': [hold(index=3, item_id=43)],
           'battle': [hold(), hold(serial=999), hold(index=2, count=0, remaining=0)]}, reserved={'1': 4}))
s.reserve([request(count=2), request(2, 1)], exclusive=True).reserve([], 'maintenance').finish()

for other_remaining in [0, -1, 2**128]:
    s = Scenario('other_owner_blocks_even_zero_or_negative_' + str(other_remaining), bag(
        holds={'storage': [hold(remaining=other_remaining)], 'battle': []}, reserved={'1': 0}))
    s.reserve([request()]).allocate(count=1).finish()

s = Scenario('unbounded_accounting_and_source_negative_reserved', bag(
    reserved={'1': -2**160, '2': 2**160, '10': 0},
    holds={'battle': [hold(count=2**170, remaining=2**170, before=-2**180)]}))
s.allocate(count=2**159).reserve([request(count=2**158), request(count=2**158)])
s.allocate(count=2**158).reserve([request(2, 1)]).finish()

# Malformed values are not silently coerced: exact source check and error precedence.
for count in [None, True, False, 0, -1, -2**128, 0.0, 1.0, 1.5, '', '1', [], {}, [1], 2**160]:
    s = Scenario('malformed_or_huge_count_' + str(len(SCENARIOS)))
    s.reserve([request(2, 1), request(count=count)]).finish()
for index in [None, True, False, -1, 0, 256, 65535, 65536, 2**160, 1.0, 1.5, '', '01', '+1', ' 1', '1 ', '1.0', '１', [], {}, [1], '1', 1]:
    s = Scenario('index_conversion_' + str(len(SCENARIOS)))
    s.reserve([request(index)]).finish()
for value in [None, False, True, 42.0, 42.5, '42', [], {}, 2**160, 43, 42]:
    s = Scenario('item_identity_equality_' + str(len(SCENARIOS)))
    s.reserve([request(item_id=value)]).reserve([request(4, item_id=value)]).finish()
s = Scenario('missing_fields_and_malformed_rows')
for row in [{}, {'index': 1}, {'count': 1}, {'index': 1, 'count': 1},
            None, [], [1], 'x', True, False, 1, 1.0]:
    s.reserve([row])
s.finish()
s = Scenario('boolean_item_identity_matches_one_but_not_index')
s.reserve([request(4, item_id=True)]).reserve([request(True, item_id=True)]).finish()
s = Scenario('huge_positive_and_negative_current_counts', bag(items={'1': item(count=2147483647), '2': item(2, count=-2147483648)}))
s.allocate(count=2147483647).reserve([request(count=2147483647)]).allocate(count=1).finish()

s = Scenario('seeded_zero_slot_and_item_are_not_revalidated', bag(items={'0': item(0, 0, 10), '255': item(255, 65535, 255)}))
s.allocate(0, 1).reserve([request(0, item_id=False)]).reserve([request(0, item_id=0)], exclusive=True)
s.allocate(0, 0).allocate(65535, 255).finish()

for scenario in range(70):
    initial = bag()
    if scenario % 3 == 0:
        initial['reserved'] = {str(i): RNG.choice([-2, 0, 3, 2**100]) for i in [1, 2, 10]}
    if scenario % 5 == 0:
        initial['holds'] = {'crafting': [hold(index=2, exclusive=bool(scenario % 2), uncertain=bool(scenario % 3))]}
    s = Scenario('mixed_planning_' + str(scenario), initial)
    for _ in range(22):
        if RNG.randrange(3) == 0:
            s.allocate(RNG.choice([1, 42, 43, 65535, -1]), RNG.choice([-1, 0, 1, 3, 10, 100, 2**100]))
        else:
            rows = [request(RNG.choice([1, 2, '2', 3, 4, 10, 255]), RNG.choice([False, 0, 1, 2, 4, 2**100]),
                            RNG.choice([1, 42, 43, 65535])) for _ in range(RNG.randrange(4))]
            s.reserve(rows, RNG.choice(['battle', 'alchemy', 'expedition', 'maintenance', 'crafting', 'storage', 'unknown']), bool(RNG.randrange(2)))
    s.finish()

sources = ['wlre/services/items/inventory.py', 'wlre/services/items/reservations.py',
           'wlre/services/items/catalog.py', 'wlre/services/items/live_combat_catalog.py',
           'wlre/network/live_data.py', 'wlre/network/wire.py']
provenance = {path: hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for path in sources}
HEADER = ['// Generated by generate_inventory_planning_vectors.py. Synthetic offline proposals only.',
          'namespace Lala.Core.Tests.Inventory;', 'public static partial class InventoryPlanningPythonVectors', '{']
entries = ['        yield return new object[] { ' + json.dumps(name) + ', ' +
           csharp_gzip_json(json.dumps(steps, ensure_ascii=False, separators=(',', ':'), allow_nan=False)) + ' };'
           for name, steps in SCENARIOS]


def part(index, rows):
    return ('\n'.join(HEADER + [f'    private static IEnumerable<object[]> SequencesPart{index:02d}()', '    {'] + rows + ['    }', '}']) + '\n').encode('utf-8')


parts, current = [], []
for entry in entries:
    if current and len(part(len(parts)+1, current + [entry])) > 500_000:
        parts.append(current)
        current = []
    assert len(part(len(parts)+1, [entry])) <= 500_000
    current.append(entry)
if current: parts.append(current)
output = Path(__file__).with_name('InventoryPlanningPythonVectors.cs')
lines = HEADER + ['    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
                  '    public static IEnumerable<object[]> Sequences()', '    {']
lines += [f'        foreach (var row in SequencesPart{index:02d}()) yield return row;' for index in range(1, len(parts)+1)]
lines += ['    }', '}']
generated = {output: ('\n'.join(lines)+'\n').encode('utf-8')}
for index, rows in enumerate(parts, 1): generated[output.with_name(f'{output.stem}.Part{index:02d}.cs')] = part(index, rows)
for path, payload in generated.items():
    assert len(payload) <= 500_000
    path.write_bytes(payload)
for stale in output.parent.glob(f'{output.stem}.Part*.cs'):
    if stale not in generated: stale.unlink()
print(f'{len(SCENARIOS)} sequences; {sum(len(steps) for _, steps in SCENARIOS)} snapshots; '
      f'{len(generated)} files; max {max(map(len, generated.values()))} bytes')
