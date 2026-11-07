"""Synthetic offline guild-action receive oracle, not a scheduler or game client.

Executes actual defaults/apply_actions, after actual apply_guild then dispatch_local,
as in State.apply. Imports explicit pending evidence without begin/command/tick,
quotes, reservations, sends, runtime catalogs or lifecycle work. Every historical
expectation is copied. Run from repository root with retained Python dependencies:
python dotnet/Lala.Core.Tests/Social/GuildActions/generate_guild_action_vectors.py
"""
import ast
import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import struct
import sys

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'dotnet/Lala.Core.Tests'))
from TestSupport.gzip_json_fixture import csharp_gzip_json
from wlre.core.state import State
from wlre.core.state_events import dispatch_local
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.social.guild import apply_guild
from wlre.services.social import guild_actions as ga

# Assert the retained State.apply hook order that the isolated harness reproduces.
source = ast.parse((ROOT / 'wlre/core/state.py').read_bytes())
apply = next(n for n in ast.walk(source) if isinstance(n, ast.FunctionDef) and n.name == 'apply')
calls = [n.value.func.id for n in apply.body if isinstance(n, ast.Expr)
         and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)]
assert calls.index('apply_guild') < calls.index('dispatch_local') < calls.index('apply_actions')


def pack(fmt, *values): return struct.pack('<' + fmt, *values)


def text(value):
    raw = value.encode('utf-16le')
    return pack('B', len(raw)) + raw


def roster(members=(1,), serial=9, level=1):
    raw = text('Synthetic 組織') + text('unused chief') + pack('B', len(members))
    for role in members:
        raw += pack('I', role) + text('synthetic member') + bytes(16) + bytes(8) + text('') + bytes(8 + 13)
    return raw + text('') + bytes(2) + pack('B', level) + bytes(37) + pack('I', serial)


def world(role):
    return pack('IBHHHBBBIIBBB', role, 0, 100, 1, 2, 0, 0, 0, 0, 0, 0, 0, 0) + text('synthetic player') + bytes(8) + text('') + bytes(2)


def pending(kind='donate', **changes):
    p = dict(kind=kind, role=1, guild=9, token=(True, 'synthetic catalog'), epoch=0, due=120.0)
    if kind == 'sign': p.update(sign_ack=False)
    else:
        p.update(quote=dict(price=150, price_kind=4, sell_id=8, save_index=7, count=2, item_index=None),
                 before_remaining=5, gold_before=1000, gold_ack=False, sell_ack=False, remaining_ack=False)
    p.update(changes)
    return p


scenarios = []


class Scenario:
    def __init__(self, name):
        self.name, self.state, self.steps = name, State(), []
        assert self.state.snapshot()['guild_actions'] == ga.defaults()
        self.record()

    def record(self, **operation):
        self.steps.append(copy.deepcopy(dict(**operation, expected=self.state.snapshot()['guild_actions'],
            own_role_id=self.state.player.get('role_id'), valid_member=ga.valid_member(self.state))))

    def seed(self, **changes):
        self.state.guild_actions.update(copy.deepcopy(changes))
        self.record(seed=copy.deepcopy(self.state.guild_actions))

    def packet(self, main, sub, raw=b''):
        message = dict(main=main, sub=sub, hex=raw.hex().upper())
        try:
            event = decode(Packet(main, sub, raw), self.state.player.get('role_id'))
        except ProtocolError as exc:
            self.record(message=message, error=str(exc)); return
        apply_guild(self.state, event)
        dispatch_local(self.state, event, affects_navigation=lambda *_: False)
        ga.apply_actions(self.state, event)
        self.record(message=message)

    def ready(self, role=1, serial=9):
        self.packet(3, 1, world(role)); self.roster((role,), serial)
        self.packet(26, 4, pack('I', 1000)); self.sign(1); self.donate(5)

    def roster(self, members=(1,), serial=9): self.packet(39, 2, roster(members, serial))
    def sign(self, value): self.packet(39, 85, pack('B', value))
    def result(self, value): self.packet(39, 86, pack('B', value))
    def donate(self, value, allow=1): self.packet(39, 87, pack('BB', value, allow))
    def sell(self, index=7, count=3): self.packet(10, 5, pack('BBB', 1, index, count))
    def gold(self, amount=150, sub=2): self.packet(26, sub, pack('IB', amount, 0))
    def day(self): self.packet(10, 5, b'\x03')
    def finish(self): scenarios.append(dict(name=self.name, steps=self.steps))


s = Scenario('unbound-observations-are-discarded-not-buffered')
s.sign(1); s.result(0); s.donate(5); s.packet(39, 15, b'\xff')
s.packet(10, 5, b'\x02\x02\x01\x02'); s.sell(); s.day()
s.roster(); s.sign(2); s.packet(3, 1, world(1)); s.sign(1); s.roster(); s.sign(3)
s.roster((), 9); s.sign(2); s.roster((1,), 0); s.donate(2); s.roster(); s.donate(3); s.finish()

