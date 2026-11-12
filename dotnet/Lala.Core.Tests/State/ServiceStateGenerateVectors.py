"""Real State.apply integration oracle, entirely synthetic and offline.

All source observers actually execute. Only time and current runtime inputs are supplied;
tracing wrappers do not replace observer behavior. Project only the declared supported
subset. No command, tick, scheduler, transport, official catalog or account data is used.
"""
import base64
from contextlib import ExitStack
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
import wlre.core.state as state_module
from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError

ORDER = ('apply_daily_tasks', 'apply_cube', 'apply_recovery', 'apply_guild', 'apply_activity',
         'apply_crafting', 'apply_storage', 'apply_live', 'apply_points_event', 'apply_party',
         'apply_expedition', 'apply_instances', 'dispatch_local', 'apply_tent',
         'observe_shop_evidence', 'observe_efficiency', 'apply_actions', 'apply_ark')
ACTIVITIES = {'釣魚': 0, '採集': 1, '跳舞': 2, '馬桶製作': 3, '鍛鍊': 4, '夥伴鍛鍊': 5}


def p(fmt, *values): return struct.pack('<' + fmt, *values)
def text(value):
    raw = value.encode('utf-16le')
    return bytes([len(raw)]) + raw

def world(role=17, scene=101):
    return (p('IBHHHBBBIIBBB', role, 0, scene, 1, 2, 0, 0, 0, 0, 0, 0, 0, 0)
            + text('Synthetic 角色') + bytes(8) + text('') + p('H', 0))

def roster(role=17):
    profile = text('Synthetic 成員') + bytes(15) + b'\0' + bytes(8) + text('') + bytes(8)
    return (text('Synthetic 組織') + text('') + b'\1' + p('I', role) + profile + bytes(13)
            + text('') + bytes(2) + b'\1' + bytes(37) + p('I', 72))

def daily(progress=1, value=40):
    return bytes([value, value] + [progress]*20 + [0]*9 + [1, 0])
def team(index=1, minutes=3): return p('BH4H4HH', index, minutes, 1, 2, 0, 0, 42, 43, 0, 0, 7)
def unit(pid=17):
    return (p('BBIHIBBIHIHBBBBHHBBII', 16, 0, pid, 2, 0, 3, 1, 100, 40, 90, 20,
              19, 2, 1, 3, 0, 0, 1, 2, 0, 0) + b'\0'
            + b''.join(p('HI', n, n*1000) for n in range(9)))


def project(state):
    s = state.snapshot()
    session = {k: s[k] for k in ('phase', 'packet_count', 'roles', 'gold', 'event_flow', 'npc_dialogue',
                                'initial_data_complete', 'unimplemented_count', 'attributes')}
    session['npc_dialogue'].setdefault('history', [])
    session['npc_dialogue'].setdefault('choice_continuation_pending', False)
    world = {k: s[k] for k in ('phase', 'packet_count', 'player', 'positions', 'navigation', 'location',
                              'local_movement', 'movement_check')}
    world['player'] = world['player'] or None
    world['positions'] = [dict(role_id=int(k), x=v[0], y=v[1]) for k, v in world['positions'].items()]
    if world['navigation'].get('house_context') is not None:
        world['navigation']['house_context'].setdefault('sizes', {})
    battle = {k: s[k] for k in ('battle', 'battle_units', 'battle_count')}
    battle['unit_order'] = list(s['battle_units'])
    battle['command_order'] = list(s['battle'].get('commands', {}))
    d = s['daily_tasks']
    d['marks'] = dict(daily_value=d['daily_value'] or 0, weekly_value=d['weekly_value'] or 0,
        daily_done=d.pop('daily_done_mark'), daily_reward=d.pop('daily_reward_mark'),
        daily_event_a=d.pop('daily_event_reward_a'), daily_event_b=d.pop('daily_event_reward_b'),
        weekly_done=sum(v << (8*i) for i, v in enumerate(d.pop('weekly_done_mark'))),
        weekly_reward=d.pop('weekly_reward_mark'), weekly_event_a=d.pop('weekly_event_reward_a'),
        weekly_event_b=d.pop('weekly_event_reward_b'))
    return dict(local=dict(session=session, world=world, battle=battle), daily_tasks=d,
                time_cube=s['time_cube'], recovery=s['potion_storage'], guild=s['guild'],
                activities=sorted(ACTIVITIES[k] for k in s['activities']), storage=s['room_storage'],
                server_stackable=s['inventory'].get('server_stackable'), expedition=s['expedition'])


def evidence(state):
    s = state.snapshot()
    return dict(phase=s['phase'], player=s['player'] or None, packet_count=s['packet_count'])

