"""Offline integration vectors from real dispatch_local, State helpers, and StatePublisher.

Deliberately does not call State.apply's service observers. Only its increment-before-
dispatch ownership is composed here. No requests, runtime catalogs or transport are used.
"""
import base64
import gzip
import json
import os
from pathlib import Path
import random
import struct
import sys

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from wlre.core.state import State
from wlre.core.state_events import dispatch_local
from wlre.core.state_world_events import WORLD_KINDS
from wlre.core.state_battle_events import BATTLE_KINDS
from wlre.core.state_session_events import SESSION_KINDS
from wlre.network.protocol import decode
from wlre.network.state_updates import StatePublisher
from wlre.network.wire import Packet

SESSION = ('phase', 'packet_count', 'roles', 'gold', 'event_flow', 'npc_dialogue',
           'initial_data_complete', 'unimplemented_count', 'attributes')
WORLD = ('phase', 'packet_count', 'player', 'positions', 'navigation', 'location',
         'local_movement', 'movement_check')


def project(state):
    snapshot = state.snapshot()
    session = {key: snapshot[key] for key in SESSION}
    session['npc_dialogue'].setdefault('history', [])
    session['npc_dialogue'].setdefault('choice_continuation_pending', False)
    world = {key: snapshot[key] for key in WORLD}
    world['positions'] = [dict(role_id=int(key), x=value[0], y=value[1])
                          for key, value in world['positions'].items()]
    if not world['player']: world['player'] = None
    if world['navigation'].get('house_context') is not None:
        world['navigation']['house_context'].setdefault('sizes', {})
    battle = {key: snapshot[key] for key in ('battle', 'battle_units', 'battle_count')}
    battle['unit_order'] = list(snapshot['battle_units'])
    battle['command_order'] = list(snapshot['battle'].get('commands', {}))
    return dict(session=session, world=world, battle=battle)


def p(fmt, *values): return struct.pack('<' + fmt, *values)

def world(role=17, scene=101, x=8, y=9):
    name = '合成角色'.encode('utf-16-le')
    return (p('IBHHHBBB IIBB', role, 1, scene, x, y, 2, 3, 4, 5, 6, 7, 1)
            + p('BHI', 1, 8, 9) + bytes([len(name)]) + name + bytes(9) + p('H', 10))

def role(index=1):
    text = 'Synthetic'.encode('utf-16-le')
    return (bytes([index, len(text)]) + text + p('BBIIIIqIBBIIBBHdB',
        15, 3, 500, 400, 300, 200, 123456789, 900, 1, 2, 3, 4, 0, 5, 60000, .5, 1)
        + p('IIIIHiiII', 1, 2, 3, 4, 5, -6, -7, 8, 9))

def unit(pid=17, col=3, row=1):
    return (p('BBIHIBBIHIHBBBBHHBBII', 16, 0, pid, 2, 0, col, row, 100, 40, 90, 20,
              19, 2, 1, 3, 0, 0, 1, 2, 0, 0) + b'\0'
            + b''.join(p('HI', n, n * 1000) for n in range(9)))

def effect(kind=1, mean=42):
    return p('BHBBBHBIHBH', 0, 1, 2, kind, 3, 4, 5, 6, mean, 7, 8)


def apply(state, event):
    state.packet_count += 1
    # Conservative unknown catalog: house-scoped geometry might affect this scene.
    dispatch_local(state, event, affects_navigation=lambda e, _: bool(e.get('affects_geometry')))


sequences = []
covered_kinds = set()
class Scenario:
    def __init__(self, name, **initial):
        self.state = State(**initial)
        self.value = dict(name=name, initial=project(self.state), steps=[])
        sequences.append(self.value)
    def step(self, operation, **args):
        step = dict(operation=operation, **args)
        if operation == 'packet':
            event = decode(Packet(args['main'], args['sub'], bytes.fromhex(args['hex'])))
            covered_kinds.add(event['type'])
            apply(self.state, event)
        elif operation == 'event':
            covered_kinds.add(args['event']['type'])
            apply(self.state, args['event'])
        elif operation == 'remember': self.state.remember_position(args['role_id'], args['x'], args['y'])
        elif operation == 'clear': step['removed'] = self.state.clear_position_history()
        elif operation == 'wait': self.state.wait_for_position()
        elif operation == 'confirm': self.state.confirm_location(args['scene'], args['x'], args['y'], args['source'])
        else: raise AssertionError(operation)
        step['expected'] = project(self.state)
        self.value['steps'].append(step)
        return self
    def packet(self, main, sub, payload=b''):
        return self.step('packet', main=main, sub=sub, hex=payload.hex().upper())
    def event(self, kind, **args): return self.step('event', event=dict(type=kind, **args))
    def start(self): return self.packet(11, 250, p('BBB', 1, 2, 2) + unit() + unit(18, 4))
    def position(self, role=17, scene=101, x=50, y=60):
        return self.packet(12, 1, p('IHHH', role, scene, x, y))

