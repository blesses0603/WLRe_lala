"""Synthetic offline oracle for room_storage/recovery receive reducers, never actions.

Runs retained defaults/apply_storage/apply_recovery/confirmed_material_count plus the
actual reservations.consumed/available and receive decoders. No State.apply observers,
transports, catalogs, account data, moves, potions, retries or persistence are invoked.
Regenerate from repository root; compressed C# data uses deterministic gzip mtime=0.
"""
import base64
import copy
import gzip
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
from wlre.services.items import room_storage, recovery, reservations
from wlre.network.wire import Packet, ProtocolError

RNG = random.Random(62232081107)
ITEM_IDS = [0, 1, 2, 42, 43, 255, 65535]
INDICES = [0, 1, 2, 3, 255, 65535]
scenarios = []


def pack(fmt, *values):
    return struct.pack('<' + fmt, *values)


def garage(index=1, item_id=42, count=2, serial=0xffffffff, version=253):
    return pack('BHBBBIIIHddBBHHBHI', index, item_id, count, 254, version, serial,
                0x80000000, 0, 65535, -123.5, 1e-100, 255, 254, 65535, 65534,
                253, 65533, 0xffffffff) + b''.join(pack('BH', i, 65535-i) for i in range(4)) + pack('BBBB', 3, 255, 254, 253)


def material_initial(*rows):
    return pack('BBH', 1, 1, len(rows)) + b''.join(pack('HHH', *row) for row in rows)


def material_add(index=1, item_id=42, count=1):
    return pack('BBHHH', 1, 2, index, item_id, count)


def initial():
    return SimpleNamespace(room_storage=room_storage.defaults(), potion_storage={}, inventory={})


def project(state):
    return copy.deepcopy({
        'storage': state.room_storage,
        'potion_storage': state.potion_storage,
        'server_stackable': state.inventory.get('server_stackable'),
        'item_order': {bucket: list(state.room_storage[bucket]['items']) for bucket in ('garage', 'materials')},
        'hold_owner_order': {bucket: list(state.room_storage[bucket]['holds']) for bucket in ('garage', 'materials')},
        'confirmed_counts': {str(item): room_storage.confirmed_material_count(state.room_storage, item) for item in ITEM_IDS},
        'available': {bucket: {str(index): reservations.available(state.room_storage[bucket], index) for index in INDICES}
                      for bucket in ('garage', 'materials')},
    })


class Scenario:
    def __init__(self, name, seed=None):
        self.name = name
        self.state = initial()
        if seed:
            seed(self.state)
        self.steps = []
        self.record(None)

    def record(self, operation, error=None):
        self.steps.append({'operation': operation, 'error': error, 'expected': project(self.state)})

    def packet(self, main, sub, payload=b''):
        operation = {'main': main, 'sub': sub, 'hex': payload.hex()}
        try:
            packet = Packet(main, sub, payload)
            event = room_storage.decode_storage(packet) or recovery.decode_recovery(packet)
            if event is not None:
                room_storage.apply_storage(self.state, event)
                recovery.apply_recovery(self.state, event)
            self.record(operation)
        except ProtocolError as exc:
            self.record(operation, str(exc))
        return self

    def direct(self, event):
        room_storage.apply_storage(self.state, event)
        recovery.apply_recovery(self.state, event)
        self.record({'direct': event})
        return self

    def reset(self):
        self.state = initial()
        self.record({'reset': True})
        return self

    def finish(self):
        scenarios.append((self.name, self.steps))


def seed_balances(state):
    room_storage.apply_storage(state, room_storage.decode_storage(Packet(62, 7, b'\x01' + garage())))
    room_storage.apply_storage(state, room_storage.decode_storage(Packet(62, 57, material_initial((1, 42, 8), (2, 42, 10), (3, 43, 6)))))
    recovery.apply_recovery(state, {'type': 'potion_balance', 'resource': 'hp', 'value': 100})
    recovery.apply_recovery(state, {'type': 'potion_balance', 'resource': 'sp', 'value': 0})


