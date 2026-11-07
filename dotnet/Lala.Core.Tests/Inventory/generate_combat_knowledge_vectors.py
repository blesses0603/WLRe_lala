"""Synthetic remaining apply_live parity, before local dispatch; no network/catalog activation."""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import sys
from types import SimpleNamespace

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'TestSupport'))
from gzip_json_fixture import csharp_gzip_json
from wlre.services.items import combat_resources
from wlre.services.items.live_combat_catalog import _pinned
from wlre.core.state_battle_events import apply_battle_event, BATTLE_KINDS
from wlre.core.state_session_events import apply_session_event
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError

RNG = random.Random(202611080119)
NPCS = {'1': {'skills': [1001, 0, 1002, 1001, 0]}, '2': {'skills': [1002]}}
CATALOGS = [
    dict(keys={}, items={}),
    dict(keys={'1': 1001, '2': 1002, '3': 1001, '4': 0}, items={'42': {'fit_type': 3}, '43': {'fit_type': 11}, '44': {'fit_type': 0}, '45': {'fit_type': 9}}),
    dict(keys={'1': 2001, '2': 1002, '3': 1001}, items={'42': {'fit_type': 3}, '43': {'fit_type': 11}, '44': {'fit_type': 0}, '45': {'fit_type': 9}, '99': {'fit_type': 3}, '100': {'fit_type': 2}}),
    dict(keys={}, items={'99': {'fit_type': 3}, '100': {'fit_type': 2}}),
]
for catalog in CATALOGS: catalog.update(npcs=NPCS, skills={}, characters=[], element_weights={})
SCENARIOS = []

def pack(fmt, *values): return struct.pack('<' + fmt, *values)

def item(item_id=42, serial=9):
    return (pack('HBBIHddBBHBHI', item_id, 254, 2, serial, 65535, -123.5, 1e-100, 255, 254, 65535, 253, 65533, 0xffffffff) +
        b''.join(pack('BH', i, 65535-i) for i in range(4)) + pack('BBB', 3, 255, 254))

def companion(index=1, npc=1):
    data = pack('BHiBiHHHHHHBBBH', index, npc, -2147483648, 254, -2147483648, 65535, 303, 101, 202, 505, 404, 0, 255, 254, 65535) + b'\x00'
    data += b''.join(pack('BI', level, value) for level, value in [(3,4),(0,0xffffffff),(255,1),(2,5),(1,6)])
    return data + b''.join(item(42+i) for i in range(9)) + pack('BBBBHBH', 255, 253, 2, 255, 65535, 255, 65535)

def player(records=((1,3,9),(2,0,0),(3,7,8),(4,1,0),(999,9,9))):
    return (pack('BIHHHHHHBIHHIH', 255, 0xffffffff, 65535, 101, 202, 303, 404, 505, 254, 0xffffffff, 65535, 65534, 0xffffffff, 65535) +
        pack('IIIIII', *range(0xfffffff9, 0xffffffff)) + bytes(range(12)) + pack('H', len(records)) +
        b''.join(pack('HBI', *row) for row in records) + pack('HHBBB', 65535, 65534, 1, 255, 254))

def unit(pid=7, master=0, npc=0, col=1, row=1, hp=300):
    return (pack('BBIHIBBIHIHBBBBHHBBII', 9, 4, pid, npc, master, col, row, 0xffffffff, 65535, hp, 9, 21, 2, 1, 0, 0, 0, 1, 2, 0, 0) +
        b'\x00' + b''.join(pack('HI', i+42, i+100) for i in range(9)))

def attr(kind=25, value=999, parameter=0): return pack('BBII', kind, 2 if value < 0 else 1, abs(value), parameter)

def initial():
    return SimpleNamespace(inventory=dict(ready=False,reliable=False,items={},reserved={},revision=0,use_failed=False),
        knowledge=dict(player=dict(ready=False,skills={},stats={}),companions={},companions_ready=False,active_npc_id=None),
        attributes={}, player={'role_id':7}, battle_units={}, battle={}, battle_count=0)

