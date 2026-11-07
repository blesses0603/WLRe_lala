"""Offline receive parity for bag and companion slices, not commands or live authority.

Uses retained apply_live/apply_inventory/add_item/reservations and S8 local observer.
Synthetic catalog projections are explicitly injected, never activated or verified.
No accounts, network, State.apply observers or external resources. Run at repo root.
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
from wlre.core import inventory_updates
from wlre.core.state_session_events import apply_session_event
from wlre.services.items import combat_resources, reservations
from wlre.services.items.live_combat_catalog import _pinned
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError

RNG = random.Random(23151581107)
RULES = {'42': True, '43': False, '65535': True}
NPCS = {'1': [1001, 0, 1002, 1001, 0], '2': [0, 1002, 65535]}
CATALOG = dict(items={}, skills={}, keys={}, characters=[], element_weights={},
               npcs={key: {'skills': values} for key, values in NPCS.items()})
inventory_updates.STACKABLE = RULES
_pinned.set(CATALOG)
SCENARIOS = []


def pack(fmt, *args): return struct.pack('<' + fmt, *args)


def item(item_id=42, count=2, serial=9, version=2, equip=False):
    data = pack('H', item_id) + (b'' if equip else pack('B', count)) + pack('BBI', 254, version, serial)
    if not equip: data += pack('II', 0x80000000, 0xffffffff)
    data += pack('HddBBH', 65535, -123.5, 1e-100, 255, 254, 65535)
    if not equip: data += pack('H', 65534)
    data += pack('BHI', 253, 65533, 0xffffffff)
    data += b''.join(pack('BH', i, 65535-i) for i in range(4)) + pack('BBB', 3, 255, 254)
    return data + (b'' if equip else b'\xfd')


def row(index=1, item_id=42, count=2, serial=9, version=2):
    return pack('B', index) + item(item_id, count, serial, version)


def pet(simple=False, exp=-2147483648):
    if simple: data = pack('BHHHHHBI', 255, 101, 202, 303, 404, 505, 254, exp & 0xffffffff)
    else:
        name = '星河😀'.encode('utf-16le')
        data = pack('iBiHHHHHHBBBH', exp, 254, -2147483648, 65535, 303, 101, 202, 505, 404, 0, 255, 254, 65535) + pack('B', len(name)) + name
    data += b''.join(pack('BI', level, value) for level, value in [(3, 4), (0, 0xffffffff), (255, 1), (2, 5), (1, 6)])
    if simple: data += b'\xfe'
    data += b''.join(item(i, equip=True) for i in range(1, 10))
    if not simple: data += b'\xff'
    data += pack('BBBH', 253, 2, 255, 65535)
    if not simple: data += b'\xff'
    return data + pack('H', 65535)


def companion(index=1, npc=1, exp=-2147483648): return pack('BH', index, npc) + pet(exp=exp)
def add_pet(owner=7, npc=1): return pack('II', owner, npc) + pet(True) + b'\xff'
def attribute(index=1, kind=25, value=999, parameter=0, human=4):
    return pack('BHBBII', human, index, kind, 2 if value < 0 else 1, abs(value), parameter)


def initial():
    return SimpleNamespace(inventory=dict(ready=False, reliable=False, items={}, reserved={}, revision=0, use_failed=False),
        knowledge=dict(player=dict(ready=False, skills={}, stats={}), companions={}, companions_ready=False, active_npc_id=None),
        attributes={}, player={'role_id': 7}, battle_units={})


def project(state):
    inv = copy.deepcopy(state.inventory)
    for key in ['capacity', 'sync_error', 'last_use_result', 'field_supply', 'alchemy_slots', 'expedition_slots', 'maintenance_slots', 'server_stackable']:
        inv.setdefault(key, None)
    inv.setdefault('holds', {})
    return copy.deepcopy(dict(inventory=inv, item_order=list(inv['items']), hold_order=list(inv['holds']),
        available={str(i): reservations.available(state.inventory, i) for i in [0, 1, 2, 3, 4, 255, 65535]},
        companions=state.knowledge['companions'], companions_ready=state.knowledge['companions_ready'],
        active_npc_id=state.knowledge['active_npc_id'], companion_order=list(state.knowledge['companions']),
        attributes=state.attributes))


class Scenario:
    def __init__(self, name, seed=None):
        self.name, self.state, self.steps = name, initial(), []
        if seed: seed(self.state)
        self.record(None)

    def record(self, operation, error=None):
        self.steps.append(dict(operation=operation, error=error, expected=project(self.state)))

    def packet(self, main, sub, payload=b''):
        operation = dict(main=main, sub=sub, hex=payload.hex())
        try:
            event = decode(Packet(main, sub, payload))
            combat_resources.apply_live(self.state, event)
            if event['type'] == 'attribute_set': apply_session_event(self.state, event)
            self.record(operation)
        except ProtocolError as exc: self.record(operation, str(exc))
        return self

    def bag(self, *rows, capacity=8): return self.packet(23, 5, pack('B', capacity) + b''.join(rows))
    def add(self, index=1, item_id=42, count=2, serial=9): return self.packet(23, 6, row(index, item_id, count, serial) + b'\xff\xff')
    def delete(self, index=1, count=1): return self.packet(23, 9, pack('BBB', index, count, 255))
    def reset(self):
        self.state = initial(); self.record({'reset': True}); return self
    def finish(self): SCENARIOS.append((self.name, self.steps)); return self


s = Scenario('bag_snapshot_identity_counts_unknown_rules_and_late_replacement')
s.add(255, 999, 1).bag(row(4, 999, 255), row(1, 42, 254)).add(1, 42, 2)
s.packet(23, 140, pack('BBBI B', 1, 1, 4, 0xffffffff, 255)).add(0, 42, 1)
s.bag(row(3, 999, 200)).bag(row(3, 999, 200)).bag(row(3, 999, 200)).finish()

s = Scenario('stack_preferred_order_split_nonstack_unknown_and_atomic_failure')
s.bag(row(3, 42, 199), row(1, 42, 198), row(4, 43, 1), capacity=6).add(0, 42, 255)
s.add(0, 43, 2).delete(4).add(4, 43, 1).add(4, 42, 1).add(255, 42, 1)
s.bag(capacity=1).add(255, 43, 1).add(1, 999, 2).add(1, 999, 1).add(0, 999, 1)
s.bag(row(1, 42, 199), capacity=1).add(1, 42, 2).finish()

s = Scenario('invalid_snapshot_discard_then_recovery_and_failed_add_latch')
for rows, capacity in [((), 0), ((row(1), row(1)), 8), ((row(0),), 8), ((row(9),), 8), ((row(1, 0),), 8), ((row(1, count=0),), 8)]:
    s.bag(row(1)).bag(*rows, capacity=capacity).add(2, 42, 1)
s.bag().add(1, 0, 1).add(1, 42, 0).bag(row(255, count=255), capacity=255).finish()

s = Scenario('deductions_damage_break_use_result_and_acknowledgements')
s.bag(row(1, count=2)).delete(1, 0).delete(1, 3).delete(1, 1).delete(1, 1).delete(1, 0)
s.packet(27, 6, pack('IBB', 0xffffffff, 1, 255)).packet(23, 140, pack('BBBI B', 1, 1, 3, 1234, 0))
s.bag(row(2, count=3)).packet(23, 140, pack('BBBBH', 2, 1, 2, 0, 999)).packet(23, 140, pack('BBBBH', 2, 1, 2, 0, 0))
for result in [3, 0, 4, 1, 2, 255]: s.packet(23, 15, pack('B', result) + (pack('BH', 1, 42) if result == 2 else b''))
s.packet(27, 1, b'\x00').packet(27, 8, b'\xff').bag(row()).finish()


def held_seed(state):
    combat_resources.apply_live(state, decode(Packet(23, 5, b'\x08' + row(1, count=8) + row(2, count=5) + row(3, count=4))))
    def hold(index, count, remaining, before, serial=9, uncertain=False, exclusive=False):
        return dict(index=str(index), identity=[42, serial, 2], count=count, remaining=remaining, before=before, uncertain=uncertain, exclusive=exclusive)
    state.inventory.update(holds={'crafting': [hold(1, 3, 3, 8), hold(2, 1, 1, 5, exclusive=True)],
        'battle': [hold(1, 2, 2, 8)], 'alchemy': [hold(3, 4, 4, 4)], 'maintenance': []},
        reserved={'1': 5, '2': 1, '3': 4}, alchemy_slots=['3'], maintenance_slots=['255'], expedition_slots=['2'],
        field_supply=dict(status='waiting', reason='synthetic', item_id=42, pending=True, uncertain=False), server_stackable={'999': True, '43': True})

for mode in range(8):
    s = Scenario('holds_refresh_and_deductions_' + str(mode), held_seed)
    if mode == 0: s.delete(1, 2).bag(row(1, count=5), row(2, count=4)).delete(1, 255)
    elif mode == 1: s.bag(row(1, count=5), row(2, count=4), row(3, count=4)).bag(row(1, count=8), row(2, count=5), row(3, count=4))
    elif mode == 2: s.bag(row(1, count=8, serial=10), row(2, count=5), row(3, count=4))
    elif mode == 3: s.bag(row(1, item_id=43, count=8), row(2, count=5))
    elif mode == 4: s.bag()
    elif mode == 5: s.bag(row(1), row(1)).bag(row(1, count=8), row(2, count=5), row(3, count=4))
    elif mode == 6: s.add(0, 999, 255).add(0, 43, 2).delete(3, 4).bag(row(1, count=8), row(2, count=5))
    else:
        s.state.inventory['holds']['crafting'][0]['uncertain'] = True
        s.steps = []; s.record(None); s.bag(row(1, count=8), row(2, count=5), row(3, count=4))
    s.bag(row(1, count=8), row(2, count=5), row(3, count=4)).finish()

s = Scenario('companion_partial_batches_duplicate_reassign_delete_and_add')
s.packet(15, 1, add_pet()).packet(15, 8).packet(15, 1, add_pet(8))
s.packet(15, 8, companion(3, 1)).packet(15, 8, companion(1, 2)).packet(15, 8)
s.packet(15, 8, companion(3, 1, -1) + companion(3, 2, 123)).packet(15, 1, add_pet(npc=0xffffffff))
s.packet(15, 2, pack('IBB', 8, 1, 0)).packet(15, 2, pack('IBB', 7, 1, 255)).packet(15, 1, add_pet())
s.packet(19, 1, pack('I', 0xffffffff)).packet(19, 4, pack('I', 1)).packet(15, 2, pack('IBB', 7, 1, 0)).packet(19, 2).finish()

s = Scenario('buffered_attributes_same_identity_replay_different_identity_clear')
s.packet(8, 2, attribute()).packet(8, 2, attribute(kind=110, parameter=1001, value=0))
s.packet(8, 2, attribute(kind=110, parameter=1002, value=4)).packet(8, 2, attribute(kind=206, value=65535, human=9))
s.packet(15, 8, companion()).packet(8, 2, attribute(kind=110, parameter=1001, value=3))
s.packet(8, 2, attribute(kind=110, parameter=1002, value=-1)).packet(15, 8, companion(exp=123))
s.packet(15, 8, companion(npc=2)).packet(8, 2, attribute(value=1000)).packet(15, 2, pack('IBB', 7, 1, 0))
s.packet(15, 1, add_pet(npc=2)).packet(8, 2, attribute(index=65535, value=-0xffffffff)).finish()

s = Scenario('all_companion_stat_kinds_repeated_parameters_and_human_kinds')
s.packet(15, 8, companion(0, 1) + companion(255, 999))
for kind in [25, 26, 27, 28, 29, 30, 33, 35, 36, 38, 39, 41, 43, 46, 47, 205, 206, 110, 255]:
    s.packet(8, 2, attribute(0, kind, -0xffffffff, 0xffffffff)).packet(8, 2, attribute(255, kind, 0xffffffff, 0, 9))
s.packet(15, 8, companion(255, 999)).finish()

s = Scenario('all_companion_slots_full_no_add_and_reuse')
s.packet(15, 8, b''.join(companion(i, 1) for i in range(256))).packet(15, 1, add_pet(npc=2))
s.packet(15, 2, pack('IBB', 7, 255, 0)).packet(15, 1, add_pet(npc=2)).finish()

s = Scenario('malformed_atomic_and_empty_boundary_packets', held_seed)
packets = [(23, 5, b'\x08' + row()), (23, 6, row() + b'\x00\x00'), (23, 9, b'\x01\x01\xff'),
    (27, 6, pack('IBB', 123, 1, 1)), (23, 140, pack('BBBI B', 1, 1, 1, 0xffffffff, 0)),
    (23, 15, b'\x02\x01\x2a\x00'), (15, 8, companion()), (15, 1, add_pet()),
    (15, 2, pack('IBB', 7, 1, 0)), (19, 1, pack('I', 1)), (19, 2, b''), (8, 2, attribute())]
for main, sub, payload in packets:
    for cut in sorted(set([0, 1, len(payload)//2, len(payload)-1])):
        if 0 <= cut < len(payload): s.packet(main, sub, payload[:cut])
    s.packet(main, sub, payload + b'\x7f')
for value in [float('nan'), float('inf'), float('-inf')]:
    broken = bytearray(row()); broken[20:28] = pack('d', value); s.packet(23, 5, b'\x08' + broken)
s.packet(23, 140, b'\xff').packet(255, 255, b'ignored').finish()

for scenario_index in range(60):
    s = Scenario('mixed_sequence_' + str(scenario_index), held_seed if scenario_index % 3 == 0 else None)
    for step in range(22):
        op = RNG.randrange(15); index = RNG.choice([0, 1, 2, 3, 255]); count = RNG.choice([0, 1, 2, 199, 200, 255]); sid = RNG.choice([0, 42, 43, 999, 65535])
        if op == 0: s.bag(row(index, sid, count), capacity=RNG.choice([0, 1, 4, 255]))
        elif op == 1: s.add(index, sid, count)
        elif op == 2: s.delete(index, count)
        elif op == 3: s.packet(23, 140, pack('BBBI B', 1, 1, index, RNG.choice([0, 255, 0xffffffff]), 255))
        elif op == 4: s.packet(23, 140, pack('BBBBH', 2, 1, index, 255, sid))
        elif op == 5: s.packet(15, 8, companion(index, RNG.choice([1, 2, 999])))
        elif op == 6: s.packet(15, 1, add_pet(RNG.choice([7, 8]), RNG.choice([1, 2, 999])))
        elif op == 7: s.packet(15, 2, pack('IBB', RNG.choice([7, 8]), index, count))
        elif op == 8: s.packet(8, 2, attribute(index, RNG.choice([25, 36, 46, 110, 205]), RNG.choice([-1, 0, 1, 0xffffffff]), RNG.choice([0, 1001, 1002]), RNG.choice([4, 9])))
        elif op == 9: s.packet(23, 15, pack('B', RNG.choice([0, 1, 3, 4, 255])))
        elif op == 10: s.packet(15, 8)
        elif op == 11: s.packet(19, 1, pack('I', sid))
        elif op == 12: s.bag()
        elif op == 13: s.packet(27, 6, pack('IBB', 0xffffffff, index, count))
        else: s.reset()
    s.finish()

sources = ['wlre/core/inventory_updates.py', 'wlre/services/items/inventory.py', 'wlre/services/items/reservations.py',
    'wlre/services/items/combat_resources.py', 'wlre/services/items/live_combat_catalog.py', 'wlre/core/state_session_events.py',
    'wlre/network/live_data.py', 'wlre/network/protocol.py', 'wlre/network/wire.py']
provenance = {p: hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in sources}
lines = ['// Generated by generate_live_inventory_vectors.py. Synthetic offline receive-only parity.',
    'namespace Lala.Core.Tests.Inventory;', 'public static class LiveInventoryPythonVectors', '{',
    '    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
    '    public static IEnumerable<object[]> Sequences()', '    {']
for name, steps in SCENARIOS:
    raw = json.dumps(steps, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
    lines.append('        yield return new object[] { ' + json.dumps(name) + ', Decode(' + json.dumps(encoded) + ') };')
lines += ['    }', '    private static string Decode(string encoded)', '    {',
    '        using var input = new System.IO.MemoryStream(System.Convert.FromBase64String(encoded));',
    '        using var gzip = new System.IO.Compression.GZipStream(input, System.IO.Compression.CompressionMode.Decompress);',
    '        using var reader = new System.IO.StreamReader(gzip, System.Text.Encoding.UTF8);',
    '        return reader.ReadToEnd();', '    }', '}']
output = Path(__file__).with_name('LiveInventoryPythonVectors.cs')
output.write_text('\n'.join(lines) + '\n')
print(f'{len(SCENARIOS)} sequences; {sum(len(s) for _, s in SCENARIOS)} snapshots; {output.stat().st_size} bytes')