s = Scenario('defaults_receipts_and_explicit_reset')
s.packet(23, 208, pack('BBi', 4, 1, 100)).packet(62, 11, garage())
s.packet(62, 25, b'\x01\xff').packet(62, 71, b'\x01')
s.packet(62, 73, b'\xff').packet(62, 74, pack('H', 65535)).packet(62, 75, pack('H', 65535))
s.packet(62, 7, b'\x00').packet(62, 57, material_initial())
s.packet(23, 208, pack('BBi', 3, 1, 123)).reset()
s.packet(62, 13, b'\x01\x01').packet(23, 208, pack('BBi', 4, 1, 123))
s.finish()

s = Scenario('garage_append_identity_metadata_conflict_and_invalid_rows')
s.packet(62, 11, garage(count=255)).packet(62, 7, b'\x01' + garage(count=255, serial=7, version=0))
s.packet(62, 7, b'\x00').packet(62, 11, garage(count=255, serial=99))
s.packet(62, 11, garage(item_id=43)).packet(62, 11, garage(index=0))
s.packet(62, 11, garage(index=2, item_id=0)).packet(62, 11, garage(index=2, count=0))
s.packet(62, 13, b'\x01\x00').packet(62, 13, b'\x02\x01')
s.packet(62, 13, b'\x01\xff').packet(62, 13, b'\x01\xff').packet(62, 13, b'\x01\xff')
s.packet(62, 13, b'\x01\x01').packet(62, 7, b'\x01' + garage(serial=8)).finish()

s = Scenario('materials_append_stackability_before_validation_and_zero_rows')
s.packet(62, 57, material_add(0, 1, 1)).packet(62, 57, material_add(1, 42, 65535))
s.packet(62, 57, material_initial((1, 42, 1), (2, 43, 10)))
s.packet(62, 57, material_add(1, 43, 1)).packet(62, 57, material_add(3, 255, 0))
s.packet(62, 57, material_add(3, 0, 3)).packet(62, 57, material_initial())
s.packet(62, 57, pack('BHH', 2, 2, 11)).packet(62, 57, pack('BHH', 2, 2, 10))
s.packet(62, 57, material_add(2, 1, 1)).finish()

s = Scenario('materials_overgrown_count_is_retained_but_not_confirmed')
s.packet(62, 57, material_initial((1, 42, 65535), (2, 43, 1)))
s.packet(62, 57, material_add()).packet(62, 57, pack('BHH', 2, 1, 1))
s.packet(62, 57, material_add()).packet(62, 57, pack('BHH', 2, 1, 65535))
s.packet(62, 57, pack('BHH', 2, 1, 1)).finish()

s = Scenario('direct_duplicate_batches_use_apply_semantics_not_decoder_validation')
for event in [
    {'type': 'storage_materials_initial', 'items': [{'index': 1, 'item_id': 42, 'count': 2}, {'index': 1, 'item_id': 42, 'count': 3}]},
    {'type': 'storage_materials_add', 'items': [{'index': 1, 'item_id': 42, 'count': 4}, {'index': 1, 'item_id': 43, 'count': 4}]},
    {'type': 'storage_garage_initial', 'items': [room_storage.decode_storage(Packet(62, 11, garage()))['item']] * 2},
    {'type': 'storage_future_receive'}, {'type': 'craft_started', 'index': 1},
    {'type': 'potion_balance', 'resource': 'hp', 'value': -1},
    {'type': 'potion_balance_add', 'resource': 'hp', 'value': 0},
]:
    s.direct(event)
s.finish()


def seed_pending(state):
    seed_balances(state)
    state.room_storage.update(pending='withdraw', uncertain=True, status='fixture pending', last_error=77,
                              last_result=99, revision=2**100)
    state.inventory['server_stackable']['65535'] = False