sequences = []
covered = set()
class Scenario:
    def __init__(self, name, count=0):
        self.state = State(packet_count=count)
        self.steps = []
        self.value = dict(name=name, count=str(count), initial=project(self.state), steps=self.steps)
        sequences.append(self.value)
    def packet(self, main, sub, payload=b'', at=None, known=False):
        now = 100 + len(self.steps)*.25 if at is None else at
        step = dict(main=main, sub=sub, hex=payload.hex(), at=now, known=known)
        try:
            event = decode(Packet(main, sub, payload), self.state.player.get('role_id'))
        except ProtocolError:
            step['error'] = True
        else:
            covered.add(event['type'])
            trace = []
            def wrap(name, function):
                def observed(state, event, **kwargs):
                    trace.append(dict(name=name, before=evidence(state)))
                    result = function(state, event, **kwargs)
                    trace[-1]['after'] = evidence(state)
                    return result
                return observed
            runtime = SimpleNamespace(stages={101: {}}, combat_catalog=None) if known else None
            with ExitStack() as stack:
                stack.enter_context(patch('time.monotonic', return_value=now))
                stack.enter_context(patch('wlre.services.world.dynamic_bundle_runtime.current_runtime', return_value=runtime))
                for name in ORDER:
                    stack.enter_context(patch.object(state_module, name, wrap(name, getattr(state_module, name))))
                self.state.apply(event)
            assert [row['name'] for row in trace] == list(ORDER)
            dispatch = trace[ORDER.index('dispatch_local')]
            assert all(row['before'] == dispatch['before'] for row in trace[:ORDER.index('dispatch_local')])
            assert all(row['before'] == dispatch['after'] for row in trace[ORDER.index('dispatch_local')+1:])
            step.update(error=False, kind=event['type'], before=dispatch['before'], after=dispatch['after'])
        step['expected'] = project(self.state)
        self.steps.append(step)
        return self

s = Scenario('interleaved_roles_pre_post_evidence', 2**90)
s.packet(122, 1, p('BBHH', 0, 2, 3, 1)).packet(39, 2, roster()).packet(23, 123, p('IB', 17, 0))
s.packet(3, 1, world()).packet(124, 1, daily()).packet(124, 2, b'\1\2')
s.packet(23, 208, p('BBi', 3, 1, 100)).packet(62, 57, p('BBHHHH', 1, 1, 1, 1, 42, 5))
s.packet(31, 18, team()).packet(23, 123, p('IB', 17, 0)).packet(63, 1)
s.packet(122, 1, p('BBHH', 1, 1, 3, 0)).packet(3, 1, world(18))
s.packet(39, 7, p('BI', 0, 17)).packet(39, 7, p('BI', 0, 18)).packet(39, 2, roster())
s.packet(124, 3, b'\2\0\1\2').packet(31, 17, p('BH', 1, 2)).packet(1, 11)
s.packet(3, 1, world(17)).packet(63, 7, b'\1\1').packet(20, 8).packet(255, 254)

s = Scenario('repeated_late_and_reset_receive_evidence')
s.packet(3, 1, world()).packet(124, 2, b'\1\2').packet(124, 1, daily())
s.packet(124, 1, daily()).packet(124, 2, b'\1\2').packet(124, 2, b'\1\2')
s.packet(124, 1, daily(2)).packet(124, 3, b'\2\0\1\1').packet(124, 3, b'\xffopaque')
s.packet(124, 4, b'\1').packet(124, 5, b'\x0f').packet(63, 1)
for _ in range(2):
    s.packet(23, 208, p('BBi', 4, 2, 50)).packet(23, 208, p('BBi', 3, 1, 100))
    s.packet(23, 208, p('BBi', 4, 1, -30)).packet(62, 57, p('BBHHHH', 1, 1, 1, 1, 42, 5))
s.packet(62, 57, p('BBHHH', 1, 2, 1, 43, 1)).packet(62, 57, p('BHH', 2, 1, 20))
s.packet(31, 17, p('BH', 4, 5)).packet(31, 18, team(4), at=200).packet(31, 17, p('BH', 4, 2), at=100)
s.packet(31, 16, p('BBHH', 1, 4, 0, 0)).packet(31, 17, p('BH', 4, 0)).packet(31, 20, b'\1')

s = Scenario('activities_geometry_current_catalog_and_local_battle')
s.packet(62, 67).packet(62, 84, b'\1').packet(62, 84, b'\2').packet(62, 64)
s.packet(3, 1, world()).packet(62, 67).packet(23, 123, p('IB', 17, 0))
s.packet(7, 4, p('BII', 0, 1, 17)).packet(7, 4, p('BII', 0, 1, 18))
s.packet(62, 64, known=True).packet(62, 64, known=False)
s.packet(11, 250, p('BBB', 1, 2, 1) + unit()).packet(52, 1, p('H', 1))
s.packet(8, 1, p('BBII', 36, 1, 1234, 0)).packet(11, 12, b'\1').packet(20, 8)
s.packet(12, 1, p('IHHH', 17, 101, 10, 20)).packet(26, 4, p('I', 50)).packet(26, 2, p('IB', 5, 0))
s.packet(3, 1, world(17)).packet(1, 23).packet(51, 1, b'bad')

