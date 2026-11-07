"""Offline session reducer differential evidence. Run from any directory with Python 3.

Uses the retained apply_session_event on real State and the retained wire decoder;
only relevant State fields are projected. No server, catalog, or credentials.
"""
import copy
import json
import os
from pathlib import Path
import random
import struct
import sys

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from wlre.core.state import State
from wlre.core.state_session_events import apply_session_event
from wlre.network.protocol import decode
from wlre.network.wire import Packet

FIELDS = ('phase', 'roles', 'gold', 'event_flow', 'npc_dialogue', 'initial_data_complete',
          'packet_count', 'unimplemented_count', 'attributes')

def project(state):
    snapshot = state.snapshot()
    result = {key: snapshot[key] for key in FIELDS}
    result['npc_dialogue'].setdefault('history', [])
    result['npc_dialogue'].setdefault('choice_continuation_pending', False)
    return result

def p(fmt, *values): return struct.pack('<' + fmt, *values)
def effect(kind=1, mean=42):
    return p('BHBBBHBIHBH', 255, 65535, 254, kind, 252, 65534, 251, 2**32-1, mean, 250, 65532)
def role(index, name):
    encoded = name.encode('utf-16-le')
    return (bytes([index, len(encoded)]) + encoded + p('BBIIIIqIBBIIBBHdB',
        15, 3, 500, 400, 300, 200, 123456789, 900, 1, 2, 3, 4, 0, 5, 60000, 0.5, 1)
        + p('IIIIHiiII', 1, 2, 3, 4, 5, -6, -7, 8, 9))

def npc(active=True, phase='awaiting_choice', **extra):
    return dict(active=active, phase=phase, choice_continuation_pending=True, history=[10, 11],
                scene=123, npc_id=456, npc_index=7, selected_choice=3, **extra)

vectors = []
class Scenario:
    def __init__(self, name, **initial):
        self.state = State(**initial)
        self.value = dict(name=name, initial=project(self.state), steps=[])
        vectors.append(self.value)
    def event(self, event, packet=None):
        # This is the caller's responsibility in State.apply, not apply_session_event.
        self.state.packet_count += 1
        apply_session_event(self.state, event)
        self.value['steps'].append(dict(event=event if packet is None else None,
                                       packet=packet, expected=project(self.state)))
        return self
    def packet(self, main, sub, payload=b''):
        return self.event(decode(Packet(main, sub, payload)), dict(main=main, sub=sub, hex=payload.hex().upper()))

s = Scenario('login_roles_initial_unknown', packet_count=30, unimplemented_count=2)
for result in (0, 1, 255, 0): s.packet(63, 7, bytes([result, 1]))
s.packet(26, 4, p('I', 400)).packet(1, 11).packet(1, 11)
s.packet(63, 1, role(1, '合成角色') + role(2, 'Offline')).packet(26, 1, p('IB', 3, 1))
s.packet(63, 1).packet(1, 23).packet(8, 4).packet(255, 255, b'fixture').packet(255, 254)

s = Scenario('gold_preinit_limit_overflow_recovery')
for main, sub, payload in [(26,1,p('IB',1,0)), (26,3,b''), (26,4,p('I',0)),
        (26,2,p('IB',0,1)), (26,2,p('IB',1,0)), (26,1,p('IB',1,0)),
        (26,4,p('I',2**32-1)), (26,1,p('IB',0,0)), (26,1,p('IB',1,1)),
        (26,4,p('I',50)), (26,3,b''), (26,2,p('IB',1,0)),
        (26,4,p('I',2**32-1)), (26,2,p('IB',2**32-1,0)),
        (26,1,p('IB',2**32-1,0)), (26,4,p('I',10))]: s.packet(main, sub, payload)
for ready in (False, True):
    for reliable in (False, True):
        for amount in (None, 4):
            s = Scenario(f'gold_evidence_{ready}_{reliable}_{amount}',
                gold=dict(ready=ready,reliable=reliable,amount=amount,revision=17,source='fixture'))
            s.packet(26,1,p('IB',0,0)).packet(26,4,p('I',2)).packet(26,2,p('IB',1,1))
for delta in (-2**63, 2**63-1):
    s = Scenario(f'gold_signed_extreme_{delta}', gold=dict(ready=True,reliable=True,amount=2**32-1,revision=2**80,source='fixture'))
    s.event(dict(type='gold_delta',sub=1,delta=delta,notify=False)).packet(26,4,p('I',0))

for kind in range(256):
    Scenario(f'effect_kind_{kind}', npc_dialogue=npc(text_id=99,option_index=100),
        event_flow=dict(blocked=False,awaiting_response=True,last_source='fixture',requests_sent=23)).packet(20,kind%6+1,effect(kind,kind))
for active in (False, True):
    s = Scenario(f'effects_sequence_active_{active}', npc_dialogue=npc(active=active), packet_count=2**80)
    s.packet(20,1,effect(1,65535)).packet(20,2,effect(6,42)).packet(20,3,effect(255,0))
    for length in range(18): s.packet(20,4,effect()[:length])
    for sub in (9,12,46,58,67,70): s.packet(20,sub,b'ignored extension')
    s.packet(20,5,effect(1,0)).packet(20,6,effect(6,65535))