s = Scenario('parameters_replace_values_but_do_not_resolve_pending_or_history', seed_pending)
for sub, payload in [(71, b'\x01'), (25, b'\x01\x00'), (7, b'\x00'), (57, material_initial()),
                     (72, pack('BHH', 0, 0, 0)), (73, b'\xff'), (74, pack('H', 65535)),
                     (75, pack('H', 65535)), (72, pack('BHH', 3, 2, 1)), (71, b'\xff'),
                     (25, b'\x01\xff'), (71, b'\x00'), (11, garage())]:
    s.packet(62, sub, payload)
s.finish()

for field, value in [('pending', 'deposit'), ('pending', ''), ('uncertain', True), ('ready', False), ('reliable', False)]:
    def seed(state, field=field, value=value):
        seed_balances(state)
        (state.room_storage['materials'] if field in ('ready', 'reliable') else state.room_storage)[field] = value
    s = Scenario('count_query_' + field + '_' + str(value), seed)
    s.packet(62, 57, material_add()).packet(62, 57, material_initial()).finish()

for quantity in [0, -1, 65535, 65536, 2**100]:
    def seed(state, quantity=quantity):
        seed_balances(state)
        state.room_storage['materials']['items']['1']['count'] = quantity
        state.room_storage['materials']['reserved']['2'] = 2**100
    s = Scenario('count_integer_boundary_' + str(quantity), seed)
    s.packet(62, 57, material_add()).packet(62, 57, pack('BHH', 2, 1, 1)).finish()


def hold(index=1, remaining=3, exclusive=False, uncertain=False, item_id=42):
    return dict(index=str(index), identity=[item_id, None, None], count=3, remaining=remaining,
                before=8, exclusive=exclusive, uncertain=uncertain)

for owners in [('storage', 'battle', 'crafting'), ('battle', 'storage', 'crafting'), ('crafting', 'battle', 'storage')]:
    def seed(state, owners=owners):
        seed_balances(state)
        bucket = state.room_storage['materials']
        bucket['holds'] = {owner: [hold(remaining=2, exclusive=owner == 'storage'), hold(2, remaining=1)] for owner in owners}
        bucket['holds']['battle'].append(hold(3, remaining=0, uncertain=True))
        bucket['reserved'] = {'1': 6, '2': 3}
    s = Scenario('reservation_consumption_order_' + '_'.join(owners), seed)
    for index, count in [(1, 0), (1, 9), (1, 3), (1, 3), (2, 1), (2, 2), (1, 2), (2, 7)]:
        s.packet(62, 57, pack('BHH', 2, index, count))
    s.packet(62, 57, material_add(1, 43, 3)).finish()

for lock in ['alchemy_slots', 'expedition_slots', 'maintenance_slots', 'exclusive', 'uncertain']:
    def seed(state, lock=lock):
        seed_balances(state)
        bucket = state.room_storage['materials']
        bucket['reserved'] = {'1': 5}
        if lock.endswith('_slots'):
            bucket[lock] = ['1', '2']
        else:
            bucket['holds'] = {'storage': [hold(remaining=0, **{lock: True})]}
    s = Scenario('count_lock_' + lock, seed)
    s.packet(62, 57, pack('BHH', 2, 1, 3)).packet(62, 57, material_initial()).finish()

s = Scenario('garage_receive_consumption_preserves_serial_holds')
s.packet(62, 7, b'\x01' + garage(count=5))
# Separately seeded case below tests garage holds without adding reservation-acquire behavior.
s.finish()
def seed_garage_hold(state):
    seed_balances(state)
    state.room_storage['garage']['holds'] = {'storage': [dict(hold(remaining=2, exclusive=True), identity=[42, 0xffffffff, 253])]}
    state.room_storage['garage']['reserved'] = {'1': 2}
s = Scenario('garage_receive_consumption_keeps_nonbattle_hold', seed_garage_hold)
s.packet(62, 13, b'\x01\x02').packet(62, 11, garage(item_id=43, serial=3)).finish()

