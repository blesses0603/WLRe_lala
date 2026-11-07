"""Generate offline synthetic receive-state parity from the real retained Python.

Uses State defaults, apply_guild and dispatch_local in State.apply's original order;
only guild/player output is projected. Other service observers, guild_actions state,
commands, sends, runtime catalogs, account/session lifecycle and live game are excluded.
Decoded rank/chief omissions and unchanged guild on role changes are source behavior,
not evidence of current membership or permission to send. Run from repository root:
python dotnet/Lala.Core.Tests/Social/GuildEventGenerateVectors.py
"""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import sys

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.core.state import State
from wlre.core.state_events import dispatch_local
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.social.guild import apply_guild


def pack(fmt, *values):
    return struct.pack('<' + fmt, *values)


def text(value):
    raw = value.encode('utf-16le')
    return pack('B', len(raw)) + raw


def profile(name, equipment=0, skipped=0):
    return (text(name) + bytes([skipped]) * 15 + pack('B', equipment) +
            bytes([skipped]) * (equipment * 6 + 8) + text('unused signature') + bytes(8))


def roster(members, name='Fixture 組織😀', serial=72, level=1, rank=0):
    raw = text(name) + text('unused chief') + pack('B', len(members))
    for index, (rid, member_name) in enumerate(members):
        raw += pack('I', rid) + profile(member_name, index % 3, rank) + bytes([rank]) * 13
    return raw + text('unused rules') + bytes(2) + pack('B', level) + bytes(37) + pack('I', serial)


def world(role):
    return (pack('IBHHHBBBIIBBB', role, 0, 10001, 1, 2, 0, 0, 0, 0, 0, 0, 0, 0) +
            text('Fixture player') + bytes(8) + text('unused card') + pack('H', 0))


scenarios = []


class Scenario:
    def __init__(self, name):
        self.name, self.state, self.steps = name, State(), []
        self.record(None)

    def record(self, message, error=None):
        state = self.state.snapshot()
        step = dict(message=message, own_role_id=state['player'].get('role_id'), expected=state['guild'])
        if error is not None:
            step['error'] = error
        self.steps.append(step)

    def packet(self, main, sub, payload=b''):
        message = dict(main=main, sub=sub, hex=payload.hex().upper())
        try:
            event = decode(Packet(main, sub, payload), self.state.player.get('role_id'))
        except ProtocolError as exc:
            self.record(message, str(exc))
            return
        apply_guild(self.state, event)
        dispatch_local(self.state, event, affects_navigation=lambda *_: False)
        self.record(message)

    def roster(self, members=(), **kwargs):
        self.packet(39, 2, roster(members, **kwargs))

    def member(self, sub, role, name='Fixture 成員😀', **kwargs):
        self.packet(39, sub, pack('I', role) + (profile(name, **kwargs) if sub == 60 else b''))

    def leave(self, result, role):
        self.packet(39, 7, pack('BI', result, role))

    def disband(self, result):
        self.packet(39, 10, pack('B', result))

    def world(self, role):
        self.packet(3, 1, world(role))

    def finish(self):
        scenarios.append(dict(name=self.name, steps=self.steps))


s = Scenario('defaults-and-early-events-never-buffered')
s.member(60, 1); s.member(8, 1); s.member(6, 1); s.leave(0, 0); s.disband(1)
s.roster([(1, 'first')]); s.member(60, 2, 'early profile'); s.member(8, 2)
s.member(60, 2, 'named'); s.member(8, 2); s.member(6, 1); s.member(6, 1); s.finish()

s = Scenario('snapshot-replaces-members-and-metadata-even-empty-zero')
s.roster([(1, 'one'), (2, 'two')], serial=0xffffffff, level=255)
s.member(8, 3); s.member(60, 1, 'renamed')
s.roster([(4, 'four')], name='', serial=0, level=0)
s.member(8, 0); s.member(60, 0, 'zero incremental id'); s.member(6, 0)
s.roster(); s.member(8, 0xffffffff); s.member(60, 0xffffffff, '\0Ω星😀\0'); s.roster(); s.finish()

s = Scenario('self-removal-keeps-ready-but-self-leave-clears')
s.world(1); s.roster([(1, 'self'), (2, 'other')]); s.member(6, 1)
s.member(60, 1); s.member(8, 1); s.leave(1, 1); s.leave(255, 1)
s.leave(0, 2); s.leave(0, 0); s.leave(0, 1)
s.member(60, 2); s.member(8, 2); s.member(6, 2); s.leave(0, 1); s.finish()

s = Scenario('disband-results-and-repeated-late-rosters')
s.roster([(1, 'old')]); s.disband(1); s.disband(2); s.disband(255); s.disband(0)
s.member(8, 1); s.member(60, 1); s.roster([(2, 'late roster')]); s.member(8, 1)
s.disband(0); s.disband(0); s.roster([(3, 'later roster')]); s.finish()

s = Scenario('world-role-switch-and-role-list-retain-stale-guild')
s.roster([(1, 'one')]); s.world(1); s.member(60, 1, 'retained after first role')
s.packet(63, 1); s.member(8, 2); s.world(2); s.leave(0, 1)
s.member(60, 1, 'late old-role profile'); s.packet(63, 1); s.leave(0, 2)
s.roster([(1, 'late roster')]); s.world(0); s.leave(0, 0); s.finish()