s = Scenario('interleaved_domains_and_current_identity', packet_count=2**90,
    npc_dialogue=dict(active=True, phase='awaiting_choice', history=[], choice_continuation_pending=True))
s.packet(26, 1, p('IB', 5, 0)).packet(63, 7, b'\0\1').packet(63, 1, role())
s.packet(26, 4, p('I', 400)).packet(3, 1, world()).start().packet(52, 1, p('H', 1))
s.event('battle_command_sent', col=3, row=1).event('movement_request', x=50, y=60)
s.packet(20, 1, effect()).packet(26, 2, p('IB', 3, 1)).packet(6, 1, p('iHH', 18, 30, 40))
s.position().packet(3, 1, world(18)).packet(11, 1, b'\3\1').packet(11, 0, p('IH', 17, 0))
s.packet(20, 7).packet(26, 3).packet(11, 1, b'\4\1').packet(63, 1).packet(1, 11)
s.packet(255, 255).packet(1, 23).packet(51, 1, b'bad').event('unsupported_decoder')
s.packet(3, 1, world(17)).packet(63, 7, b'\1\1').packet(26, 4, p('I', 7)).packet(20, 8)

s = Scenario('helpers_do_not_count_and_role_selection_does_not_reset_identity')
s.packet(3, 1, world()).step('remember', role_id=18, x=1, y=2)
s.event('movement_request', x=5, y=6).step('wait').step('confirm', scene=101, x=5, y=6, source='fixture')
s.step('clear').step('clear').packet(26, 4, p('I', 123)).start().packet(63, 1)
s.packet(11, 0, p('IH', 17, 0)).packet(6, 2, b'\7').packet(20, 74, b'\1')
s.position().packet(62, 64).position(scene=63501).packet(7, 1, p('IHHH', 17, 63501, 1, 2) + b'\0\0\1\3\1')

s = Scenario('no_identity_before_world_and_repeated_domain_switches')
s.start().packet(11, 0, p('IH', 17, 0)).packet(11, 1, b'\3\1').position()
s.packet(3, 1, world(18)).start().packet(11, 0, p('IH', 17, 0)).packet(11, 0, p('IH', 18, 0))
s.packet(63, 7, b'\0\0').packet(63, 1).packet(3, 1, world(17)).packet(63, 7, b'\1\0')
s.packet(11, 12, b'\1').packet(1, 23).packet(255, 254)

s = Scenario('remaining_routes_and_observer_only_events',
    npc_dialogue=dict(active=True, phase='requesting'))
s.packet(3, 1, world()).start().packet(11, 5, p('B', 1) + unit(17, 3))
s.event('battle_command_sent', col=3, row=1)
s.packet(50, 1, p('BBBHBBB', 1, 3, 1, 10001, 1, 0, 0))
s.packet(11, 10, b'\x03').packet(8, 1, p('BBII', 25, 2, 7, 9))
s.packet(20, 9).packet(20, 74, b'\x01').packet(8, 4).packet(1, 11)
# This is a real decoded service event but dispatch_local must not execute its observer.
s.packet(122, 1, p('BBHH', 1, 2, 3, 4))

rng = random.Random(20261108)
for index in range(5):
    s = Scenario(f'seeded_interleaving_{index}', packet_count=index*100,
        npc_dialogue=dict(active=True, phase='requesting'))
    s.packet(3, 1, world()).start()
    for step in range(40):
        kind = rng.randrange(18)
        rid = rng.choice((17, 18))
        if kind == 0: s.packet(3, 1, world(rid, rng.choice((101, 102, 63501))))
        elif kind == 1: s.packet(63, 7, bytes([rng.randrange(2), 1]))
        elif kind == 2: s.packet(63, 1, role())
        elif kind == 3: s.packet(26, 4, p('I', rng.randrange(500)))
        elif kind == 4: s.packet(26, rng.choice((1, 2)), p('IB', rng.randrange(100), 0))
        elif kind == 5: s.packet(20, 1, effect(rng.choice((1, 6, 255)), step))
        elif kind == 6: s.packet(11, 0, p('IH', rid, 0))
        elif kind == 7: s.start()
        elif kind == 8: s.position(rid, rng.choice((101, 102, 63501)))
        elif kind == 9: s.packet(6, 1, p('iHH', rid, step, step+1))
        elif kind == 10: s.event('movement_request', x=step, y=step+1)
        elif kind == 11: s.event('battle_command_sent', col=3, row=1)
        elif kind == 12: s.packet(51, 1, p('BBBI', 3, 1, 25, step))
        elif kind == 13: s.packet(52, 1, p('H', rng.randrange(4)))
        elif kind == 14: s.packet(255, 255)
        elif kind == 15: s.packet(1, 23)
        elif kind == 16: s.step('clear')
        else: s.packet(1, 1, p('I', rid))

