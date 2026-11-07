"""Deterministic synthetic differential evidence, never a live capture.

Runs the real Python defaults/apply_instances, S85/S186 decoder, and all six receive
observers. Only monotonic time and the caller-declared entry catalog are injected.
No command, timeout, disconnect, scheduler, transport, UI or hero challenge is run.
Source hashes normalize CRLF byte pairs only (not Unicode or lone CR/newline bytes).
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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
from wlre.network.instances import decode_instances
from wlre.network.wire import Packet, ProtocolError
from wlre.services.instances import defaults, apply_instances

SOURCES = ['wlre/network/wire.py', 'wlre/network/instances.py', 'wlre/services/instances.py'] + [
    'wlre/services/instance_' + name + '.py' for name in ('creation', 'room_flow', 'standby', 'start', 'entry', 'rewards')]


def pack(fmt, *v): return struct.pack('<' + fmt, *v)
def text(s):
    b = s.encode('utf-16le'); return bytes([len(b)]) + b

def phase(kind=1, room=500, host=42, count=2):
    return (85, 5, pack('BBHBI', 1, 0, room, count, host) if kind == 1 else pack('BI', 5, host) if kind == 5 else bytes([kind]))
def members(room=500, roles=(42, 7)):
    return (85, 4, pack('HB', room, len(roles)) + b''.join(pack('I', r) for r in roles))
def coop(room=9, roles=(42, 7), kind=2, npc=1, standby=False, created=True, joined=True):
    return (186, 3, pack('BBHBBBB', created, joined, room, standby, kind, npc, len(roles)) +
            b''.join(pack('IBIIII', r, i, 100+i, 200+i, 30+i, 40+i) for i, r in enumerate(roles)))
def reward(count=3, win=3, opened=1, mark=1, npc=1): return (186, 11, bytes([count, win, opened, mark, npc]))
def result(code, *, main=False, action='create'):
    return (85, 2 if action == 'create' else 3, bytes([code])) if main else (186, 2, bytes([code]) + (pack('I', 42) if code in (16, 19) else b''))
def match(kind=18):
    return (186, 2, bytes([18, 1]) + pack('II', 42, 7)) if kind == 18 else (186, 2, bytes([17, 1])+pack('I', 77)+bytes(12)+text('敵人'))
def new(kind, payload=b''): return (85, 21, bytes([kind])+payload)
def location(role=42, scene=500, world=False):
    return {'type': 'world_player', 'player': {'role_id': role, 'scene': scene}} if world else {'type': 'position_snapshot', 'role_id': role, 'scene': scene}
def normalize(v):
    if isinstance(v, tuple): return {'$tuple': [normalize(x) for x in v]}
    if isinstance(v, dict): return {str(k): normalize(x) for k, x in v.items()}
    if isinstance(v, list): return [normalize(x) for x in v]
    return v

sequences = []
covered = set()
class Scenario:
    def __init__(self, name, main=None, coop=None, own=42, catalog=(500,)):
        self.state = SimpleNamespace(instances=defaults(), player={'role_id': own})
        for mode, seed in [('main', main), ('coop', coop)]:
            self.state.instances[mode].update(copy.deepcopy(seed or {}))
        self.catalog = catalog
        self.now = 100.25
        self.value = dict(name=name, own=own, catalog=catalog, initial=normalize(copy.deepcopy(self.state.instances)), steps=[])
        sequences.append(self.value)
    def step(self, item, at=None):
        self.now = self.now + .25 if at is None else at
        step = {'at': self.now, 'error': False}
        try:
            if isinstance(item, tuple):
                main, sub, payload = item
                step.update(main=main, sub=sub, hex=payload.hex())
                event = decode_instances(Packet(main, sub, payload))
            else:
                event = copy.deepcopy(item); step['event'] = event
        except ProtocolError:
            step['error'] = True
        else:
            if event is not None:
                covered.add((event['type'], event.get('mode'), event.get('kind')))
                with patch('time.monotonic', return_value=self.now), patch('wlre.services.instance_entry.entries_for',
                        return_value=[{'kind': 1, 'map_id': x} for x in self.catalog]):
                    apply_instances(self.state, event)
        step['expected'] = normalize(copy.deepcopy(self.state.instances))
        self.value['steps'].append(step)
        return self
    def reset(self):
        self.state.instances = defaults()
        self.value['steps'].append({'reset': True, 'expected': normalize(copy.deepcopy(self.state.instances))})
        return self

s = Scenario('main room roster order, duplicates, ignored orphans, lists and departure')
s.step(members()).step((85, 7, pack('BIH', 2, 7, 500))).step((85, 12, pack('BIII', 1, 42, 7, 0)))
listing = (85, 1, b'\x02' + (pack('H', 500)+text('團長')+b'\x02'+text('組織')+b'\x01'+pack('H', 65535))*2)
s.step(listing, at=0).step(listing, at=-4).step((85, 1, b'\x00'))
s.step(phase()).step(members(501)).step(members()).step((85, 7, pack('BIH', 3, 42, 500)))
s.step((85, 7, pack('BIH', 3, 42, 500))).step((85, 12, pack('BIII', 2, 7, 42, 1)))
s.step(phase(5, host=77)).step((85, 9, b'\x01'+pack('I', 0xffffffff))).step((85, 17, b''))
s.step((85, 12, pack('BIII', 0, 42, 7, 0))).step(phase(3)).step((85, 15, b'')).step(phase(2)).step(phase(4)).reset()

s = Scenario('objective source clamps, repeated score evidence and sticky boss completion')
objective_steps = [
    (85, 10, b'\x01\x01\x09'+text('角色')), (85, 10, b'\x03\x01\x04'+pack('H', 900)),
    (85, 10, b'\x01\x01\xff'+text('第二人')), (85, 10, b'\x02\x00'+text('未擊敗')),
    (85, 10, b'\x02\x01'+text('擊敗')), (85, 10, b'\x04'+pack('H', 901)),
    (85, 10, b'\x02\x00'+text('仍擊敗')), (85, 10, b'\x05\x03'+pack('III', 42, 42, 0xffffffff)),
    (85, 10, b'\x06\x02'+pack('II', 42, 7)), (85, 10, b'\x05\x00')]
for p in objective_steps + objective_steps: s.step(p)
s.step((85, 15, b'')).step(phase()).step(members()).step(phase(3)).step(location()).step({'type': 'battle_start'}).step((85, 15, b'')).step(phase(4))

s = Scenario('new dungeon every branch and same-scene reset boundary')
info = new(0, pack('BBHIBI', 2, 1, 600, 42, 1, 0xffffffff))
s.step(info).step(new(1, pack('BI', 7, 123))).step(new(2, pack('I', 0xffffffff)))
s.step(new(4, b'\x01\x02'+text('missing'))).step(new(3, pack('BHBB', 1, 901, 2, 9)))
for _ in range(4): s.step(new(4, b'\x01\x02'+text('tester')))
s.step(new(5, pack('H', 901))).step(new(98, pack('H', 123)+text('公告')+pack('H', 902)))
s.step(new(100, b'\x02'+pack('IBBIBB', 42, 3, 5, 7, 2, 1))).step(info)
for k in (99, 101, 102): s.step(new(k))
s.step(new(0, pack('BBHIBI', 1, 0, 601, 42, 0, 5))).step(new(6)).step(new(100, b'\x00'))

# Full byte-code matrices exercise source rejection tables and unknown-code paths.
for code in range(256):
    for action in ('create', 'join'):
        pending = {'map_id': 500, 'started': 10, 'ack': False} if action == 'create' else {'room_id': 500, 'started': 10, 'accepted': False}
        s = Scenario(f'main {action} code {code}', main={action+'_pending': pending})
        s.step(result(code, main=True, action=action)).step(phase()).step(result(code, main=True, action=action))
    if code not in (17, 18):
        for action in ('create', 'join'):
            pending = {'kind': 2, 'npc_id': 1, 'started': 10, 'ack': False} if action == 'create' else {'room_id': 9, 'started': 10, 'accepted': False}
            s = Scenario(f'coop {action} code {code}', coop={action+'_pending': pending})
            s.step(result(code)).step(coop()).step(result(code))

s = Scenario('main mismatched creation host and room cannot confirm', main={'create_pending': {'map_id': 500, 'ack': False}})
s.step(phase(room=501)).step(phase(host=7)).step(phase()).step(result(0, main=True)).step(phase())
for seed in (False, True):
    s = Scenario(f'main late create no attempt recovery {seed}', main={'create_uncertain': seed, 'create_attempt': {'map_id': 500}})
    s.step(phase()).step(result(0, main=True))
for roles in ((7, 42), (0, 42), (), (42,), (42, 42)):
    s = Scenario(f'coop creation late first-slot identity {roles}', coop={'create_uncertain': True, 'create_attempt': {'kind': 2, 'npc_id': 1}})
    s.step(coop(roles=roles, created=False)).step(coop(kind=1)).step(coop(npc=2)).step(coop(created=False))

s = Scenario('typed coop member observation uses missing-host fallback', coop={
    'create_uncertain': True, 'create_attempt': {'kind': 2, 'npc_id': 1}})
missing_host = decode_instances(Packet(*coop()))
missing_host['host_id'] = None
s.step(missing_host)

for mode in ('main', 'coop'):
    for uncertainty in (False, True):
        seed = {'leave_pending': {'room_id': 500 if mode == 'main' else 9}, 'leave_uncertain': uncertainty}
        s = Scenario(f'leave resolves {mode} uncertainty {uncertainty}', **{mode: seed})
        s.step(phase() if mode == 'main' else coop())
        s.step((85, 12, pack('BIII', 0, 42, 7, 0)) if mode == 'main' else (186, 13, b''))
        s.step(phase(4) if mode == 'main' else (186, 13, b''))
for pending in (True, False):
    for target in (True, False):
        seed = {'standby_pending' if pending else 'standby_attempt': {'room_id': 9, 'target': target}, 'standby_uncertain': not pending}
        s = Scenario(f'standby target {target} pending {pending}', coop=seed)
        s.step((186, 20, bytes([target]))).step(coop(room=10, standby=target)).step(coop(standby=not target)).step(coop(standby=target)).step((186, 13, b''))
        Scenario(f'standby exit uncertain {target} {pending}', coop=seed).step((186, 13, b'')).step(coop(standby=target))
Scenario('no standby recovery without uncertain attempt', coop={'standby_attempt': {'room_id': 9, 'target': True}}).step(coop(standby=True))

for ending in (2, 3, 4):
    s = Scenario(f'start and entry precedence end={ending}', main={'start_pending': {'room_id': 500}, 'enter_pending': {'room_id': 500}, 'start_uncertain': True})
    s.step(phase()).step(phase(ending)).step(phase(ending))
Scenario('start wrong pending room', main={'start_pending': {'room_id': 501}}).step(phase()).step(phase(3))
for world in (False, True):
    for own in (42, None):
        for catalog in ((), (500,), (501,)):
            s = Scenario(f'entry role={own} world={world} catalog={catalog}', own=own, catalog=catalog,
                         main={'enter_pending': {'room_id': 500}, 'enter_uncertain': True})
            s.step(location(world=world)).step(phase()).step(location(world=world)).step(phase(3))
            s.step(location(role=7, world=world)).step(location(scene=501, world=world)).step(location(world=world))
            s.step({'type': 'battle_start'}).step(location(world=world)).step({'type': 'fight_exit', 'role_id': 7})
            s.step({'type': 'winner', 'side': 1}).step({'type': 'winner', 'side': 2}).step({'type': 'battle_start'})
            s.step({'type': 'fight_exit', 'role_id': 42}).step((85, 15, b'')).step(location(world=world))

for standby in (None, False, True):
    for pending in (None, {'room_id': 9, 'target': True}, {'room_id': 9, 'target': False}):
        s = Scenario(f'coop match standby={standby} pending={pending}', coop={'standby': standby, 'standby_pending': pending})
        s.step(match()).step(coop(standby=bool(standby))).step(match(17)).step({'type': 'battle_start'})
        s.step(coop(standby=True)).step({'type': 'fight_exit', 'role_id': 7}).step({'type': 'winner', 'side': 1})
        s.step(match()).step({'type': 'battle_start'}).step((186, 15, b'\x03')).step((186, 15, b'\x03'))
        s.step({'type': 'fight_exit', 'role_id': 42}).step(coop(room=10)).step((186, 13, b''))
Scenario('main room blocks coop match', main={'room': {'room_id': 500}}, coop={'standby': True}).step(coop(standby=True)).step(match()).step({'type': 'battle_start'})

fp = (3, 3, 1, 1, 1)
award = {'kind': 1, 'id': 111, 'value': 3}
receipt = (186, 10, pack('BII', 1, 111, 3))
for op in (None, 'claim', 'cancel'):
    for uncertain in (False, True):
        for received in ([], [award]):
            seed = {'reward_uncertain': uncertain, 'received_awards': received, 'reward_handled_fingerprint': fp}
            if op: seed[op+'_pending'] = {'fingerprint': fp, 'started': 10}
            s = Scenario(f'reward receipt op={op} uncertain={uncertain} received={len(received)}', coop=seed)
            s.step(reward()).step(result(15)).step((186, 10, b'')).step(receipt).step(receipt).step(reward(opened=0))
            s.step(reward(count=0, win=0, opened=2)).step(reward(opened=255)).step((186, 13, b''))
            s = Scenario(f'reward close first op={op} uncertain={uncertain} received={len(received)}', coop=seed)
            s.step(reward(opened=0)).step(receipt).step(reward(opened=1)).step((186, 13, b''))
            s = Scenario(f'reward room exit first op={op} uncertain={uncertain} received={len(received)}', coop=seed)
            s.step((186, 13, b'')).step(receipt).step(reward(opened=0))
for unresolved in (None, 'claim_pending', 'cancel_pending', 'reward_uncertain'):
    seed = {'received_awards': [award], 'mail_notice': True, 'reward_handled_fingerprint': fp, 'claim_result': 'prior', 'cancel_result': 'prior'}
    if unresolved: seed[unresolved] = True if unresolved == 'reward_uncertain' else {'fingerprint': fp}
    s = Scenario(f'reward before first roster and room changes {unresolved}', coop=seed)
    s.step(reward()).step(coop()).step(coop()).step(coop(room=10)).step(coop(room=9))

s = Scenario('cooperative list snapshots and refresh requests')
s.step((186, 17, pack('HBBBHBBI', 1, 1, 2, 1, 9, 4, 2, 42))).step((186, 6, pack('H', 9)))
s.step((186, 17, b'\0\0')).step((186, 20, b'\x01')).step((186, 20, b'\x00'))

# Every strict instance payload truncation/trailing-byte error is decoded before reduction.
valid_packets = [listing, phase(), phase(2), phase(5), members(), coop(), reward(), receipt,
    result(0, main=True), result(16), match(), match(17), *objective_steps, info,
    new(1, pack('BI', 1, 3)), new(2, pack('I', 3)), new(3, pack('BHBB', 1, 900, 4, 1)),
    new(4, b'\x01\x02'+text('a')), new(5, pack('H', 9)), new(6), new(98, pack('H', 1)+text('a')+pack('H', 9)),
    new(100, b'\x01'+pack('IBB', 42, 1, 2)), new(99), (186, 15, b'\x03'), (186, 20, b'\1'), (186, 13, b''),
    (85, 12, pack('BIII', 1, 42, 7, 0)), (85, 7, pack('BIH', 3, 42, 500)), (85, 9, b'\1'+pack('I', 1)), (85, 15, b''), (85, 17, b'')]
for main, sub, payload in valid_packets:
    assert decode_instances(Packet(main, sub, payload)) is not None, (main, sub, payload.hex())
for i, (main, sub, data) in enumerate(valid_packets):
    s = Scenario(f'malformed bounded packet {i}', coop={'reward_uncertain': True})
    for cut in range(len(data)): s.step((main, sub, data[:cut]))
    s.step((main, sub, data+b'\xff'))
s = Scenario('unknown keys and count limits stay unchanged')
for p in [(85, 255, b''), (186, 255, b''), (85, 5, b'\xff'), (85, 10, b'\xff'), new(255), (85, 9, b'\xff'),
          (85, 1, b'\xc9'), (85, 4, b'\0\0\x11'), (85, 10, b'\5\x11'), new(100, b'\x11'),
          (186, 17, pack('H', 1001)), (186, 2, b'\x12\0'), (186, 2, b'\x11\x09'), (186, 10, bytes(45)),
          (186, 3, b'\0\0\0\0\0\0\0\x09')]: s.step(p)

# Long randomized valid streams retain every historical immutable publication in C#.
rng = random.Random(186085)
pool = [p for p in valid_packets if p[0:2] not in [(85, 7)]] + [location(), {'type': 'battle_start'}, {'type': 'winner', 'side': 2}]
for n in range(20):
    s = Scenario(f'random receive stream {n}')
    for _ in range(70): s.step(rng.choice(pool))

for kind in range(1, 7):
    assert ('instance_objective', 'main', kind) in covered, kind
for kind in (0, 1, 2, 3, 4, 5, 6, 98, 99, 100, 101, 102):
    assert ('instance_new_info', 'main', kind) in covered, kind
for kind in range(1, 6):
    assert ('instance_phase', 'main', kind) in covered, kind
for kind in (17, 18):
    assert ('instance_coop_match', 'coop', kind) in covered, kind

metadata = {'sources': {p: hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in SOURCES},
            'covered': sorted([list(x) for x in covered], key=repr), 'scenarios': len(sequences),
            'steps': sum(len(s['steps']) for s in sequences)}
raw = json.dumps({'metadata': metadata, 'sequences': sequences}, ensure_ascii=False, separators=(',', ':')).encode()
data = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
chunks = '\n'.join('        "'+data[i:i+120]+'"'+(' +' if i+120<len(data) else ';') for i in range(0, len(data), 120))
out = '''// Generated by generate_instance_receive_vectors.py. Synthetic offline evidence only.
using System.IO.Compression;
using System.Text.Json;
namespace Lala.Core.Tests.Instances;
public static class PythonInstanceReceiveVectors
{
    private static JsonDocument Open()
    {
        using var bytes = new MemoryStream(Convert.FromBase64String(Data));
        using var gzip = new GZipStream(bytes, CompressionMode.Decompress);
        return JsonDocument.Parse(gzip);
    }
    public static IEnumerable<object[]> Sequences()
    {
        using var document = Open();
        foreach (var sequence in document.RootElement.GetProperty("sequences").EnumerateArray())
            yield return new object[] { sequence.GetProperty("name").GetString()!, sequence.GetRawText() };
    }
    public static string Metadata()
    {
        using var document = Open();
        return document.RootElement.GetProperty("metadata").GetRawText();
    }
    private const string Data =
'''+chunks+'\n}\n'
assert len(out.encode()) < 500_000, len(out.encode())
Path(__file__).with_name('PythonInstanceReceiveVectors.cs').write_text(out, encoding='utf-8', newline='\n')
print(json.dumps(metadata, ensure_ascii=False, indent=2))
print(f'Fixture {len(out.encode())} bytes; raw {len(raw)} bytes')
