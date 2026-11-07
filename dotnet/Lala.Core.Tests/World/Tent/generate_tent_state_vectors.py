"""Deterministic synthetic offline oracle for tent.defaults/apply_tent.

Runs retained receive functions, including apply_world_event before apply_tent, as in
state.py. Only current_runtime is injected with synthetic stage identity evidence.
No command, timeout, exit lookup, service observer, catalog activation or send is run.
Run from repository root. Deterministic gzip fixtures stay below 500 KB.
"""
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
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from wlre.core.state import State
from wlre.core.state_world_events import apply_world_event
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.world import tent

RNG = random.Random(651126)
SCENARIOS = []
CONTEXTS = {
    'absent': None,
    'empty': {'stage_ids': [], 'verified_instance_alias_ids': [61501]},
    'known': {'stage_ids': [100, 101, 61501, 63501, 65535, 10000], 'verified_instance_alias_ids': []},
}


def p(fmt, *values): return struct.pack('<' + fmt, *values)
def camp(owner=17, tent_id=42, x=0xffffffff, y=0, kind=255, make=0):
    return p('IH IIBB', owner, tent_id, x, y, kind, make)
def world(role=17, scene=100):
    return p('IBHHHBBB IIBB', role, 0, scene, 0, 65535, 0, 0, 0, 0, 0, 0, 0) + bytes(11) + p('H', 0)
def furniture(index=1):
    return p('HHHHHBH', index, 39053, 0, 0, 0, 0, 0) + bytes(31)
def pending(action='enter', **more): return dict(action=action, due=123.25, **more)
def entry(action='enter', source=100, received=False):
    return dict(action=action, source_scene=source, furniture_received=received)
def populated(**more):
    return dict(scene=100, scene_known=True, visible=True, deployed_scene=100, tent_id=42,
                x=123, y=456, kind=7, make=8, access_open=True, return_scene=99,
                status='合成保留狀態', **more)


class Scenario:
    def __init__(self, name, role=17, scene=100, context='absent', seed=None):
        self.name, self.context = name, context
        player = {'scene': scene} if scene is not None else {}
        if role is not None: player['role_id'] = role
        self.state = State(player=player)
        if seed: self.state.tent.update(copy.deepcopy(seed))
        self.steps = []
        self.record(None)

    def record(self, operation, error=None):
        self.steps.append(dict(operation=operation, error=error,
                               role=self.state.player.get('role_id'), scene=self.state.player.get('scene'),
                               expected=copy.deepcopy(self.state.tent)))

    def apply(self, event):
        catalog = CONTEXTS[self.context]
        runtime = None if catalog is None else SimpleNamespace(stages=dict.fromkeys(catalog['stage_ids']))
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime', return_value=runtime):
            apply_world_event(self.state, event, lambda *_: False)
            tent.apply_tent(self.state, event)

    def packet(self, main, sub, data=b''):
        operation = dict(main=main, sub=sub, hex=data.hex())
        try:
            self.apply(decode(Packet(main, sub, data)))
            self.record(operation)
        except ProtocolError as exc:
            self.record(operation, str(exc))
        return self

    def direct(self, event):
        self.apply(copy.deepcopy(event)); self.record({'direct': event}); return self

    def position(self, scene, role=None, main=12):
        role = self.state.player.get('role_id', 17) if role is None else role
        return self.packet(main, 1, p('IHHH', role, scene, 0, 65535))

    def room(self, owner=17, rows=b''):
        return self.packet(62, 4, p('I', owner) + rows)

    def finish(self):
        SCENARIOS.append(dict(name=self.name, catalog=CONTEXTS[self.context], steps=self.steps))


for role in (17, 0, 0xffffffff, None):
    own = role if role is not None else 17
    other = 18 if own != 18 else 19
    s = Scenario('ownership_first_duplicate_list_visibility_' + str(role), role=role)
    s.packet(65, 1, camp(other)).packet(65, 4, p('I', other)).packet(65, 3)
    s.packet(65, 3, camp(other) + camp(own, 1) + camp(own, 2)).packet(65, 1, camp(own, 3))
    s.position(101, own).packet(65, 3).packet(65, 5).packet(65, 4, p('I', own))
    s.packet(65, 4, p('I', own)).packet(65, 3, camp(other)).packet(65, 18, b'\x01\x02')
    s.packet(65, 7, b'\0\xff').packet(65, 7, b'\xff\0').finish()

for scene in (None, 0, 100, 65535):
    s = Scenario('camp_observation_uses_current_nullable_scene_' + str(scene), scene=scene)
    s.packet(65, 1, camp()).packet(65, 3).packet(65, 3, camp()).finish()