def project(state):
    return copy.deepcopy(dict(player=state.knowledge['player'], player_skill_order=list(state.knowledge['player']['skills']), companions=state.knowledge['companions'],
        companion_order=list(state.knowledge['companions']), units=state.battle_units, unit_order=list(state.battle_units), attributes=state.attributes))

class Scenario:
    def __init__(self,name):
        self.name=name; self.state=initial(); self.catalog=0; self.steps=[]; self.record(None)
    def record(self,operation,error=None): self.steps.append(dict(operation=operation,error=error,expected=project(self.state)))
    def packet(self,main,sub,payload=b''):
        operation=dict(main=main,sub=sub,hex=payload.hex())
        _pinned.set(CATALOGS[self.catalog])
        try:
            event=decode(Packet(main,sub,payload))
            combat_resources.apply_live(self.state,event)
            if event['type'] in BATTLE_KINDS: apply_battle_event(self.state,event)
            if event['type']=='attribute_set': apply_session_event(self.state,event)
            self.record(operation)
        except ProtocolError as exc: self.record(operation,str(exc))
        return self
    def cat(self,index): self.catalog=index; self.record(dict(catalog=index)); return self
    def role(self,value): self.state.player={'role_id':value} if value is not None else {}; self.record(dict(role=value)); return self
    def reset(self): self.state=initial(); self.record(dict(reset=True)); return self
    def finish(self): SCENARIOS.append((self.name,self.steps)); return self
    def equips(self,*ids): return self.packet(23,11,b''.join(item(value,9+i) for i,value in enumerate(ids)))
    def equip(self,owner=7,npc=0,index=3,item_id=99,design=123): return self.packet(11,252,pack('IBBHI',owner,npc,index,item_id,design))
    def damage(self,index=3,value=17,npc=0): return self.packet(23,140,pack('BBBIB',1,2,index,value,npc))
    def broken(self,item_id=42,npc=0): return self.packet(23,35,pack('BH',npc,item_id))
    def units(self,*values,start=False): return self.packet(11,250 if start else 5,(b'\x01\x02' if start else b'')+pack('B',len(values))+b''.join(values))

s=Scenario('player_skill_evidence_replaces_but_stats_merge')
s.packet(8,1,attr(41,-1)).packet(8,1,attr(110,8,1001)).packet(8,1,attr(110,0,1002))
s.packet(5,3,player()).cat(1).packet(255,255).packet(5,3,player()).packet(8,1,attr(110,-1,1001))
s.packet(8,1,attr(110,0,1001)).packet(8,1,attr(110,9,1001)).packet(5,3,player(())).finish()
s=Scenario('all_self_attributes_star_and_nonself_ignored').cat(1)
for kind in [25,26,27,28,29,30,33,35,36,38,39,41,43,46,47,205,206,110,255]:
    s.packet(8,1,attr(kind,-0xffffffff,0xffffffff)).packet(8,3,pack('I',7)+attr(kind,123,1002))
s.packet(5,47,pack('BBq',255,254,-2**63)+bytes(30)).packet(5,3,player()).packet(5,47,pack('BBq',0,0,2**63-1)+bytes(30)).finish()

s=Scenario('late_catalog_partial_resolution_fit11_duplicates_and_sparse_replay').cat(1)
s.equips(42,99,43,100,44,45,42).damage().broken(43).equip(item_id=42,design=888).equip(item_id=45)
s.cat(3).packet(255,255).damage(index=2,value=0xffffffff).cat(2).packet(255,255)
s.equip(item_id=42,design=11).equip(item_id=42,design=99).damage().broken().equips().finish()

s=Scenario('unknown_player_equipment_waits_until_all_rows_resolve').equips(99,100)
s.damage().equip().cat(3).packet(255,255).cat(1).equips(99,100).damage().cat(2).packet(27,1,b'\x00').finish()

