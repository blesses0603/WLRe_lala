"""Pure reservations helpers and receive-composition oracle on synthetic dictionaries.

Runs the retained release/uncertain/checkpoint/restore/identity/locked/_slots methods.
Existing inventory.apply_inventory supplies consumed/refreshed observations; no copies
of those algorithms, sessions, packet sends, resources or live holds are used here.
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

RNG = random.Random(202611080329)
SCENARIOS = []
QUERIES = [0, 1, 2, 3, 4, 10, 255, 65535, -1, 65536, 2**128,
           '1', '01', '+1', ' 1', '1.0', 1.0, True, False, None, [], {}, [1]]


def item(index=1, item_id=42, count=10, serial=9, version=2):
    raw = struct.pack('<HBBBIIIHddBBHHBHI', item_id, 1, 254, version, serial,
        0x80000000, 0xffffffff, 65535, -123.5, 1e-100, 255, 254, 65535, 65534,
        253, 65533, 0xffffffff)
    raw += b''.join(struct.pack('<BH', i, 65535-i) for i in range(4)) + bytes([3, 255, 254, 253])
    value = item_save(Reader(raw), index)
    value['count'] = count
    return value


def hold(index=1, count=2, remaining=2, before=10, exclusive=False, uncertain=False,
         item_id=42, serial=9, version=2):
    return dict(index=str(index), count=count, remaining=remaining, before=before,
                exclusive=exclusive, uncertain=uncertain, identity=[item_id, serial, version])


def bag(**updates):
    result = dict(ready=True, reliable=True, capacity=255, revision=2**100, use_failed=True,
        sync_error='retained unrelated diagnostic', last_use_result=4,
        items={'10': item(10, count=7), '2': item(2, count=8), '1': item(1),
               '3': item(3, 43, 6), '4': item(4, 1, 6), '255': item(255, 65535, 255)},
        reserved={}, holds={}, field_supply={'nested': ['keep', {'quantity': 2**100}]},
        server_stackable={'42': True, '43': False})
    result.update(updates)
    return result


def project(state, saved):
    value = copy.deepcopy(state)
    for key in ['capacity', 'sync_error', 'last_use_result', 'field_supply',
                'alchemy_slots', 'expedition_slots', 'maintenance_slots', 'server_stackable']:
        value.setdefault(key, None)
    return dict(inventory=value, item_order=list(state['items']), hold_order=list(state.get('holds', {})),
        available={str(index): reservations.available(state, index) for index in [0, 1, 2, 3, 4, 255, 65535]},
        locked=[reservations.locked(state, index) for index in QUERIES],
        identities={key: list(reservations.identity(value)) for key, value in state['items'].items()},
        checkpoints=copy.deepcopy(saved),
        checkpoint_fields={key: list(value) for key, value in saved.items()},
        checkpoint_hold_order={key: list(value['holds']) for key, value in saved.items()})


class Scenario:
    def __init__(self, name, initial=None):
        self.name, self.state = name, copy.deepcopy(initial if initial is not None else bag())
        self.saved = {}
        self.steps = [dict(operation=None, expected=project(self.state, self.saved))]

    def operation(self, kind, **values):
        operation = dict(kind=kind, **copy.deepcopy(values))
        if kind == 'checkpoint': self.saved[values['name']] = reservations.checkpoint(self.state)
        elif kind == 'restore': reservations.restore(self.state, self.saved[values['name']])
        elif kind == 'release': reservations.release(self.state, values['owner'])
        elif kind == 'uncertain': reservations.uncertain(self.state, values['owner'])
        elif kind == 'slots': reservations._slots(self.state, values['owner'])
        elif kind == 'receive':
            host = SimpleNamespace(inventory=self.state)
            inventory.apply_inventory(host, values['event'])
            self.state = host.inventory
        else: raise AssertionError(kind)
        self.steps.append(dict(operation=operation, expected=project(self.state, self.saved)))
        return self

    def checkpoint(self, name='A'): return self.operation('checkpoint', name=name)
    def restore(self, name='A'): return self.operation('restore', name=name)
    def release(self, owner='battle'): return self.operation('release', owner=owner)
    def uncertain(self, owner='battle'): return self.operation('uncertain', owner=owner)
    def slots(self, owner): return self.operation('slots', owner=owner)
    def receive(self, event): return self.operation('receive', event=event)
    def delete(self, index=1, count=1): return self.receive(dict(type='bag_delete', index=index, count=count))
    def snapshot(self, rows=None, capacity=255):
        return self.receive(dict(type='bag_snapshot', capacity=capacity,
                                items=[item(1), item(2), item(3, 43)] if rows is None else rows))
    def finish(self): SCENARIOS.append((self.name, self.steps)); return self


s = Scenario('missing_slot_defaults_are_saved_then_restored_only_as_empty_lists')
s.checkpoint().uncertain('missing').release('missing').slots('missing').checkpoint('B')
s.restore().release('alchemy').release('expedition').release('maintenance').restore('B').finish()

for owner in ['battle', 'field_supply', 'alchemy', 'crafting', 'expedition', 'maintenance', 'storage', 'legacy', '', 'Alchemy']:
    initial = bag(ready=False, reliable=False, reserved={'1': 10, '2': 8},
        holds={'other': [hold(remaining=3)], owner: [hold(uncertain=True), hold(2, exclusive=True)], 'last': []},
        alchemy_slots=['10', '1', '1'], expedition_slots=['2', '65535'], maintenance_slots=['4'])
    s = Scenario('release_has_no_owner_or_readiness_gate_' + owner, initial)
    s.checkpoint().release(owner).release(owner).checkpoint('B').restore().uncertain(owner)
    s.release(owner).restore('B').finish()

s = Scenario('duplicate_rows_clamp_in_order_and_leave_other_owners_untouched', bag(
    holds={'first': [], 'battle': [hold(remaining=3), hold(remaining=-5), hold(remaining=2),
        hold(2, remaining=2**140), hold(65535, remaining=-2**160)],
        'storage': [hold(remaining=8, exclusive=True)]}, reserved={'1': 1, '2': 2**140-1}))
s.checkpoint().release().restore().delete(count=1).release().restore().finish()

s = Scenario('uncertain_marks_all_rows_without_reliability_or_counter_changes', bag(
    holds={'battle': [hold(remaining=0), hold(2, remaining=-3), hold(3, remaining=2**150)],
        'legacy': [hold(remaining=0)], 'empty': []}, reserved={'1': 0, '2': -7, '3': 2**150}))
s.checkpoint().uncertain().uncertain().uncertain('legacy').uncertain('empty').uncertain('missing')
s.checkpoint('uncertain').restore().restore('uncertain').snapshot().release().finish()

for owner, field in [('alchemy', 'alchemy_slots'), ('expedition', 'expedition_slots'), ('maintenance', 'maintenance_slots')]:
    s = Scenario('slot_projection_preserves_first_occurrence_' + owner, bag(
        holds={owner: [hold(10, remaining=0), hold(2, uncertain=True), hold(10, remaining=-9), hold(65535), hold(1)]},
        **{field: ['4', '4', '255']}))
    s.checkpoint().slots(owner).checkpoint('projected').uncertain(owner).slots(owner)
    s.restore().release(owner).restore('projected').finish()

s = Scenario('checkpoint_restores_only_reservation_fields_after_server_item_changes', bag(
    holds={'battle': [hold(remaining=2)], 'crafting': [hold(2, remaining=1)]}, reserved={'1': 2, '2': 1},
    alchemy_slots=['10', '1', '10'], expedition_slots=[], maintenance_slots=['255']))
s.checkpoint().delete(count=2).checkpoint('after_deduction')
s.receive(dict(type='bag_damage', index=2, damage=0xffffffff))
s.snapshot([item(1, serial=999), item(2, count=6), item(3, 43)])
s.restore().checkpoint('restored').snapshot().restore('after_deduction').snapshot([]).restore('restored').finish()

s = Scenario('checkpoint_roundtrip_does_not_project_stale_slots_or_revalidate_identity', bag(
    holds={'alchemy': [hold(2, item_id=43, serial=None, version=None)], 'battle': []},
    reserved={'1': -2**150, '65535': 2**180}, alchemy_slots=['255', '255', '10'],
    expedition_slots=['1', '2', '1'], maintenance_slots=['65535', '0']))
s.checkpoint().release('alchemy').checkpoint('B').restore().restore('B').restore().finish()

for order in [('battle', 'storage', 'crafting'), ('storage', 'battle', 'crafting'), ('crafting', 'storage', 'battle')]:
    s = Scenario('receive_consumed_keeps_original_owner_order_' + '_'.join(order), bag(
        holds={owner: [hold(remaining=2), hold(2, remaining=0, uncertain=True)] for owner in order},
        reserved={'1': 6, '2': 0}))
    s.checkpoint().delete(count=3).checkpoint('deducted').uncertain('storage').delete(count=3)
    s.restore().delete(count=6).restore('deducted').release('storage').finish()

s = Scenario('refresh_after_uncertainty_and_hypothetical_release_uses_existing_receive_reducer', bag(
    holds={'battle': [hold()], 'expedition': [hold(2)]}, reserved={'1': 2, '2': 2}))
s.checkpoint().uncertain('expedition').snapshot().checkpoint('uncertain')
s.release('expedition').snapshot().restore('uncertain').snapshot().restore().snapshot().finish()

# Typed bag identities retain zero/max values and exclude current count/damage/slot.
s = Scenario('identity_wire_boundaries_and_unrelated_metadata', bag(items={
    '0': item(0, 0, count=-1, serial=0, version=0), '255': item(255, 65535, serial=0xffffffff, version=255)}))
s.checkpoint().receive(dict(type='bag_damage', index=255, damage=0xffffffff)).restore().finish()

for scenario in range(45):
    owners = RNG.sample(['battle', 'storage', 'crafting', 'alchemy', 'expedition', 'maintenance', 'legacy', ''], 4)
    holds = {owner: [hold(RNG.choice([0, 1, 2, 3, 255, 65535]), count=RNG.choice([-1, 0, 2, 2**130]),
        remaining=RNG.choice([-2**140, -1, 0, 2, 2**140]), before=RNG.choice([-1, 0, 10, 2**150]),
        exclusive=bool(RNG.randrange(2)), uncertain=bool(RNG.randrange(2))) for _ in range(RNG.randrange(5))] for owner in owners}
    initial = bag(holds=holds, reserved={str(i): RNG.choice([-2**120, -1, 0, 3, 2**120]) for i in [0, 1, 2, 3, 255, 65535]})
    for field in ['alchemy_slots', 'expedition_slots', 'maintenance_slots']:
        if RNG.randrange(2): initial[field] = [str(RNG.choice([0, 1, 2, 3, 255, 65535])) for _ in range(RNG.randrange(5))]
    s = Scenario('mixed_checkpoints_proposals_and_receive_' + str(scenario), initial).checkpoint()
    for _ in range(24):
        choice = RNG.randrange(7)
        owner = RNG.choice(owners + ['missing', 'battle'])
        if choice == 0: s.checkpoint(RNG.choice(['A', 'B', 'C']))
        elif choice == 1: s.restore(RNG.choice(list(s.saved)))
        elif choice == 2: s.release(owner)
        elif choice == 3: s.uncertain(owner)
        elif choice == 4: s.slots(owner)
        elif choice == 5: s.delete(RNG.choice([0, 1, 2, 3, 255]), RNG.choice([0, 1, 2, 255]))
        else: s.snapshot([item(1, count=RNG.choice([1, 2, 10]), serial=RNG.choice([9, 999])), item(2, count=8)])
    s.finish()

sources = ['wlre/services/items/reservations.py', 'wlre/services/items/inventory.py',
           'wlre/network/live_data.py', 'wlre/network/wire.py']
provenance = {path: hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for path in sources}
HEADER = ['// Generated by generate_reservation_planning_vectors.py. Synthetic offline proposals only.',
          'namespace Lala.Core.Tests.Inventory;', 'public static partial class ReservationPlanningPythonVectors', '{']
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
output = Path(__file__).with_name('ReservationPlanningPythonVectors.cs')
lines = HEADER + ['    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
                  '    public const string QueryJson = ' + json.dumps(json.dumps(QUERIES, separators=(',', ':'))) + ';',
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