s = Scenario('recovery_independent_baselines_clamping_duplicates_and_ignored_receipts')
for bottle in [1, 2, 3, 4]:
    s.packet(23, 208, pack('BBi', 4, bottle, 2147483647))
    s.packet(23, 208, pack('BBi', 3, bottle, 0))
    s.packet(23, 208, pack('BBi', 4, bottle, -2147483648))
    s.packet(23, 208, pack('BBi', 4, bottle, 2147483647))
    s.packet(23, 208, pack('BBi', 4, bottle, 2147483647))
    s.packet(23, 208, pack('BBi', 3, bottle, 7))
    s.packet(23, 208, pack('BBi', 3, bottle, 7))
s.packet(23, 208, pack('BBB3B', 5, 3, 3, 1, 1, 255))
s.packet(23, 208, pack('BBB', 5, 4, 0))
s.packet(23, 208, pack('BBBiB', 1, 255, 1, -2147483648, 255))
s.packet(23, 208, pack('BBi', 2, 1, 2147483647)).finish()

def seed_huge_potion(state):
    state.potion_storage = {'hp': {'value': 2**100, 'revision': 2**100}, 'sp': {'revision': 42}}
s = Scenario('recovery_unbounded_value_revision_and_unknown_seed', seed_huge_potion)
for kind, bottle, value in [(4, 1, 2147483647), (4, 1, -2147483648), (4, 2, 1), (3, 2, 0), (4, 2, 0), (3, 1, 0)]:
    s.packet(23, 208, pack('BBi', kind, bottle, value))
s.finish()

# Every short prefix and trailing byte of representative packets is replayed against
# populated state: parse failures must not partially mutate any published snapshot.
examples = [(62, 7, b'\x02' + garage() + garage(2)), (62, 11, garage()), (62, 13, b'\x01\x01'),
            (62, 57, material_initial((1, 42, 2), (2, 43, 3))), (62, 57, material_add()),
            (62, 57, pack('BHH', 2, 1, 1)), (62, 25, b'\x01\xff'), (62, 71, b'\x01'),
            (62, 72, pack('BHH', 9, 10, 999)), (62, 73, b'\x01'), (62, 74, pack('H', 100)),
            (62, 75, pack('H', 100)), (23, 208, pack('BBi', 3, 1, 2147483647)),
            (23, 208, pack('BBi', 4, 4, -2147483648)), (23, 208, pack('BBB3B', 5, 3, 3, 1, 1, 255)),
            (23, 208, pack('BBBiB', 1, 255, 1, -2147483648, 255)), (23, 208, pack('BBi', 2, 1, -1))]
for i, (main, sub, payload) in enumerate(examples):
    s = Scenario('malformed_prefix_and_tail_' + str(i), seed_balances)
    for length in range(len(payload)):
        s.packet(main, sub, payload[:length])
    s.packet(main, sub, payload + b'x').packet(main, sub, payload).finish()

s = Scenario('duplicate_batches_invalid_bottles_nonfinite_and_ignored_keys', seed_balances)
for main, sub, payload in [(62, 7, b'\x02' + garage() + garage()),
                           (62, 57, material_initial((1, 42, 1), (1, 42, 2))),
                           (62, 57, b'\x01\x03'), (62, 57, b'\x03'), (23, 208, b'\x00'),
                           (23, 208, pack('BBi', 3, 0, 0)), (23, 208, pack('BBi', 4, 255, 1)),
                           (23, 208, pack('BBi', 3, 3, -1)), (23, 208, b'\x05\x01\x00'),
                           (62, 25, b'\x02'), (62, 25, b'\x02\x01ignored'), (0, 0, b''),
                           (62, 255, b'ignored'), (23, 207, b'ignored')]:
    s.packet(main, sub, payload)
for number in [float('nan'), float('inf'), float('-inf')]:
    row = bytearray(garage())
    row[20:28] = pack('d', number)
    s.packet(62, 11, bytes(row))
s.finish()

s = Scenario('maximum_garage_batch_keeps_metadata')
s.packet(62, 7, b'\xff' + b''.join(garage(i, count=255) for i in range(1, 256)))
s.packet(62, 7, b'\xff' + b''.join(garage(i, count=255, serial=7) for i in range(1, 256))).finish()

