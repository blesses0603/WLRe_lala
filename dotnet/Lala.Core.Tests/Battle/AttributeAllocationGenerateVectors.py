"""Receive-only allocation oracle using the retained, complete State.apply path.

Pending evidence is imported; begin/allocation/expire and command senders are never called.
The wrapper records exactly what apply_points_event sees after apply_live and before
local attribute dispatch. The C# slice consumes that explicit knowledge context, not a
second hand-written model of player knowledge. All values and packets are synthetic.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import sys
from unittest.mock import patch

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'TestSupport'))
from gzip_json_fixture import csharp_gzip_json
import wlre.core.state as state_module
from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.battle.attribute_points import apply_event, defaults
from wlre.services.items.live_combat_catalog import _pinned

CATALOG = dict(items={}, skills={}, keys={}, npcs={}, characters=[], element_weights={})
STATS = dict(str=20, con=30, int=40, wis=50, agi=60, attribute_potential=20)
KINDS = dict(str=28, con=29, int=27, wis=33, agi=30, attribute_potential=38)
scenarios = []


def p(fmt, *values): return struct.pack('<' + fmt, *values)


def attr(value, kind=28, sub=1, sign=None, parameter=0, entity=0xffffffff, human=4):
    prefix = b'' if sub == 1 else p('BH', human, 65535) if sub == 2 else p('I', entity)
    return 8, sub, prefix + p('BBII', kind, sign if sign is not None else 2 if value < 0 else 1, abs(value), parameter)


def combat(stats=None, wide=False):
    stats = stats if stats is not None else STATS
    word, dword, byte = (65535, 0xffffffff, 255) if wide else (3, 4, 1)
    data = (p('BIH5HBI2HIH6I', byte, dword, word, stats['str'], stats['con'], stats['int'],
              stats['wis'], stats['agi'], byte, dword, word, stats['attribute_potential'],
              dword, word, *([dword] * 6)) + bytes(12) + p('H', 0) + p('HHBBB', word, word, byte, byte, byte))
    return 5, 3, data


class Scenario:
    def __init__(self, name):
        self.name, self.state, self.steps = name, State(), []
        assert self.state.snapshot()['attribute_allocation'] == defaults()
        self.record()

    def record(self, **values):
        values['expected'] = self.state.snapshot()['attribute_allocation']
        self.steps.append(copy.deepcopy(values))

    def seed(self, expected, *, stats=None, pending=True, acknowledged=False, uncertain=False, sent_at=1.25, status='imported pending'):
        info = dict(pending=pending, acknowledged=acknowledged, uncertain=uncertain,
                    expected=expected, sent_at=sent_at, status=status)
        self.state.attribute_allocation = copy.deepcopy(info)
        self.state.knowledge['player']['stats'] = copy.deepcopy(STATS if stats is None else stats)
        self.record(seed=info)

    def packet(self, main=8, sub=4, payload=b''):
        message = dict(main=main, sub=sub, hex=payload.hex().upper())
        try:
            event = decode(Packet(main, sub, payload))
        except ProtocolError as exc:
            self.record(message=message, error=str(exc))
            return
        before = self.state.snapshot()
        capture = {}

        def observe(state, event):
            at_observer = state.snapshot()
            capture.update(current_stats=at_observer['knowledge']['player']['stats'],
                           player_ready=at_observer['knowledge']['player']['ready'],
                           attributes_at_observer=at_observer['attributes'])
            # The real source order must retain the pre-dispatch S8 buffer, even though
            # apply_live has already replaced the matching knowledge statistic.
            assert at_observer['attributes'] == before['attributes']
            apply_event(state, event)

        token = _pinned.set(CATALOG)
        try:
            with patch.object(state_module, 'apply_points_event', observe):
                self.state.apply(event)
        finally:
            _pinned.reset(token)
        assert capture
        self.record(message=message, stats_before=before['knowledge']['player']['stats'],
                    attributes_after=self.state.snapshot()['attributes'], **capture)

    def finish(self): scenarios.append(dict(name=self.name, steps=self.steps))


s = Scenario('defaults-ignore-receipts-and-no-receive-created-pending')
s.packet(); s.packet(*attr(22)); s.packet(*combat()); s.packet(); s.finish()

for ack_first in (False, True):
    s = Scenario('ack-first' if ack_first else 'stats-first')
    expected = dict(STATS, str=22, attribute_potential=18)
    s.seed(expected)
    if ack_first: s.packet(); s.packet()  # duplicates while still waiting
    s.packet(*attr(22)); s.packet(*attr(22)); s.packet(*attr(18, 38))
    if not ack_first: s.packet()
    s.packet(); s.packet(*attr(20)); s.finish()  # late old values never reopen pending

s = Scenario('same-packet-knowledge-new-local-attributes-old')
s.packet(*attr(20)); s.seed({'str': 22}); s.packet(); s.packet(*attr(22)); s.finish()
assert s.steps[-1]['stats_before']['str'] == 20
assert s.steps[-1]['current_stats']['str'] == 22
assert s.steps[-1]['attributes_at_observer']['self']['28:0'] == 20
assert s.steps[-1]['attributes_after']['self']['28:0'] == 22
assert not s.steps[-1]['expected']['pending']

s = Scenario('matching-combat-snapshot-is-not-ack')
s.seed(dict(STATS, str=22)); s.packet(*combat(dict(STATS, str=22))); s.packet(); s.finish()
s = Scenario('ack-then-combat-snapshot-completes')
s.seed(dict(STATS, str=22)); s.packet(); s.packet(*combat(dict(STATS, str=22))); s.finish()

for expected in (None, {}):
    s = Scenario('null-expected' if expected is None else 'empty-expected')
    s.seed(expected, stats={}); s.packet(*attr(0)); s.packet(); s.packet(); s.finish()

s = Scenario('unknown-missing-zero-extras-and-case-sensitive-keys')
s.seed({'str': 22, 'unknown': 0}); s.packet(); s.packet(*attr(22))
s.seed({'STR': 22}, stats={'str': 22}, acknowledged=True); s.packet(*attr(22))
s.seed({'str': 22}, stats={'str': 22, 'extra': 987}, acknowledged=True); s.packet(*attr(99, 255)); s.finish()

s = Scenario('any-attribute-entity-or-kind-can-trigger-current-comparison')
for sub, human, kind in [(2, 4, 28), (2, 1, 110), (3, 4, 255), (1, 4, 255)]:
    s.seed({'str': 22}, stats={'str': 22}, acknowledged=True)
    s.packet(*attr(999, kind, sub, human=human, parameter=0xffffffff))
s.finish()

s = Scenario('event-values-do-not-stand-in-for-current-context')
for sub in (2, 3):
    s.seed({'str': 22}, stats={'str': 20}, acknowledged=True)
    s.packet(*attr(22, sub=sub)); s.packet(); s.packet(*attr(22))
s.finish()

s = Scenario('uncertain-latch-closed-idle-and-imported-pending')
s.seed({'str': 22}, pending=False, uncertain=True, acknowledged=True)
s.packet(); s.packet(*attr(22)); s.packet(*combat(dict(STATS, str=22)))
s.seed({'str': 22}, stats={'str': 22}, pending=True, uncertain=True); s.packet(); s.finish()

s = Scenario('irrelevant-receipts-do-not-resolve-even-when-current-matches')
s.seed({'str': 22}, stats={'str': 22}, acknowledged=True)
s.packet(5, 47, p('BBq', 255, 255, 0x7fffffffffffffff))  # live, not player_combat_data
s.packet(52, 1, p('H', 65535)); s.packet(254, 254, b'\x00\xff'); s.packet(); s.finish()

s = Scenario('signed-uint32-and-unbounded-imported-numeric-values')
for value in (0, 1, 0x7fffffff, 0x80000000, 0xffffffff, -1, -0x80000000, -0xffffffff):
    s.seed({'str': value}, stats={}, acknowledged=True); s.packet(*attr(value))
for sign in (0, 1, 3, 255):
    s.seed({'str': 0xffffffff}, stats={}, acknowledged=True); s.packet(*attr(0xffffffff, sign=sign))
s.seed({'custom': 2**100}, stats={'custom': 2**100}, acknowledged=True); s.packet(*attr(0, 255))
s.seed({'str': 22}, sent_at=None); s.packet(); s.packet(*attr(22)); s.finish()

s = Scenario('wide-s5-values-and-explicit-reset')
wide = {key: 65535 for key in STATS}
s.seed(wide); s.packet(); s.packet(*combat(wide, wide=True))
s.seed(None, pending=False, status='', sent_at=None, stats={}); s.packet(); s.finish()

s = Scenario('malformed-packets-never-partly-ack-or-complete')
s.seed({'str': 22}, acknowledged=True)
for main, sub, payload in [attr(22), attr(22, sub=2), attr(22, sub=3), combat(dict(STATS, str=22)), (8, 4, b'')]:
    for size in range(len(payload)):
        s.packet(main, sub, payload[:size])
    s.packet(main, sub, payload + b'\x00')
s.packet(*attr(22)); s.finish()

rng = random.Random(20261108)
for index in range(64):
    s = Scenario(f'seeded-arrival-order-{index:02}')
    for _ in range(28):
        kind = rng.randrange(9)
        if kind <= 1:
            expected = rng.choice([None, {}, {'str': rng.randrange(4)}, {'str': rng.randrange(4), 'attribute_potential': rng.randrange(4)}])
            s.seed(expected, stats={'str': rng.randrange(4), 'attribute_potential': rng.randrange(4)},
                   acknowledged=bool(rng.randrange(2)), pending=bool(rng.randrange(2)),
                   uncertain=bool(rng.randrange(2)), sent_at=rng.choice([None, 0, -100, 1e100]))
        elif kind <= 3: s.packet()
        elif kind <= 6: s.packet(*attr(rng.randrange(4), rng.choice([28, 38, 255]), rng.choice([1, 2, 3])))
        elif kind == 7: s.packet(*combat(dict(STATS, str=rng.randrange(4), attribute_potential=rng.randrange(4))))
        else: s.packet(52, 1, p('H', rng.randrange(65536)))
    s.finish()

sources = ['wlre/services/battle/attribute_points.py', 'wlre/services/items/combat_resources.py',
           'wlre/services/items/live_combat_catalog.py', 'wlre/core/state.py', 'wlre/core/state_events.py',
           'wlre/core/state_session_events.py', 'wlre/network/protocol.py', 'wlre/network/live_data.py',
           'wlre/network/wire.py']
hashes = {path: hashlib.sha256((ROOT / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for path in sources}
count = sum(len(row['steps']) for row in scenarios)
errors = sum('error' in step for row in scenarios for step in row['steps'])
lines = ['// Generated from retained Python; synthetic offline receive observations only.',
         'namespace Lala.Core.Tests.Battle;', 'public static class AttributeAllocationPythonVectors', '{',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(hashes, separators=(',', ':'))) + ';',
         f'    public const int SnapshotCount = {count};', f'    public const int ErrorCount = {errors};',
         '    public static IEnumerable<object[]> Sequences()', '    {']
for row in scenarios:
    payload = json.dumps(row['steps'], ensure_ascii=False, separators=(',', ':'))
    lines.append('        yield return new object[] { ' + json.dumps(row['name']) + ', ' + csharp_gzip_json(payload) + ' };')
lines += ['    }', '}']
output = Path(__file__).with_name('AttributeAllocationPythonVectors.cs')
output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'{len(scenarios)} sequences, {count} snapshots, {errors} malformed observations; {output.stat().st_size} bytes')