s = Scenario('roster-binding-change-invalid-leave-and-late-rebind')
s.ready(); s.seed(sign_attempted=True, reserved=450, confirmed=300, counts={'7':2}, counts_ready=True,
                  catalog_ready=True, catalog_token=(True, 'old'), price=150, donated=2)
s.roster((1,), 10); s.sign(2); s.donate(3); s.roster((), 10)
s.packet(39, 8, pack('I', 1)); s.sign(1); s.roster((1,), 10)
s.packet(39, 7, pack('BI', 1, 1)); s.packet(39, 7, pack('BI', 0, 2))
s.packet(39, 6, pack('I', 1)); s.sign(2); s.roster((1,), 9)
s.packet(39, 10, b'\x01'); s.packet(39, 10, b'\x00'); s.roster(); s.finish()

s = Scenario('world-role-and-role-list-reset-boundaries')
s.ready(); s.seed(pending=pending(), reserved=150, sign_attempted=True)
s.packet(3, 1, world(1)); s.packet(3, 1, world(2)); s.sign(2); s.roster((2,))
s.seed(pending=pending('sign', role=2), uncertain=True, reserved=450, epoch=17)
s.packet(63, 1); s.sign(1); s.roster((2,)); s.packet(3, 1, world(2))
s.seed(role=None, pending=pending('sign'), sign_state=2); s.packet(3, 1, world(0))
s.roster((1,)); s.packet(3, 1, world(1)); s.finish()

for reason, event in [('roster-invalid', (39, 2, roster(()))), ('roster-changed', (39, 2, roster(serial=11))),
                      ('self-removed', (39, 6, pack('I', 1))), ('self-left', (39, 7, pack('BI', 0, 1))),
                      ('disbanded', (39, 10, b'\0'))]:
    s = Scenario('pending-identity-' + reason); s.ready(); s.seed(pending=pending(), reserved=150)
    s.packet(*event); s.result(0); s.donate(4); s.gold(); s.roster(); s.finish()

for order in itertools.permutations(('result', 'state')):
    s = Scenario('sign-receipts-only-' + '-'.join(order)); s.ready(); s.seed(pending=pending('sign'), sign_attempted=True)
    for part in order:
        if part == 'result': s.result(0); s.result(0)
        else: s.sign(2); s.sign(2)
    s.sign(1); s.result(0); s.sign(2); s.finish()

s = Scenario('all-sign-results-on-imported-pending-and-unsolicited-results')
s.ready()
for result in range(256):
    s.seed(pending=pending('sign'), uncertain=False, sign_state=1, sign_attempted=True)
    s.result(result); s.result(result)
s.seed(pending=None, sign_state=0)
for result in (0, 1, 2, 3, 255): s.result(result)
s.finish()

for order in itertools.permutations(('gold', 'remaining', 'sell')):
    s = Scenario('donation-receipts-only-' + '-'.join(order)); s.ready(); s.seed(pending=pending(), reserved=150)
    for part in order:
        if part == 'gold': s.gold()
        elif part == 'remaining': s.donate(4); s.donate(4)
        else: s.sell(); s.sell()
    s.packet(255, 255, b'\x01'); s.result(0); s.gold(); s.donate(3); s.sell(count=4); s.finish()

for label, operations in [
    ('remaining-unchanged', [(39, 87, b'\x05\x00'), (39, 87, b'\x04\x00')]),
    ('remaining-wrong-before-ack', [(39, 87, b'\x03\x01')]),
    ('remaining-reverts-after-ack', [(39, 87, b'\x04\x01'), (39, 87, b'\x05\x01')]),
    ('sell-unchanged-after-ack-is-retained', [(10, 5, b'\x01\x07\x03'), (10, 5, b'\x01\x07\x02')]),
    ('sell-mismatch', [(10, 5, b'\x01\x07\x04')]),
    ('sell-snapshot-does-not-ack', [(10, 5, b'\x02\x07\x00\x00\x00\x00\x00\x00\x03')]),
    ('sell-index-zero-ignored', [(10, 5, b'\x01\x00\xff')]),
    ('gold-snapshot-not-a-payment-ack', [(26, 4, pack('I', 850))]),
    ('gold-limit-uncertain', [(26, 3, b'ignored')]),
    ('gold-increase-uncertain', [(26, 1, pack('IB', 150, 0))]),
    ('gold-wrong-decrease', [(26, 2, pack('IB', 149, 0))]),
    ('gold-underflow', [(26, 2, pack('IB', 1001, 0))]),
    ('server-action-error', [(39, 15, b'\xff')]),
]:
    s = Scenario(label); s.ready(); s.seed(pending=pending(), reserved=150)
    for event in operations: s.packet(*event)
    s.finish()

s = Scenario('gold-uses-post-local-value-not-pre-local-and-is-not-guild-gated')
s.ready(); s.seed(pending=pending(), reserved=150); s.gold()
s.seed(pending=pending(gold_before=1000)); s.gold()  # Matching delta but wrong resulting total.
s.seed(pending=pending(gold_before=700), guild=None); s.gold()  # Gold branch is not S39-gated.
s.packet(63, 1); s.seed(pending=pending(gold_before=550)); s.gold(); s.finish()