for action in ('open', 'close', 'enter', 'leave', '', 'future'):
    for signal in (2, 5, 8, 16):
        s = Scenario(f'pending_signal_{action}_{signal}', seed=populated(
            pending=pending(action), uncertain=True, entry_context=entry()))
        s.packet(65, signal, b'\x02' if signal == 16 else b'')
        s.packet(65, signal, b'\xff' if signal == 16 else b'').packet(65, 3).packet(65, 1, camp()).finish()
    s = Scenario('pending_visible_' + action, seed=populated(
        pending=pending(action), uncertain=True, entry_context=entry()))
    s.packet(65, 1, camp(18)).packet(65, 1, camp()).packet(65, 3, camp()).packet(65, 4, p('I', 17)).finish()
    s = Scenario('pending_event_rejection_' + action, seed=populated(
        pending=pending(action), uncertain=True, entry_context=entry()))
    s.packet(20, 74, b'\x02').packet(20, 74, b'\xff').packet(65, 16, b'\x03').finish()

for code in (0, 1, 2, 3, 255):
    s = Scenario('pending_error_code_' + str(code), seed=populated(
        pending=pending(), uncertain=True, entry_context=entry()))
    s.packet(65, 16, bytes([code])).packet(65, 16, bytes([code])).finish()

for context in CONTEXTS:
    for scene in (0, 100, 101, 10000, 10298, 10299, 61501, 63501, 65535):
        for order in ('furniture_first', 'position_first'):
            s = Scenario(f'entry_{context}_{scene}_{order}', context=context,
                         seed=populated(pending=pending(), uncertain=True, entry_context=entry()))
            s.room(18).position(scene, role=18)
            if order == 'furniture_first': s.room(rows=furniture()).position(scene)
            else: s.position(scene).room()
            s.room().position(scene).packet(65, 5).position(100).position(100).finish()
    s = Scenario('late_furniture_after_timeout_evidence_' + context, context=context,
                 seed=populated(uncertain=True, entry_context=entry()))
    s.packet(65, 8).packet(65, 16, b'\x02').position(63501).room().position(10299).finish()
    s = Scenario('pending_fallback_confirmation_' + context, context=context,
                 seed=populated(pending=pending(source_scene=100, furniture_received=True), uncertain=True))
    s.room().position(63501).position(10299).finish()
    s = Scenario('entry_context_precedes_pending_' + context, context=context, seed=populated(
        pending=pending(source_scene=100, furniture_received=True), entry_context=entry('future', received=True)))
    s.position(10299).room().position(100).finish()
    s = Scenario('inside_floor_return_and_unrelated_transition_' + context, context=context, seed=populated(
        inside=True, interior_scene=10000, pending=pending('leave'), uncertain=True))
    s.position(10299).position(63501).position(101).position(99).packet(65, 4, p('I', 17)).finish()
    s = Scenario('inside_return_precedes_private_classification_' + context, context=context, seed=populated(
        inside=True, interior_scene=10000, pending=pending('leave'), uncertain=True))
    s.position(99).finish()

for role in (17, 0, None):
    s = Scenario('role_world_reset_' + str(role), role=role, seed=populated(
        inside=True, interior_scene=10299, pending=pending('enter'), uncertain=True, entry_context=entry()))
    s.packet(63, 1).packet(1, 11).packet(1, 23).packet(65, 5)
    s.packet(3, 1, world(0xffffffff, 65535)).packet(65, 1, camp(17))
    s.packet(65, 3, camp(0xffffffff)).packet(3, 1, world()).packet(3, 1, world()).finish()

s = Scenario('same_scene_never_runs_entry_confirmation', seed=populated(
    pending=pending(source_scene=99, furniture_received=True), uncertain=True))
s.position(100).position(100, main=7).position(10299).finish()
s = Scenario('same_scene_furniture_can_confirm', scene=10299, seed=dict(
    scene=10299, pending=pending(), uncertain=True, entry_context=entry()))
s.position(10299).room().room().finish()
s = Scenario('removed_preserves_access_appearance_return_and_scene', seed=populated(
    inside=True, interior_scene=10299, pending=pending(), uncertain=True, entry_context=entry()))
s.packet(65, 4, p('I', 17)).packet(65, 16, b'\x02').packet(65, 3).finish()

for main, sub, payload in [(65, 1, camp()), (65, 3, camp(18) + camp()), (65, 4, p('I', 17)),
                           (65, 7, b'\0\xff'), (65, 16, b'\x02'), (65, 18, b'\xff\0'),
                           (62, 4, p('I', 17) + furniture()), (12, 1, p('IHHH', 17, 10299, 0, 0)),
                           (3, 1, world())]:
    s = Scenario(f'malformed_prefix_tail_{main}_{sub}', seed=populated(
        pending=pending(), uncertain=True, entry_context=entry()))
    for length in range(len(payload)): s.packet(main, sub, payload[:length])
    s.packet(main, sub, payload + b'x').packet(main, sub, payload).finish()