s = Scenario('talk_history_bound_50', npc_dialogue=npc())
for mean in range(70): s.packet(20,mean%6+1,effect(1,mean))
s.packet(20,2,effect(6,300)).packet(20,3,b'').packet(20,8)
s = Scenario('history_trims_only_on_talk', npc_dialogue=dict(active=True,phase='talk',history=list(range(80))))
s.packet(20,1,effect(6,1)).packet(20,1,effect(0,1)).packet(20,1,effect(1,80))

for active in (False, True):
    for phase in ('requesting','awaiting_reply','awaiting_choice','continue','idle','talk',
                  'choice_unavailable','effect_unavailable','ended','rejected','closing'):
        s = Scenario(f'continue_{active}_{phase}', npc_dialogue=npc(active,phase),
            event_flow=dict(blocked=False,awaiting_response=True,last_source='fixture',requests_sent=2**70))
        for sub in (7,10,11,13,14,15,16,17): s.packet(20,sub,b'extension')
for active in (False, True):
    for terminal in (8,74):
        s = Scenario(f'terminal_{active}_{terminal}', npc_dialogue=npc(active),
            event_flow=dict(blocked=True,awaiting_response=True,last_source='fixture',requests_sent=3))
        s.packet(20,terminal,b'' if terminal==8 else b'\x03').packet(20,terminal,b'' if terminal==8 else b'\xff')
        s.packet(6,2,b'\xff').packet(20,74,b'\x01')
for kind in (0,1,255):
    for awaiting in (False,True):
        Scenario(f'movement_{kind}_{awaiting}',event_flow=dict(blocked=False,awaiting_response=awaiting,last_source=None,requests_sent=9)).packet(6,2,bytes([kind]))

s = Scenario('attributes_replacements_and_namespaces', attributes={'self':{'25:0':9,'55:3':111}, 'follow:1':{'25:0':222}})
for sub,prefix in ((1,b''),(2,p('BH',4,1)),(2,p('BH',255,65535)),(3,p('I',0)),(3,p('I',2**32-1))):
    for kind in (0,25,36,55,255):
        for parameter in (0,1,2**32-1):
            for sign,amount in ((0,5),(1,2),(2,2**32-1),(1,0)):
                s.packet(8,sub,prefix+p('BBII',kind,sign,amount,parameter))
s.packet(255,255).packet(255,255)
Scenario('unbounded_unknown_counter',unimplemented_count=2**90).packet(255,255)

rng = random.Random(20261107)
for number in range(8):
    s = Scenario(f'mixed_replay_{number}', npc_dialogue=npc(number%2==0))
    for _ in range(80):
        kind = rng.randrange(9)
        if kind==0: s.packet(26,4,p('I',rng.randrange(2**32)))
        elif kind==1: s.packet(26,rng.choice((1,2)),p('IB',rng.randrange(2**32),rng.randrange(2)))
        elif kind==2: s.packet(26,3)
        elif kind==3: s.packet(20,rng.randrange(1,7),effect(rng.choice((1,6,255)),rng.randrange(65536)))
        elif kind==4: s.packet(20,rng.choice((7,10,17)))
        elif kind==5: s.packet(20,8)
        elif kind==6: s.packet(20,74,bytes([rng.randrange(5)]))
        elif kind==7: s.packet(8,1,p('BBII',rng.randrange(256),rng.randrange(3),rng.randrange(2**32),rng.randrange(8)))
        else: s.packet(255,255)

# Bounded generated source files keep review/build/upload units manageable.
rows = []
for value in vectors:
    payload = json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    rows.append('        yield return new object[] { ' + json.dumps(value['name']) + ', ' + json.dumps(payload,ensure_ascii=False) + ' };')
groups = []
for row in rows:
    if not groups or sum(len(x.encode('utf-8')) for x in groups[-1]) + len(row.encode('utf-8')) > 180_000:
        groups.append([])
    groups[-1].append(row)
root = Path(__file__).parent
for old in root.glob('SessionEventPythonVectors.Part*.cs'):
    old.unlink()
header = ['// Generated by SessionEventGenerateVectors.py; synthetic Python evidence only.',
          'namespace Lala.Core.Tests.Sessions;', 'public static partial class SessionEventPythonVectors', '{']
main = header + ['    public static IEnumerable<object[]> Sequences()', '    {']
for number, group in enumerate(groups, 1):
    method = f'Part{number:02d}'
    main.append(f'        foreach (var row in {method}()) yield return row;')
    part = header + [f'    private static IEnumerable<object[]> {method}()', '    {'] + group + ['    }', '}']
    (root / f'SessionEventPythonVectors.Part{number:02d}.cs').write_text('\n'.join(part)+'\n',encoding='utf-8')
(root / 'SessionEventPythonVectors.cs').write_text('\n'.join(main + ['    }','}'])+'\n',encoding='utf-8')
print(f'Generated {len(vectors)} sequences, {sum(len(x["steps"]) for x in vectors)} checkpoints in {len(groups)} parts.')