s = Scenario('all-result-bytes-match-source')
s.world(42)
for result in range(256):
    s.roster([(42, 'self'), (7, 'other')]); s.leave(result, 42); s.disband(result)
s.finish()

s = Scenario('rank-profile-extras-and-chief-not-retained')
for rank in (0, 1, 2, 3, 127, 255):
    s.roster([(1, 'same member')], rank=rank)
    s.member(60, 1, 'same member', equipment=rank, skipped=rank)
s.finish()

s = Scenario('decoder-errors-never-publish-partial-guild-state')
s.roster([(1, 'keep')])
for payload in (roster([(0, 'invalid')]), roster([(1, 'one'), (1, 'duplicate')]),
                roster([(2, 'bad tail')]) + b'\x00', roster([(2, 'truncated')])[:-1]):
    s.packet(39, 2, payload)
for sub, payload in ((60, pack('I', 1) + profile('bad')), (6, pack('I', 1)),
                     (8, pack('I', 1)), (7, pack('BI', 0, 1)), (10, b'\0')):
    s.packet(39, sub, payload[:-1]); s.packet(39, sub, payload + b'\xff')
s.finish()

s = Scenario('unrelated-events-and-actions-are-noops')
s.world(1); s.roster([(1, 'keep')])
for main, sub, payload in ((39, 85, b'\x01'), (39, 86, b'\0'), (39, 87, b'\x03\x01'),
                            (39, 15, b'\x05'), (10, 5, b'\x00'), (10, 5, b'\x01\x01\x01'),
                            (10, 5, b'\x02\x02\x01\x02'), (10, 5, b'\x03'),
                            (13, 4, pack('I', 1)), (2, 13, b'\0'), (255, 255, b'\xff')):
    s.packet(main, sub, payload)
s.finish()

s = Scenario('maximum-roster-and-unicode-boundaries')
s.roster([(i, '界' * 127 if i == 1 else 'member-' + str(i)) for i in range(1, 256)])
s.member(60, 255, 'A\0B\0\0'); s.member(6, 1); s.member(8, 1); s.member(60, 1, '')
s.roster([(0xffffffff, 'last'), (0x80000000, 'high'), (1, 'first')]); s.finish()

for seed in range(16):
    rng = random.Random(793900 + seed)
    s = Scenario('seeded-mixed-' + str(seed))
    for step in range(80):
        op, role = rng.randrange(10), rng.choice([0, 1, 2, 42, 0x80000000, 0xffffffff])
        if op == 0:
            ids = rng.sample([1, 2, 42, 0x80000000, 0xffffffff], rng.randrange(6))
            s.roster([(rid, f'member-{rid}-{step}') for rid in ids], serial=rng.choice([0, 1, 72, 0xffffffff]),
                     level=rng.randrange(256), name=f'guild-{step}')
        elif op == 1: s.member(8, role)
        elif op == 2: s.member(6, role)
        elif op == 3: s.member(60, role, rng.choice(['', '星😀', 'A\0B\0', 'renamed']))
        elif op == 4: s.leave(rng.choice([0, 0, 1, 2, 255]), role)
        elif op == 5: s.disband(rng.choice([0, 1, 2, 255]))
        elif op == 6: s.world(role)
        elif op == 7: s.packet(63, 1)
        elif op == 8: s.packet(39, 85, pack('B', rng.randrange(4)))
        else: s.packet(39, 255, b'\xff')
    s.finish()

sources = ['wlre/services/social/guild.py', 'wlre/core/state.py', 'wlre/core/state_events.py',
           'wlre/core/state_session_events.py', 'wlre/core/state_world_events.py', 'wlre/network/protocol.py',
           'wlre/network/layouts.py', 'wlre/network/wire.py', 'wlre/services/social/guild_actions.py']
provenance = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sources}
lines = ['// Generated by GuildEventGenerateVectors.py from retained Python; synthetic offline data only.',
         'namespace Lala.Core.Tests.Social;', 'public static class GuildEventPythonVectors', '{',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
         f'    public const int SnapshotCount = {sum(len(s["steps"]) for s in scenarios)};',
         '    public static IEnumerable<object[]> Sequences()', '    {']
for scenario in scenarios:
    data = json.dumps(scenario['steps'], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    encoded = base64.b64encode(gzip.compress(data, mtime=0)).decode('ascii')
    lines.append('        yield return new object[] { ' + json.dumps(scenario['name']) + ', Decode(' + json.dumps(encoded) + ') };')
lines += ['    }', '    private static string Decode(string encoded)', '    {',
          '        using var input = new System.IO.MemoryStream(System.Convert.FromBase64String(encoded));',
          '        using var gzip = new System.IO.Compression.GZipStream(input, System.IO.Compression.CompressionMode.Decompress);',
          '        using var reader = new System.IO.StreamReader(gzip, System.Text.Encoding.UTF8);',
          '        return reader.ReadToEnd();', '    }', '}']
output = Path(__file__).with_name('GuildEventPythonVectors.cs')
output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
assert output.stat().st_size < 500_000
print(f'{len(scenarios)} sequences, {sum(len(s["steps"]) for s in scenarios)} snapshots; {output.stat().st_size} bytes')