for overflow in ['damage','battle']:
    s=Scenario('deferred_256_boundary_and_overflow_'+overflow).cat(1).equips(42,99)
    for i in range(256): s.damage(value=i) if overflow=='damage' else s.equip(item_id=45 if i%2 else 42,design=i)
    s.damage(value=0xffffffff) if overflow=='damage' else s.equip(item_id=100,design=999)
    s.cat(2).packet(255,255).damage().equip().equips(99).damage().finish()

s=Scenario('profile_identity_battle_stats_and_equipment_are_distinct').cat(1)
s.packet(15,8,companion()).equips(42).units(unit(),unit(1,7,1,2),unit(1,8,1,3),unit(2,7,1,4),start=True)
s.packet(51,1,pack('BBBI',1,1,25,0xffffffff)+pack('BBBI',2,1,47,123)+pack('BBBI',3,1,26,55)+pack('BBBI',4,1,25,44))
s.damage(npc=1).broken(npc=1).equip(npc=1,item_id=99).equip(npc=1,item_id=99,design=999)
s.equip(owner=8,npc=1).equip(owner=8).packet(11,1,b'\x01\x01').equip(item_id=45)
s.units(unit(7,0,0,1,hp=200)).units(unit(7,0,0,2,hp=400)).units(unit(1,7,1,2,hp=500))
s.packet(15,8,companion(npc=2)).packet(51,1,pack('BBBI',2,1,25,12)).units(unit(2,7,1,2,hp=600))
s.packet(15,2,pack('IBB',7,1,0)).equip(npc=1).units(start=True).packet(51,1,pack('BBBI',1,1,25,77)).finish()

s=Scenario('unknown_and_changed_roles_do_not_borrow_companion_stats').cat(1).role(None)
s.equips(42).packet(15,8,companion()).units(unit(),unit(1,7,1,2),start=True).equip().role(8).equip().role(7)
s.units(unit(7,8,1,1,hp=13),unit(1,7,1,2,hp=15)).role(1).units(unit(1,99,99,1,hp=123)).finish()

s=Scenario('fresh_s15_clears_current_equipment_but_same_identity_replays_s8').cat(1)
s.packet(8,2,pack('BH',4,1)+attr(25,345)).packet(15,8,companion()).damage(npc=1).equip(npc=1)
s.packet(15,8,companion()).damage(npc=2).broken(npc=2).packet(15,8,companion(npc=2)).finish()