assert covered_kinds >= WORLD_KINDS | BATTLE_KINDS | SESSION_KINDS, (
    WORLD_KINDS | BATTLE_KINDS | SESSION_KINDS) - covered_kinds

publishers = []
for name, interval, operations in [
    ('threshold_force_and_callback_elapsed', 10, [
        (0,'flush',0,False), (0,'publish',3,False), (2,'publish',0,False),
        (12,'flush',0,False), (13,'flush',2,False), (14,'flush',0,False),
        (14,'publish',1,True), (24,'publish',0,False), (25,'flush',0,False)]),
    ('zero_interval_and_empty_flush', 0, [(0,'flush',0,False), (0,'publish',0,False),
        (0,'publish',0,False), (0,'flush',0,False), (1,'publish',0,True)]),
    ('clock_regression_remains_pending', 5, [(10,'publish',0,False), (9,'publish',0,False),
        (14,'flush',0,False), (15,'flush',0,False)]),
    ('callback_exception_keeps_pending', 4, [(0,'publish',1,False), (1,'publish_fail',2,True),
        (4,'flush',0,False), (5,'flush',0,False), (9,'publish',0,False)])]:
    now = [0]; delay = [0]; failing = [False]; callbacks = []
    state = State()
    def callback(snapshot):
        callbacks.append(dict(packet_count=snapshot['packet_count'], phase=snapshot['phase']))
        now[0] += delay[0]
        if failing[0]: raise RuntimeError('synthetic callback failure')
    publisher = StatePublisher(callback, interval, clock=lambda:now[0])
    vector = dict(name=name, interval=interval, steps=[])
    for index, (timestamp, operation, elapsed, force) in enumerate(operations):
        apply(state, dict(type='login_result', result=index%2))
        now[0] = timestamp; delay[0] = elapsed; failing[0] = operation == 'publish_fail'
        error = False
        try:
            if operation == 'flush': publisher.flush(state)
            else: publisher.publish(state, force=force)
        except RuntimeError: error = True
        vector['steps'].append(dict(now=timestamp, operation=operation, delay=elapsed, force=force,
            result=index%2, error=error, expected=dict(last=publisher.last, pending=publisher.pending,
            callbacks=list(callbacks))))
    publishers.append(vector)

lines = ['// Generated by LocalStateGenerateVectors.py. Synthetic offline evidence only.',
         'namespace Lala.Core.Tests.State;', 'public static class LocalStatePythonVectors', '{']
for method, vectors in [('Sequences', sequences), ('Publishers', publishers)]:
    lines += ['    public static IEnumerable<object[]> ' + method + '()', '    {']
    for vector in vectors:
        payload = json.dumps(vector, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        lines.append('        yield return new object[] { ' + json.dumps(vector['name']) + ', '
                     + 'Decode(' + json.dumps(base64.b64encode(gzip.compress(payload.encode('utf-8'), mtime=0)).decode('ascii')) + ') };')
    lines += ['    }']
lines += ['    private static string Decode(string encoded)', '    {',
          '        using var input = new System.IO.MemoryStream(System.Convert.FromBase64String(encoded));',
          '        using var gzip = new System.IO.Compression.GZipStream(input, System.IO.Compression.CompressionMode.Decompress);',
          '        using var reader = new System.IO.StreamReader(gzip, System.Text.Encoding.UTF8);',
          '        return reader.ReadToEnd();', '    }', '}']
Path(__file__).with_name('LocalStatePythonVectors.cs').write_text('\n'.join(lines)+'\n', encoding='utf-8')
print(f'Generated {len(sequences)} sequences / {sum(len(v["steps"]) for v in sequences)} checkpoints '
      f'and {len(publishers)} publisher scenarios / {sum(len(v["steps"]) for v in publishers)} operations.')