s = Scenario('opaque_signals_unknown_and_unrelated', seed=populated(
    pending=pending(), uncertain=True, entry_context=entry()))
for sub in (2, 5, 8): s.packet(65, sub, b'x').packet(65, sub, bytes(65536))
for sub in (0, 6, 9, 255): s.packet(65, sub, b'SYNTHETIC')
for name in ('tent_future_notice', 'connection_closed', 'role_list_available', 'world_changed'):
    s.direct({'type': name})
s.packet(1, 11).packet(255, 255).finish()

for count in (0, 1, 255, 256, 4095, 4096, 8192):
    s = Scenario('uncapped_aligned_camp_count_' + str(count))
    s.packet(65, 3, camp(18) * count + camp(17, 65535) + camp(17, 1))
    s.packet(65, 3, camp(18) * count).finish()

for number in range(80):
    role = RNG.choice([17, 0, 0xffffffff, None])
    action = RNG.choice(['open', 'close', 'enter', 'leave'])
    s = Scenario('mixed_' + str(number), role=role, context=RNG.choice(list(CONTEXTS)),
                 seed=populated(pending=pending(action), uncertain=bool(number % 2),
                                entry_context=entry(received=bool(number % 3))))
    for _ in range(55):
        op = RNG.randrange(15)
        who = RNG.choice([17, 18, 0, 0xffffffff])
        scene = RNG.choice([0, 99, 100, 101, 10299, 61501, 63501, 65535])
        if op == 0: s.packet(65, 1, camp(who, RNG.randrange(65536)))
        elif op == 1: s.packet(65, 3, b''.join(camp(RNG.choice([17, 18, 0, 0xffffffff]), i) for i in range(RNG.randrange(8))))
        elif op == 2: s.packet(65, 4, p('I', who))
        elif op == 3: s.packet(65, RNG.choice([2, 5, 8]), RNG.choice([b'', b'x']))
        elif op == 4: s.packet(65, 16, bytes([RNG.randrange(256)]))
        elif op == 5: s.packet(65, 7, bytes([RNG.choice([0, 1, 255]), RNG.choice([0, 1, 255])]))
        elif op == 6: s.packet(65, 18, bytes([RNG.randrange(256), RNG.randrange(256)]))
        elif op == 7: s.position(scene, who, RNG.choice([7, 12]))
        elif op == 8: s.room(who)
        elif op == 9: s.packet(3, 1, world(who, scene))
        elif op == 10: s.packet(20, 74, bytes([RNG.randrange(256)]))
        elif op == 11: s.packet(1, 11)
        elif op == 12: s.packet(65, 3)
        elif op == 13: s.packet(65, 255, b'SYNTHETIC')
        else: s.packet(65, 1, camp(who)[:-1])
    s.finish()

sources = ['wlre/services/world/tent.py', 'wlre/network/wire.py', 'wlre/network/protocol.py',
           'wlre/network/layouts.py', 'wlre/core/state_world_events.py', 'wlre/services/world/house_navigation.py',
           'wlre/services/items/crafting.py', 'wlre/services/items/crafting_official_v1286.py']
provenance = {path: hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for path in sources}
data = json.dumps(SCENARIOS, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
compressed = gzip.compress(data, mtime=0)
lines = ['// Generated by generate_tent_state_vectors.py. Retained Python; synthetic offline data only.',
         '// Numeric byte data avoids the shared test assembly user-string heap limit.',
         'namespace Lala.Core.Tests.World.Tent;', 'public static class TentStatePythonVectors', '{',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
         '    public static IEnumerable<object[]> Sequences()', '    {',
         '        using var input = new System.IO.MemoryStream(CompressedData.ToArray());',
         '        using var gzip = new System.IO.Compression.GZipStream(input, System.IO.Compression.CompressionMode.Decompress);',
         '        using var document = System.Text.Json.JsonDocument.Parse(gzip);',
         '        foreach (var scenario in document.RootElement.EnumerateArray())',
         '            yield return new object[] { scenario.GetProperty("name").GetString()!, scenario.GetRawText() };',
         '    }', '    private static ReadOnlySpan<byte> CompressedData =>', '    [']
for offset in range(0, len(compressed), 100):
    lines.append('        ' + ','.join(str(value) for value in compressed[offset:offset+100]) + ',')
lines += ['    ];', '}']
output = Path(__file__).with_name('TentStatePythonVectors.cs')
output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
assert output.stat().st_size < 500_000
print(f'{len(SCENARIOS)} sequences; {sum(len(s["steps"]) for s in SCENARIOS)} snapshots; {output.stat().st_size} bytes ({len(compressed)} compressed)')
