"""Synthetic offline party receive oracle. Executes retained decode, party_defaults,
apply_party, expire, own_team/player_name and local world dispatch in State.apply order.
No command handler, sender, scheduler, auto-accept or external connection is invoked.
Run from repository root: python dotnet/Lala.Core.Tests/Social/Party/generate_party_vectors.py
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
from unittest.mock import patch

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from wlre.core.state import State
from wlre.core.state_events import dispatch_local
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.battle.party import apply_party, expire, own_team, party_defaults, player_name


def pack(fmt, *values):
    return struct.pack('<' + fmt, *values)


def text(value):
    raw = value.encode('utf-16le')
    return pack('B', len(raw)) + raw


def nearby(role, scene=100, name='Fixture 夥伴😀', equipment=0):
    return (pack('IBBBHHH', role, 2, 3, 4, scene, 5, 6) + bytes(13) + pack('B', equipment)
            + bytes(equipment * 6) + pack('BB', 7, 8) + text(name) + bytes(8) + text('unused card') + bytes(2))


def world(role, name='Fixture 自己😀'):
    return (pack('IBHHHBBBIIBBB', role, 0, 100, 1, 2, 0, 0, 0, 0, 0, 0, 0, 0)
            + text(name) + bytes(8) + text('unused card') + bytes(2))


def team_list(teams):
    return b''.join(pack('IB', leader, len(members)) + b''.join(pack('I', r) for r in members)
                    for leader, members in teams)


scenarios = []
QUERY_IDS = [0, 1, 2, 3, 7, 42, 0x80000000, 0xffffffff]


class Scenario:
    def __init__(self, name):
        self.name, self.state, self.steps, self.now = name, State(), [], 100.0
        assert self.state.snapshot()['party'] == party_defaults()
        self.record()

    def record(self, **operation):
        snapshot = self.state.snapshot()
        step = dict(**operation, now=self.now, own_role_id=snapshot['player'].get('role_id'),
                    own_name=snapshot['player'].get('name'), expected=snapshot['party'],
                    team_order=list(snapshot['party']['teams']), own_team=copy.deepcopy(own_team(snapshot)),
                    names={str(r): player_name(snapshot, r) for r in QUERY_IDS})
        assert own_team(self.state) == own_team(snapshot)
        # Historical expectations must not alias mutable Python lists/dictionaries.
        self.steps.append(json.loads(json.dumps(step)))

    def packet(self, main, sub, payload=b'', at=None):
        self.now = self.now + 0.25 if at is None else at
        message = dict(main=main, sub=sub, hex=payload.hex().upper())
        try:
            event = decode(Packet(main, sub, payload), self.state.player.get('role_id'))
        except ProtocolError as exc:
            self.record(message=message, error=str(exc))
            return
        with patch('wlre.services.battle.party.time.monotonic', return_value=self.now):
            apply_party(self.state, event)
        dispatch_local(self.state, event, affects_navigation=lambda *_: False)
        self.record(message=message)

    def roster(self, *teams): self.packet(13, 6, team_list(teams))
    def join(self, leader, role): self.packet(13, 5, pack('II', leader, role))
    def leave(self, role): self.packet(13, 4, pack('I', role))
    def leader(self, old, new): self.packet(13, 15, pack('BII', 3, new, old))
    def invite(self, role, at=None): self.packet(13, 9, pack('I', role), at=at)
    def application(self, role): self.packet(13, 1, pack('I', role))
    def offer(self, role): self.packet(13, 15, pack('BI', 1, role))
    def world(self, role, name='Fixture 自己😀'): self.packet(3, 1, world(role, name))
    def nearby(self, role, scene=100, name='Fixture 夥伴😀', equipment=0):
        self.packet(4, 1, nearby(role, scene, name, equipment))
    def position(self, role, scene, main=7): self.packet(main, 1, pack('IHHH', role, scene, 65535, 0) + b'\xff')

    def seed(self, enabled=True, sent=None):
        # Caller-supplied pending evidence only, never execute team_command or produce packets.
        pending = {f'invite:{r}': dict(role_id=r, expires=self.now + 15 + i)
                   for i, r in enumerate([0, 1, 2, 42])}
        data = dict(outbound=pending, enabled_requested=enabled)
        self.state.party['outbound'] = copy.deepcopy(pending)
        self.state.party['enabled_requested'] = enabled
        if sent:
            request = dict(key=f'team_invite:{sent}', type='team_invite', role_id=sent,
                           expires=self.now + 15, status='sent')
            self.state.party['requests'][request['key']] = request
            data['sent_request'] = request
        self.record(seed=data)

    def expire(self, at):
        self.now = at
        changed = expire(self.state, at)
        self.record(expire=changed)

    def finish(self): scenarios.append(dict(name=self.name, steps=self.steps))


s = Scenario('defaults-no-ready-early-joins-and-empty-rosters')
s.roster(); s.join(42, 1); s.join(42, 1); s.roster(); s.roster((7, [2]))
s.join(42, 2); s.join(42, 3); s.join(42, 4); s.leave(1); s.leave(2); s.leave(3); s.leave(4)
s.leave(42); s.leave(42); s.join(0, 0); s.join(0, 1); s.leave(0); s.finish()

s = Scenario('roster-merges-order-overwrites-and-first-own-team')
s.world(42); s.roster((7, [42]), (1, [42, 2])); s.roster((7, [2]), (3, [42]))
s.roster((1, [42, 3]), (1, [42, 2])); s.roster(); s.leave(42)
s.roster((7, [42]), (1, [42]), (3, [42])); s.leader(7, 7); s.leader(3, 1)
s.leader(99, 42); s.leader(1, 0); s.leader(0, 0xffffffff); s.finish()

s = Scenario('leave-all-containing-teams-and-leader-collapse')
s.roster((1, [2, 42]), (3, [2]), (7, [1, 42])); s.leave(2); s.leave(1)
s.roster((1, [2, 3]), (7, [1, 42])); s.leave(1); s.leave(77); s.finish()

s = Scenario('own-role-is-explicit-and-stale-events-recreate-state')
s.roster((1, [42]), (2, [7])); s.world(42); s.packet(63, 1); s.world(7)
s.leave(1); s.join(1, 42); s.world(0); s.join(0, 0); s.leader(0, 42); s.world(42)
s.invite(1); s.world(1); s.packet(63, 1); s.finish()

s = Scenario('nearby-replacement-names-position-and-scene-pruning')
s.nearby(1, 100, 'other one'); s.nearby(2, 200, 'other two'); s.position(3, 300)
s.position(1, 200, 12); s.world(42, ''); s.nearby(42, 100, 'nearby self not preferred')
s.position(42, 200); s.nearby(1, 300, 'renamed 星😀'); s.packet(1, 1, pack('I', 1))
s.packet(1, 1, pack('I', 1)); s.nearby(0, 0, ''); s.nearby(0xffffffff, 65535, 'A\0B\0\0', 255)
s.world(0); s.position(0, 0); s.packet(6, 1, pack('iHH', 0, 4, 5)); s.finish()

s = Scenario('requests-received-repeated-with-deadline-and-no-auto-expiry')
s.invite(1, at=0); s.application(1); s.offer(1); s.invite(1, at=30)
s.seed(sent=2); s.packet(13, 16, b'\x01', at=500); s.expire(45.499); s.expire(45.5)
s.expire(60.249); s.expire(60.25); s.expire(60.5); s.expire(89.999); s.expire(90); s.expire(1000)
s.invite(1, at=2000); s.expire(2059.999); s.expire(2060); s.invite(1, at=2060); s.finish()

for own in (None, 42, 1):
    s = Scenario('join-request-filter-own-' + str(own))
    if own is not None: s.world(own)
    for role in (1, 2, 42): s.invite(role); s.application(role); s.offer(role)
    s.seed(); s.join(7, 1); s.join(7, 42); s.join(7, 2); s.finish()

s = Scenario('leader-transfer-clears-offers-even-with-missing-old-team')
for role in (1, 2): s.invite(role); s.application(role); s.offer(role)
s.seed(); s.leader(99, 2); s.seed(); s.roster((1, [2, 42])); s.offer(42)
s.leader(1, 42); s.leader(1, 42); s.finish()

s = Scenario('all-answer-notice-rejection-and-flag-bytes')
s.invite(1)
for value in range(256):
    s.seed(enabled=value % 2 == 0)
    s.packet(13, 3 if value % 2 else 10, pack('BI', value, value % 3))
    s.seed(); s.packet(13, 15, pack('BB', 2, value) + (pack('I', 2) if value == 2 else b''))
    s.packet(13, 16, pack('B', value)); s.seed(); s.packet(33, 1, pack('B', value))
    s.seed(); s.packet(33, 2, bytes([255, 255, value, 255, 88]))
s.finish()

s = Scenario('prefix-tail-and-malformed-atomicity')
s.world(42); s.roster((42, [1])); s.invite(1); s.seed()
cases = [(13, 1, pack('I', 2)), (13, 4, pack('I', 1)), (13, 9, pack('I', 2)),
         (13, 3, pack('BI', 1, 2)), (13, 10, pack('BI', 2, 1)), (13, 5, pack('II', 42, 2)),
         (13, 6, team_list([(7, [42, 1]), (2, [3])])), (13, 15, pack('BI', 1, 2)),
         (13, 15, pack('BBI', 2, 2, 2)), (13, 15, pack('BB', 2, 1)),
         (13, 15, pack('BII', 3, 2, 42)), (13, 16, b'\x01'),
         (4, 1, nearby(1)), (1, 1, pack('I', 1)), (33, 1, b'\x05'),
         (33, 2, bytes([0, 0, 1, 0])), (7, 1, pack('IHHH', 42, 100, 1, 2))]
for main, sub, payload in cases:
    for length in range(len(payload)): s.packet(main, sub, payload[:length])
    s.packet(main, sub, payload + b'\x7f')
for payload in (team_list([(0, [])]), pack('IB', 1, 4), team_list([(1, [0])]),
                team_list([(1, [1])]), team_list([(2, [3]), (1, [1])]),
                team_list([(2, [3]), (1, [1])])[:-1]):
    s.packet(13, 6, payload)
for payload in (b'\x04', b'\x04\xff', b'\x00\xff'): s.packet(13, 15, payload)
s.finish()

s = Scenario('unrelated-social-world-and-session-observations')
s.world(42); s.roster((42, [1])); s.invite(2); s.seed()
for main, sub, payload in [(23, 13, pack('HB', 12, 1)), (23, 120, b'\x02\xff'),
                           (63, 1, b''), (63, 7, b'\x00\x00'), (1, 11, b''),
                           (39, 85, b'\x01'), (255, 255, b'\xff'), (13, 255, b'\xff')]:
    s.packet(main, sub, payload)
s.finish()

s = Scenario('unbounded-team-collection-and-incremental-members-source-boundaries')
s.world(0xffffffff)
s.roster(*[(r, [0xffffffff]) for r in range(1, 129)])
for role in range(129, 200): s.join(1, role)
s.roster((1, [])); s.leave(0xffffffff); s.finish()

for seed in range(16):
    rng = random.Random(791300 + seed)
    s = Scenario('seeded-mixed-' + str(seed))
    for index in range(100):
        role = rng.choice(QUERY_IDS); op = rng.randrange(16)
        if op == 0:
            leader = rng.choice(QUERY_IDS[1:]); members = rng.sample([r for r in QUERY_IDS[1:] if r != leader], rng.randrange(4))
            s.roster((leader, members))
        elif op == 1: s.join(rng.choice(QUERY_IDS), role)
        elif op == 2: s.leave(role)
        elif op == 3: s.leader(rng.choice(QUERY_IDS), role)
        elif op == 4: s.world(role, rng.choice(['', '自己', 'A\0B\0']))
        elif op == 5: s.nearby(role, rng.choice([0, 100, 200, 65535]), rng.choice(['', '夥伴😀', 'A\0B\0']))
        elif op == 6: s.position(role, rng.choice([0, 100, 200, 65535]), rng.choice([7, 12]))
        elif op == 7: s.invite(role)
        elif op == 8: s.application(role)
        elif op == 9: s.offer(role)
        elif op == 10: s.seed(sent=role)
        elif op == 11: s.expire(s.now + rng.choice([0, 15, 60]))
        elif op == 12: s.packet(13, 10, pack('BI', rng.randrange(256), role))
        elif op == 13: s.packet(33, 1, pack('B', rng.randrange(256)))
        elif op == 14: s.packet(33, 2, pack('BBBB', 0, 0, rng.randrange(4), 0))
        else: s.packet(1, 1, pack('I', role))
    s.finish()

sources = ['wlre/services/battle/party.py', 'wlre/network/social_protocol.py',
           'wlre/network/protocol.py', 'wlre/network/layouts.py', 'wlre/network/wire.py',
           'wlre/core/state.py', 'wlre/core/state_events.py', 'wlre/core/state_world_events.py',
           'wlre/core/state_session_events.py', 'wlre/services/world/house_navigation.py']
provenance = {p: hashlib.sha256((ROOT / p).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in sources}
count = sum(len(s['steps']) for s in scenarios)
lines = ['// Generated from retained Python. Synthetic offline data only.',
         'namespace Lala.Core.Tests.Social.Party;', 'public static class PartyEventPythonVectors', '{',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
         f'    public const int SnapshotCount = {count};',
         '    public static IEnumerable<object[]> Sequences()', '    {']
for s in scenarios:
    raw = json.dumps(s['steps'], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode('ascii')
    lines.append('        yield return new object[] { ' + json.dumps(s['name']) + ', Decode(' + json.dumps(encoded) + ') };')
lines += ['    }', '    private static string Decode(string encoded)', '    {',
          '        using var input = new MemoryStream(Convert.FromBase64String(encoded));',
          '        using var gzip = new System.IO.Compression.GZipStream(input, System.IO.Compression.CompressionMode.Decompress);',
          '        using var reader = new StreamReader(gzip, System.Text.Encoding.UTF8);',
          '        return reader.ReadToEnd();', '    }', '}']
output = Path(__file__).with_name('PartyEventPythonVectors.cs')
output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
assert output.stat().st_size < 500_000
print(f'{len(scenarios)} sequences, {count} snapshots; {output.stat().st_size} bytes')
