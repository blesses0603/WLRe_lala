"""Deterministic, synthetic offline oracle for crafting defaults/room_defaults/apply_crafting.

Invokes retained Python functions, not a rewritten transition model. Only a synthetic
runtime's recipe identity list and monotonic time are injected. No runtime activation,
service observer, commands, inventory, reservation, timer or transport is executed.
Run from repository root. Output uses deterministic gzip and remains below 500 KB.
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
from unittest.mock import patch

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.services.items import crafting
from wlre.network.wire import Packet, ProtocolError

RNG = random.Random(641621126)
CONTEXTS = {
    'legacy': None,
    'recipes': [{'recipe_id': 1, 'item_id': 500}, {'recipe_id': 42, 'item_id': 65535},
                {'recipe_id': 65535, 'item_id': 500}],
}
scenarios = []


def pack(fmt, *values): return struct.pack('<' + fmt, *values)


def row(index=1, identity=42, elapsed=1250, count=2, base=20):
    return pack('BHIBI', index, identity, elapsed, count, base)


def furniture(index=7, item=39053, status=0):
    return (pack('HHHHHBH', index, item, 0, 32768, 65535, 255, 65534)
            + pack('11H', *range(11)) + pack('BB', 255, status) + b'PRIVATE')


def initial(role=100):
    return SimpleNamespace(crafting=crafting.defaults(), furniture=crafting.room_defaults(),
                           player={} if role is None else {'role_id': role})


def project(state, now):
    result = copy.deepcopy({'crafting': state.crafting, 'furniture': state.furniture})
    for domain, keys in [('crafting', ('revision', 'completed')), ('furniture', ('revision',))]:
        for key in keys: result[domain][key] = str(result[domain][key])
    result['queue_order'] = [int(index) for index in state.crafting['queue']]
    result['furniture_order'] = [int(index) for index in state.furniture['items']]
    result['elapsed'] = {str(index): [crafting.elapsed(state.crafting, r, at) for at in (now-100, now, now+100000)]
                         for index, r in state.crafting['queue'].items()}
    return result


class Scenario:
    def __init__(self, name, context='legacy', role=100, seed=None):
        self.name, self.context, self.role, self.now = name, context, role, 100.25
        self.state, self.steps = initial(role), []
        if seed: seed(self.state)
        self.record(None)

    def record(self, operation, error=None):
        self.steps.append({'operation': operation, 'error': error, 'at': self.now, 'expected': project(self.state, self.now)})

    def packet(self, main, sub, data=b'', at=None):
        self.now = self.now + 1.25 if at is None else at
        op = {'main': main, 'sub': sub, 'hex': data.hex()}
        rows = CONTEXTS[self.context]
        runtime = None if rows is None else SimpleNamespace(recipe_catalog=rows)
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime', return_value=runtime), \
             patch.object(crafting.time, 'monotonic', return_value=self.now):
            try:
                event = crafting.decode_crafting(Packet(main, sub, data))
                if event: crafting.apply_crafting(self.state, event)
                self.record(op)
            except ProtocolError as exc:
                self.record(op, str(exc))
        return self

    def direct(self, event, at=None):
        self.now = self.now + 1.25 if at is None else at
        with patch.object(crafting.time, 'monotonic', return_value=self.now):
            crafting.apply_crafting(self.state, copy.deepcopy(event))
        self.record({'direct': event})
        return self

    def barrier(self): return self.direct({'type': 'initial_data_complete'})

    def reset(self):
        self.state = initial(self.role)
        self.record({'reset': True})
        return self

    def finish(self):
        scenarios.append({'name': self.name, 'context': self.context, 'role': self.role, 'steps': self.steps})


for context in CONTEXTS:
    s = Scenario('empty_barrier_incremental_and_explicit_reset_' + context, context)
    s.barrier().barrier().packet(64, 16, row(7)).packet(64, 2, b'\x07').barrier()
    s.packet(64, 4, pack('BH', 7, 65535)).packet(64, 4, pack('BH', 7, 0)).reset()
    s.packet(64, 16, row(255)).packet(64, 16, row(2, 1)).barrier().finish()

    s = Scenario('pause_resume_backwards_clock_and_not_active_pause_' + context, context)
    s.packet(64, 1, row(3) + row(1, 1) + b'\x03', at=1000)
    s.packet(64, 3, b'\x03', at=950).packet(64, 2, b'\x03', at=1100)
    s.packet(64, 3, b'\x03', at=1101.375).packet(64, 3, b'\x03', at=1200)
    s.packet(64, 2, b'\x03', at=1300).packet(64, 3, b'\x01', at=1400)
    s.packet(64, 2, b'\x03', at=1500).packet(64, 3, b'\xff', at=1700).finish()

    s = Scenario('missing_active_unknown_start_and_snapshot_recovery_' + context, context)
    s.packet(64, 2, b'\xff').barrier().packet(64, 1, row() + b'\x02')
    s.barrier().packet(64, 16, row(2)).packet(64, 2, b'\x02').barrier()
    s.packet(64, 1, row(2) + b'\x02').packet(64, 2, b'\xff').packet(64, 1, b'\x00').finish()

    s = Scenario('complete_duplicate_late_and_compaction_' + context, context)
    s.packet(64, 1, row(255, 65535) + row(7, 42) + row(3, 1) + b'\x07')
    s.packet(64, 4, pack('BH', 3, 100)).packet(64, 4, pack('BH', 7, 100))
    s.packet(64, 4, pack('BH', 7, 100)).packet(64, 4, pack('BH', 1, 100))
    s.packet(64, 2, b'\x01').packet(64, 4, pack('BH', 1, 0)).packet(64, 4, pack('BH', 1, 0)).finish()

    s = Scenario('delete_reindexes_without_adjusting_active_or_timing_' + context, context)
    s.packet(64, 1, row(255) + row(7, 1) + row(3, 65535) + b'\xff')
    s.packet(64, 5, b'\x00').packet(64, 5, b'\x01').packet(64, 4, pack('BH', 255, 99))
    s.packet(64, 3, b'\xff').packet(64, 5, b'\x01').packet(64, 5, b'\xff').finish()

    s = Scenario('swaps_duplicates_replacement_and_human_' + context, context)
    s.packet(64, 1, row(2) + row(1, 1) + b'\x00')
    for payload in [b'\x01\x01\x02', b'\x01\x01\x01', b'\x01\x01\xff', b'\x00', b'\xff']:
        s.packet(64, 25, payload)
    s.packet(64, 16, row(1, 65535)).packet(64, 10, pack('BI', 255, 0xffffffff))
    s.packet(64, 10, pack('BI', 0, 0)).packet(64, 1, b'\x00').finish()

    def seed_pending(state):
        state.crafting.update(pending='complete', uncertain=True, auto_continue=True, completion_requested=True,
                              completed=2**100, revision=2**110, human_index=255, human_id=0xffffffff)
    s = Scenario('pending_uncertainty_receipt_failures_and_snapshot_' + context, context, seed=seed_pending)
    s.barrier().packet(64, 16, row()).packet(64, 2, b'\x01')
    for sub in (6, 7, 8):
        s.packet(64, sub, pack('BH', 255, 65535)).barrier().packet(64, 2, b'\x01')
    s.packet(64, 4, pack('BH', 1, 1)).packet(64, 1, row() + b'\x01').barrier().reset().finish()

for field, value in [('pending', 'add'), ('pending', ''), ('uncertain', True), ('active', 255), ('ready', True)]:
    s = Scenario('barrier_guard_' + field + '_' + str(value), seed=lambda state, f=field, v=value: state.crafting.update({f: v}))
    s.barrier().barrier().packet(64, 16, row(255)).barrier().finish()

for role in (100, 0, 0xffffffff, None):
    s = Scenario('furniture_ownership_' + str(role), role=role)
    # Before a room snapshot, null == missing role follows the retained source exactly.
    s.packet(62, 1, b'\x01' + furniture()).packet(62, 76, pack('H', 7))
    s.packet(62, 4, pack('I', 200) + furniture(8)).packet(62, 1, b'\x01' + furniture(9))
    s.packet(62, 1, b'\x02' + furniture(3)).barrier().barrier()
    s.packet(62, 5, pack('BHHH', 2, 3, 100, 55)).packet(62, 5, pack('BHHH', 1, 4, 100, 55))
    if role is not None:
        s.packet(62, 4, pack('I', role) + furniture(1) + furniture(1, 65535) + furniture(7))
    s.packet(62, 5, pack('BHHH', 1, 7, 42, 65535)).packet(62, 76, pack('H', 7))
    s.packet(62, 76, pack('H', 65535)).packet(62, 5, pack('BHHH', 255, 7, 42, 0))
    s.packet(62, 2, pack('H', 1)).packet(62, 4, pack('I', 200)).barrier().finish()

s = Scenario('apply_direct_last_duplicate_wins_and_future_type')
r = {'index': 1, 'item_id': 42, 'elapsed': 1.25, 'count': 2, 'base_time': 10}
s.direct({'type': 'craft_snapshot', 'rows': [r, {**r, 'item_id': 65535}], 'active': 1})
s.direct({'type': 'craft_future_notice'}).direct({'type': 'bag_add'}).direct({'type': 'connection_closed'})
s.direct({'type': 'craft_completed', 'index': 1}).direct({'type': 'craft_completed', 'index': 1}).finish()

for context in CONTEXTS:
    for main, sub, payload in [(64, 1, row() + row(2, 1) + b'\x01'), (64, 16, row()),
                               (64, 2, b'\x01'), (64, 3, b'\x01'), (64, 4, pack('BH', 1, 99)),
                               (64, 5, b'\x01'), (64, 6, pack('BH', 1, 99)), (64, 7, pack('BH', 1, 99)),
                               (64, 8, pack('BH', 1, 99)), (64, 10, pack('BI', 1, 99)), (64, 25, b'\x01\x01\x02'),
                               (62, 4, pack('I', 100) + furniture()), (62, 1, b'\x02' + furniture()),
                               (62, 2, pack('H', 7)), (62, 76, pack('H', 7)), (62, 5, pack('BHHH', 1, 7, 42, 0))]:
        s = Scenario(f'malformed_prefix_tail_{context}_{main}_{sub}', context)
        s.packet(64, 1, row() + b'\x01')
        for length in range(len(payload)): s.packet(main, sub, payload[:length])
        s.packet(main, sub, payload + b'x').packet(main, sub, payload).finish()

for context in CONTEXTS:
    s = Scenario('malformed_duplicates_fields_and_unknown_' + context, context)
    for payload in [row(0), row(identity=0), row(count=0), row(identity=2)]: s.packet(64, 16, payload)
    s.packet(64, 1, row()*2 + b'\x01').packet(64, 255, b'PRIVATE').packet(62, 255, b'PRIVATE')
    s.packet(99, 99, b'PRIVATE').barrier().finish()
    s = Scenario('full_queue_boundary_' + context, context)
    s.packet(64, 1, b''.join(row(index, count=255, elapsed=0xffffffff, base=0xffffffff) for index in range(1, 256)) + b'\xff')
    s.packet(64, 4, pack('BH', 255, 65535)).packet(64, 5, b'\x01').packet(64, 1, b'\x00').finish()

for number in range(80):
    s = Scenario('mixed_' + str(number), RNG.choice(list(CONTEXTS)), role=RNG.choice([100, 0, None]))
    for _ in range(55):
        op, index, identity = RNG.randrange(19), RNG.choice([0, 1, 2, 3, 255]), RNG.choice([0, 1, 2, 42, 65535])
        at = RNG.choice([0, 1.25, 1000.5, 1000000])
        if op == 0: s.packet(64, 1, row(index, identity) + bytes([index]), at)
        elif op == 1: s.packet(64, 16, row(index, identity), at)
        elif op in (2, 3, 5): s.packet(64, op, bytes([index]), at)
        elif op in (4, 6, 7, 8): s.packet(64, op, pack('BH', index, 65535), at)
        elif op == 9: s.packet(64, 25, bytes([1, index, RNG.choice([0, 1, 2, 255])]), at)
        elif op == 10: s.packet(64, 10, pack('BI', index, RNG.randrange(2**32)), at)
        elif op == 11: s.packet(62, 4, pack('I', RNG.choice([0, 100, 200])) + furniture(index, identity), at)
        elif op == 12: s.packet(62, 1, bytes([RNG.choice([0, 1, 2, 255])]) + furniture(index, identity), at)
        elif op == 13: s.packet(62, 5, pack('BHHH', RNG.choice([0, 1, 2, 255]), index, identity, 42), at)
        elif op == 14: s.packet(62, RNG.choice([2, 76]), pack('H', index), at)
        elif op == 15: s.barrier()
        elif op == 16: s.reset()
        elif op == 17: s.packet(64, 1, b'\x00', at)
        else: s.packet(64, 255, b'PRIVATE', at)
    s.finish()

sources = ['wlre/services/items/crafting.py', 'wlre/services/items/crafting_official_v1286.py', 'wlre/network/wire.py']
provenance = {path: hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for path in sources}
lines = ['// Generated by generate_crafting_state_vectors.py. Retained Python; synthetic offline data only.',
         'namespace Lala.Core.Tests.Inventory;', 'public static class CraftingStatePythonVectors', '{',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
         '    public static IEnumerable<object[]> Sequences()', '    {']
for scenario in scenarios:
    data = json.dumps(scenario, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    encoded = base64.b64encode(gzip.compress(data, mtime=0)).decode('ascii')
    lines.append('        yield return new object[] { ' + json.dumps(scenario['name']) + ', Decode(' + json.dumps(encoded) + ') };')
lines += ['    }', '    private static string Decode(string encoded)', '    {',
          '        using var input = new System.IO.MemoryStream(System.Convert.FromBase64String(encoded));',
          '        using var gzip = new System.IO.Compression.GZipStream(input, System.IO.Compression.CompressionMode.Decompress);',
          '        using var reader = new System.IO.StreamReader(gzip, System.Text.Encoding.UTF8);',
          '        return reader.ReadToEnd();', '    }', '}']
output = Path(__file__).with_name('CraftingStatePythonVectors.cs')
output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
assert output.stat().st_size < 500_000
print(f'{len(scenarios)} sequences; {sum(len(s["steps"]) for s in scenarios)} snapshots; {output.stat().st_size} bytes')