s=Scenario('malformed_packet_is_atomic_including_pending_equipment').cat(1).equips(99).damage().cat(2)
for main,sub,payload in [(5,3,player()),(5,47,pack('BBq',1,2,-1)+bytes(30)),(23,11,item()),(23,27,b'\x03\x01'),
    (23,28,b'\x01\x03\xff'),(23,35,pack('BH',0,42)),(11,252,pack('IBBHI',7,0,3,99,1)),
    (8,1,attr()),(11,250,b'\x01\x02\x01'+unit())]:
    for cut in sorted({0,1,len(payload)//2,len(payload)-1}): s.packet(main,sub,payload[:cut])
    s.packet(main,sub,payload+b'\x7f')
for index in [0,10,255]: s.equip(index=index).damage(index=index)
s.packet(51,1,b'\x01').packet(255,255).finish()

for number in range(30):
    s=Scenario('mixed_arrival_order_'+str(number))
    for step in range(30):
        op=RNG.randrange(14)
        if op==0: s.cat(RNG.randrange(4))
        elif op==1: s.equips(*RNG.choices([42,43,44,45,99,100],k=RNG.randrange(5)))
        elif op==2: s.damage(RNG.choice([0,1,3,7,9,255]),RNG.choice([0,250,0xffffffff]),RNG.choice([0,1,2]))
        elif op==3: s.broken(RNG.choice([42,43,99,100]),RNG.choice([0,1,2]))
        elif op==4: s.equip(RNG.choice([7,8]),RNG.choice([0,1,2]),RNG.choice([0,1,3,9,10]),RNG.choice([42,45,99]))
        elif op==5: s.packet(5,3,player(RNG.choices([(1,3,4),(2,1,9),(3,7,8),(1,0,0),(999,1,1)],k=RNG.randrange(6))))
        elif op==6: s.packet(8,1,attr(RNG.choice([25,26,41,110,205]),RNG.choice([-1,0,123,0xffffffff]),RNG.choice([1001,1002])))
        elif op==7: s.packet(15,8,companion(RNG.choice([1,2]),RNG.choice([1,2])))
        elif op==8: s.units(unit(),unit(RNG.choice([1,2]),7,RNG.choice([1,2]),2,hp=RNG.randrange(999)),start=bool(RNG.randrange(2)))
        elif op==9: s.packet(51,1,pack('BBBI',RNG.choice([1,2,3]),1,RNG.choice([25,26,46,47,205]),RNG.randrange(9999)))
        elif op==10: s.reset()
        elif op==11: s.packet(8,2,pack('BH',RNG.choice([4,9]),1)+attr(110,RNG.choice([-1,0,7]),1001))
        elif op==12: s.role(RNG.choice([None,1,7,8]))
        else: s.packet(255,255)
    s.finish()

sources=['wlre/services/items/combat_resources.py','wlre/services/items/live_combat_catalog.py',
    'wlre/core/state_battle_events.py','wlre/core/state_session_events.py','wlre/network/live_data.py',
    'wlre/network/layouts.py','wlre/network/protocol.py','wlre/network/wire.py']
provenance={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sources}
# Keep each generated publication unit below the repository's bounded upload size.
# Partition only between cases: gzip bytes, logical payloads, and sequence order stay intact.
MAX_GENERATED_BYTES = 500_000
HEADER = ['// Generated by generate_combat_knowledge_vectors.py. Synthetic offline receive-only parity.',
    'namespace Lala.Core.Tests.Inventory;', 'public static partial class CombatKnowledgePythonVectors', '{']
entries = ['        yield return new object[] { '+json.dumps(name)+', '+
    csharp_gzip_json(json.dumps(steps,ensure_ascii=False,separators=(',',':'),allow_nan=False))+' };'
    for name,steps in SCENARIOS]


def render_part(index, rows):
    return ('\n'.join(HEADER + [f'    private static IEnumerable<object[]> SequencesPart{index:02d}()', '    {'] +
        rows + ['    }', '}']) + '\n').encode('utf-8')


parts = []
current = []
for entry in entries:
    index = len(parts) + 1
    if current and len(render_part(index, current + [entry])) > MAX_GENERATED_BYTES:
        parts.append(current)
        current = []
        index += 1
    if len(render_part(index, [entry])) > MAX_GENERATED_BYTES:
        raise ValueError('One combat knowledge sequence exceeds the generated-file byte limit.')
    current.append(entry)
if current:
    parts.append(current)

output = Path(__file__).with_name('CombatKnowledgePythonVectors.cs')
lines = HEADER + [
    '    public const string SourceSha256 = '+json.dumps(json.dumps(provenance,separators=(',',':')))+';',
    '    public static IEnumerable<object[]> Sequences()', '    {']
for index in range(1, len(parts) + 1):
    lines.append(f'        foreach (var row in SequencesPart{index:02d}()) yield return row;')
lines += ['    }', '}']
generated = {output: ('\n'.join(lines)+'\n').encode('utf-8')}
for index,rows in enumerate(parts, 1):
    generated[output.with_name(f'{output.stem}.Part{index:02d}.cs')] = render_part(index, rows)
for path,payload in generated.items():
    assert len(payload) <= MAX_GENERATED_BYTES, path
    path.write_bytes(payload)
# A changed future partition must not leave obsolete partial-class methods behind.
for stale in output.parent.glob(f'{output.stem}.Part*.cs'):
    if stale not in generated:
        stale.unlink()
print(f'{len(SCENARIOS)} sequences; {sum(len(s) for _,s in SCENARIOS)} snapshots; '
    f'{len(generated)} generated files; max {max(map(len, generated.values()))} bytes')