# Mixed sequence fuzzing is deterministic and uses source transitions, not an oracle copy.
for scenario_index in range(100):
    s = Scenario('mixed_sequence_' + str(scenario_index), seed_balances if scenario_index % 2 else None)
    for step in range(30):
        op = RNG.randrange(16)
        index, item, count = RNG.choice([0, 1, 2, 3, 255]), RNG.choice([0, 1, 42, 43, 65535]), RNG.choice([0, 1, 2, 255])
        if op == 0: s.packet(62, 7, b'\x01' + garage(index, item, count, RNG.randrange(2**32)))
        elif op == 1: s.packet(62, 11, garage(index, item, count, RNG.randrange(2**32)))
        elif op == 2: s.packet(62, 13, pack('BB', index, count))
        elif op == 3: s.packet(62, 57, material_initial((index, item, RNG.choice([count, 65535]))))
        elif op == 4: s.packet(62, 57, material_add(index, item, RNG.choice([count, 65535])))
        elif op == 5: s.packet(62, 57, pack('BHH', 2, index, RNG.choice([count, 65535])))
        elif op == 6: s.packet(62, 72, pack('BHH', count, count, count))
        elif op == 7: s.packet(62, 71, pack('B', count))
        elif op == 8: s.packet(62, 25, pack('BB', 1, count))
        elif op == 9: s.packet(62, RNG.choice([73, 74, 75]), pack('H', count))  # S62-73 tail errors included
        elif op == 10: s.packet(23, 208, pack('BBi', 3, RNG.choice([1, 2, 3, 4]), RNG.choice([0, 1, 2147483647])))
        elif op == 11: s.packet(23, 208, pack('BBi', 4, RNG.choice([1, 2, 3, 4]), RNG.choice([-2147483648, -1, 0, 1, 2147483647])))
        elif op == 12: s.packet(23, 208, pack('BBB', 5, RNG.choice([3, 4]), 0))
        elif op == 13: s.packet(23, 208, pack('BBi', 2, index, -1))
        elif op == 14: s.packet(62, 57, material_initial())
        else: s.reset()
    s.finish()

sources = ['wlre/services/items/room_storage.py', 'wlre/services/items/recovery.py',
           'wlre/services/items/reservations.py', 'wlre/network/live_data.py', 'wlre/network/wire.py']


def canonical_source_sha256(raw):
    # Match Git's LF text content regardless of checkout newlines. Do not decode,
    # trim, remove bare CR, or otherwise ignore real source-byte changes.
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


provenance = {path: canonical_source_sha256((ROOT/path).read_bytes()) for path in sources}
lines = ['// Generated by generate_inventory_state_vectors.py. Retained Python; synthetic offline data only.',
         'namespace Lala.Core.Tests.Inventory;', 'public static class InventoryStatePythonVectors', '{',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
         '    public static IEnumerable<object[]> Sequences()', '    {']
for name, steps in scenarios:
    data = json.dumps(steps, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    encoded = base64.b64encode(gzip.compress(data, mtime=0)).decode('ascii')
    lines.append('        yield return new object[] { ' + json.dumps(name) + ', Decode(' + json.dumps(encoded) + ') };')
lines += ['    }', '    private static string Decode(string encoded)', '    {',
          '        using var input = new System.IO.MemoryStream(System.Convert.FromBase64String(encoded));',
          '        using var gzip = new System.IO.Compression.GZipStream(input, System.IO.Compression.CompressionMode.Decompress);',
          '        using var reader = new System.IO.StreamReader(gzip, System.Text.Encoding.UTF8);',
          '        return reader.ReadToEnd();', '    }', '}']
output = Path(__file__).with_name('InventoryStatePythonVectors.cs')
output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'{len(scenarios)} sequences; {sum(len(steps) for _, steps in scenarios)} snapshots; {output.stat().st_size} bytes')