s = Scenario('malformed_packets_never_enter_apply')
s.packet(3, 1, world())
for main, sub, body in [(124, 1, daily()[:-1]), (124, 2, b'\1'), (122, 1, b'\0\4\0\0\0\0'),
        (122, 3, b'\0\0'), (23, 208, b'\3\1'), (39, 2, roster()[:-1]), (62, 57, b'\1\1\xff\xff'),
        (31, 18, team()[:-1]), (23, 123, b'\1'), (3, 1, world()[:-1]), (26, 4, b'\0'),
        (7, 4, p('BI', 0, 0xffffffff))]:
    s.packet(main, sub, body).packet(1, 23)

rng = random.Random(2026110801)
for index in range(10):
    s = Scenario('seeded_full_apply_interleave_' + str(index), index*100)
    for step in range(60):
        role = rng.choice((17, 18))
        choice = rng.randrange(18)
        if choice == 0: s.packet(3, 1, world(role))
        elif choice == 1: s.packet(63, 1)
        elif choice == 2: s.packet(124, 1, daily(rng.randrange(4)))
        elif choice == 3: s.packet(124, 2, bytes([rng.randrange(3), 2]))
        elif choice == 4: s.packet(122, 1, p('BBHH', rng.randrange(2), rng.randrange(4), 3, rng.randrange(5)))
        elif choice == 5: s.packet(23, 208, p('BBi', 3, 1, rng.randrange(100)))
        elif choice == 6: s.packet(23, 208, p('BBi', 4, 1, rng.randrange(-40, 20)))
        elif choice == 7: s.packet(39, 2, roster(role))
        elif choice == 8: s.packet(39, 7, p('BI', 0, role))
        elif choice == 9: s.packet(23, rng.choice((122, 123)), p('IB', role, 0))
        elif choice == 10: s.packet(62, 57, p('BBHHH', 1, 2, rng.randrange(1, 4), 42, 1))
        elif choice == 11: s.packet(31, 18, team(rng.randrange(1, 4), rng.randrange(5)))
        elif choice == 12: s.packet(31, 17, p('BH', rng.randrange(1, 4), rng.randrange(5)))
        elif choice == 13: s.packet(62, 64, known=bool(step % 2))
        elif choice == 14: s.packet(26, 4, p('I', step))
        elif choice == 15: s.packet(20, 8)
        elif choice == 16: s.packet(62, 84, bytes([step % 3]))
        else: s.packet(255, 255)

sources = ['wlre/core/state.py', 'wlre/core/state_events.py', 'wlre/core/state_session_events.py',
    'wlre/core/state_world_events.py', 'wlre/core/state_battle_events.py', 'wlre/core/activity.py',
    'wlre/services/daily_tasks.py', 'wlre/services/time_cube.py', 'wlre/services/items/recovery.py',
    'wlre/services/items/room_storage.py', 'wlre/services/social/guild.py', 'wlre/services/expedition/manager.py',
    'wlre/services/items/crafting.py', 'wlre/services/items/combat_resources.py', 'wlre/services/items/inventory.py',
    'wlre/services/battle/attribute_points.py', 'wlre/services/battle/party.py', 'wlre/services/instances.py',
    'wlre/services/world/tent.py', 'wlre/services/world/npc_shop_evidence.py', 'wlre/core/efficiency.py',
    'wlre/services/social/guild_actions.py', 'wlre/services/star_ark.py', 'wlre/network/protocol.py']


def canonical_source_sha256(raw):
    # Match Git text checkouts without decoding or ignoring any other content bytes.
    # Only CRLF pairs become LF; bare CR, BOMs and invalid UTF-8 remain significant.
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


hashes = {path: canonical_source_sha256((ROOT/path).read_bytes()) for path in sources}
lines = ['// Generated by ServiceStateGenerateVectors.py from real State.apply. Synthetic offline evidence.',
         'namespace Lala.Core.Tests.State;', 'public static class ServiceStatePythonVectors', '{',
         '    public const string ObserverOrder = ' + json.dumps(json.dumps(ORDER)) + ';',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(hashes)) + ';',
         '    public static IEnumerable<object[]> Sequences()', '    {']
for vector in sequences:
    raw = json.dumps(vector, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
    lines.append('        yield return new object[] { ' + json.dumps(vector['name']) + ', Decode(' + json.dumps(encoded) + ') };')
lines += ['    }', '    private static string Decode(string encoded)', '    {',
    '        using var input = new System.IO.MemoryStream(System.Convert.FromBase64String(encoded));',
    '        using var gzip = new System.IO.Compression.GZipStream(input, System.IO.Compression.CompressionMode.Decompress);',
    '        using var reader = new System.IO.StreamReader(gzip, System.Text.Encoding.UTF8);',
    '        return reader.ReadToEnd();', '    }', '}']
Path(__file__).with_name('ServiceStatePythonVectors.cs').write_text('\n'.join(lines)+'\n')
print(f'Generated {len(sequences)} real State.apply scenarios / {sum(len(s["steps"]) for s in sequences)} checkpoints; {len(covered)} event kinds.')