s = Scenario('day-reset-only-budget-reset-and-uncertainty-latch')
s.ready(); s.seed(reserved=2**90, confirmed=2**80, epoch=2**100, sign_state=2, sign_attempted=True,
                  counts={'255':255, '1':7}, counts_ready=True, catalog_token=(True, 'keep'),
                  catalog_ready=True, price=150, donated=-250, settings_revision=2**90)
s.sign(1); s.day(); s.day()
s.seed(pending=pending(), reserved=450, confirmed=300, sign_state=2, sign_attempted=True)
s.day(); s.sell(); s.donate(4); s.day(); s.roster(); s.finish()

s = Scenario('byte-boundaries-and-zero-free-quote-receipt-evidence')
s.ready(); s.seed(pending=pending(quote=dict(price=0, price_kind=5, sell_id=8, save_index=0, count=0, item_index=None),
                                gold_ack=True, sell_ack=True), reserved=0)
s.donate(4); s.gold(0)
s.seed(pending=pending(quote=dict(price=150, price_kind=4, sell_id=8, save_index=255, count=255, item_index=None)))
s.sell(255, 255); s.sell(255, 0)
s.seed(pending=pending(before_remaining=0)); s.donate(0); s.donate(255)
s.packet(10, 5, bytes([2,255]) + bytes(range(255))); s.packet(10, 5, b'\x02\x00'); s.finish()

s = Scenario('decoder-errors-do-not-publish-any-partial-state')
s.ready(); s.seed(pending=pending(), reserved=150)
for main, sub, raw in [(39,85,b'\1'),(39,86,b'\0'),(39,87,b'\4\1'),(39,15,b'\5'),
                      (10,5,b'\0'),(10,5,b'\1\7\3'),(10,5,b'\2\2\3\4'),(10,5,b'\3'),
                      (26,2,pack('IB',150,0)),(39,2,roster())]:
    s.packet(main,sub,raw[:-1]); s.packet(main,sub,raw+b'\xff')
s.packet(39,85,b'\4'); s.packet(39,87,b'\4\2'); s.packet(10,5,b'\4')
s.packet(26,2,pack('IB',150,2)); s.finish()

for seed in range(12):
    r = random.Random(793985 + seed); s = Scenario('seeded-late-duplicate-reset-' + str(seed)); s.ready()
    for _ in range(90):
        op = r.randrange(16)
        if op == 0: s.sign(r.randrange(4))
        elif op == 1: s.result(r.choice([0,1,2,255]))
        elif op == 2: s.donate(r.choice([0,3,4,5,255]), r.randrange(2))
        elif op == 3: s.sell(r.choice([0,1,7,255]), r.choice([0,2,3,4,255]))
        elif op == 4: s.day()
        elif op == 5: s.gold(r.choice([0,149,150,1001]), r.choice([1,2]))
        elif op == 6: s.roster(r.choice([(1,),(2,),(),(1,2)]), r.choice([0,9,10,0xffffffff]))
        elif op == 7: s.packet(3,1,world(r.choice([0,1,2,0xffffffff])))
        elif op == 8: s.packet(63,1)
        elif op == 9: s.seed(pending=pending(r.choice(['sign','donate'])), reserved=150, sign_attempted=True)
        elif op == 10: s.packet(39,6,pack('I',r.choice([1,2])))
        elif op == 11: s.packet(39,7,pack('BI',r.randrange(2),r.choice([1,2])))
        elif op == 12: s.packet(39,15,pack('B',r.randrange(256)))
        elif op == 13: s.packet(10,5,b'\x02\x02\x00\xff')
        elif op == 14: s.packet(26,4,pack('I',r.choice([0,1000,0xffffffff])))
        else: s.packet(255,255,b'ignored')
    s.finish()

sources = ['wlre/services/social/guild_actions.py', 'wlre/services/social/guild.py', 'wlre/core/state.py',
           'wlre/core/state_events.py', 'wlre/core/state_session_events.py', 'wlre/core/state_world_events.py',
           'wlre/network/protocol.py', 'wlre/network/layouts.py', 'wlre/network/wire.py']
provenance = {p: hashlib.sha256((ROOT / p).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in sources}
lines = ['// Generated by generate_guild_action_vectors.py; synthetic offline receive evidence only.',
         'namespace Lala.Core.Tests.Social.GuildActions;', 'public static class GuildActionsPythonVectors', '{',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
         f'    public const int SnapshotCount = {sum(len(s["steps"]) for s in scenarios)};',
         '    public static IEnumerable<object[]> Sequences()', '    {']
for scenario in scenarios:
    encoded = csharp_gzip_json(json.dumps(scenario['steps'], ensure_ascii=False, separators=(',', ':')))
    lines.append('        yield return new object[] { ' + json.dumps(scenario['name']) + ', ' + encoded + ' };')
lines += ['    }', '}']
output = Path(__file__).with_name('GuildActionsPythonVectors.cs')
output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'{len(scenarios)} sequences, {sum(len(s["steps"]) for s in scenarios)} snapshots; {output.stat().st_size} bytes')
