"""Retained decoder + apply_live + efficiency observer; explicit offline times only.

Six sequences supply captured post-live knowledge; five also run dispatch_local and
verify C# receive/local slices plus the projector. This is not the complete State.apply
coordinator. Only explicit synthetic packets and recorded timestamps are used.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
from unittest.mock import patch

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'TestSupport'))
from gzip_json_fixture import csharp_gzip_json
from wlre.core import efficiency
from wlre.core.state import State
from wlre.core.state_events import dispatch_local
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.items.combat_resources import apply_live
from wlre.services.world.obstacle_scope import affects_navigation


def pack(fmt, *values): return struct.pack('<' + fmt, *values)
def attr(value, kind=36, parameter=0): return pack('BBII', kind, 2 if value < 0 else 1, abs(value), parameter)
def unit(pid=71, master=0, slot=0):
    return (pack('BBIHIBBIHIHBBBBHHBBII', 0, 4, pid, slot, master, 1, 1, 500, 100, 400, 50,
        15, 1, 0, 0, 0, 0, 0, 0, 0, 0) + b'\x00' + bytes(54))
def item():
    return pack('HBBIHddBBHBHI',0,0,0,0,0,0,0,0,0,0,0,0,0)+bytes(15)
def companion(index=0, npc=8000, total=10000, level=12, degree=0, name=''):
    encoded=name.encode('utf-16-le')
    return (pack('BHiBiHHHHHHBBBH',index,npc,total,level,300,50,10,11,12,13,14,0,100,1,0)
        + bytes([len(encoded)])+encoded+bytes(25)+item()*9+pack('BBBBHBH',0,0,degree,0,0,0,0))
def world(role=71, name='After local'):
    encoded=name.encode('utf-16-le')
    return pack('IBHHHBBBIIBB',role,1,101,8,9,2,3,4,5,6,7,0)+b'\x00'+bytes([len(encoded)])+encoded+bytes(9)+pack('H',10)
def safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return 'nan' if math.isnan(value) else 'inf' if value > 0 else '-inf'
    if isinstance(value, dict): return {str(k): safe(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [safe(v) for v in value]
    return value


SCENARIOS = []
class Scenario:
    def __init__(self, name, compose=False):
        self.name = name; self.state = State(); self.steps = []; self.compose = compose
        if compose: return
        self.state.player = dict(role_id=71, name='Offline fixture')
        self.state.knowledge['player']['stats'] = dict(exp=20000, level=15, degree=0)
        self.state.knowledge['companions'] = {
            '2': dict(npc_id=8002, stats=dict(exp=10000, level=12, degree=0, name='Pet Two')),
            '3': dict(npc_id=8003, stats=dict(exp=22000, level=16, degree=0, name='Idle Pet'))}
    def packet(self, main, sub, payload=b'', when=0, offline=None):
        error = None
        try:
            event = decode(Packet(main, sub, payload), self.state.player.get('role_id'))
            apply_live(self.state, event)
            if self.compose: dispatch_local(self.state,event,affects_navigation=affects_navigation)
            event['_observed_at'] = when
            if offline is not None: event['_offline'] = offline
            # Python evaluates event.get's fallback eagerly. Do not consult a wall clock.
            with patch.object(efficiency.time, 'monotonic', return_value=1234.5):
                efficiency.observe(self.state, event)
        except ProtocolError as exc: error = str(exc)
        knowledge = dict(role_id=self.state.player.get('role_id'), name=self.state.player.get('name', '玩家'),
            stats=dict(self.state.knowledge['player']['stats']),
            companions={k:dict(npc_id=v.get('npc_id'), stats=dict(v['stats'])) for k,v in self.state.knowledge['companions'].items()})
        expected = copy.deepcopy(self.state.snapshot()['efficiency'])
        for row in expected['rows'].values():
            row['rates'] = efficiency.rates(row)
            row['level_inferred'] = row.get('level_inferred', False)
            row['degree_inferred'] = row.get('degree_inferred', False)
            row['sample_degree'] = row.get('sample_degree')
        self.steps.append(dict(main=main, sub=sub, hex=payload.hex(), when=when, offline=offline,
            error=error, project_knowledge=self.compose, knowledge=knowledge, expected=expected))
        return self
    def start(self, when, *units): return self.packet(11, 250, b'\x01\x02'+pack('B',len(units))+b''.join(units), when)
    def exp(self, total, when, slot=2, human=4, parameter=0):
        return self.packet(8, 1 if slot is None else 2,
            (b'' if slot is None else pack('BH',human,slot))+attr(total, parameter=parameter), when)
    def end(self, when): return self.packet(20, 8, when=when)
    def battle(self, total, end): return self.start(end-2, unit(), unit(8002,71,2)).exp(total,end-1).end(end)
    def finish(self): SCENARIOS.append((self.name,self.steps)); return self

s = Scenario('wire_completed_battles_filters_refresh_and_idle_history')
s.packet(1,11,when=0,offline=True).battle(10000,10).battle(10120,30)
s.start(40,unit()).end(50).exp(10500,60).battle(10540,80)
s.start(90,unit(),unit(8002,71,2)).exp(10600,91,human=9).exp(10610,92,parameter=7)
s.packet(8,3,pack('I',71)+attr(99999),93).packet(11,12,b'\x01',94).packet(11,0,pack('IH',71,2),95)
s.packet(11,5,b'\x00',96).packet(255,255,when=97).end(100).battle(10650,120).finish()

s = Scenario('wire_nonowned_starts_and_unknown_companion')
s.start(0,unit(9),unit(8002,9,2)).exp(10100,1).end(2)
s.start(3,unit(8008,71,8)).exp(30,4,slot=8).end(5)
s.start(6,unit(),unit(8002,71,2)).exp(10200,7).end(8).end(9).finish()

s = Scenario('wire_star_signed64_and_outside_battle_rebase')
for total,when in [(10000,10),(10120,30),(2**63-1,50),(-2**63,70),(0,90)]:
    s.start(when-2,unit()).packet(5,47,pack('BBq',1,0,total)+bytes(30),when-1).end(when)
s.packet(5,47,pack('BBq',2,0,999)+bytes(30),100).finish()

s = Scenario('post_knowledge_unrecognized_refresh_identity_deletion')
s.battle(10000,10).battle(10100,30)
s.state.knowledge['companions']['2']['stats']['name'] = 'Renamed'
s.state.player['name'] = 'New local name'
s.packet(255,255,when=40)
s.state.knowledge['companions']['2']['npc_id'] = 9002
s.packet(255,255,when=50)
del s.state.knowledge['companions']['3']
s.packet(255,255,when=60).finish()

s = Scenario('role_zero_missing_and_nonfinite_reset_order')
s.battle(10000,10).start(20,unit(),unit(8002,71,2)).exp(10100,21)
s.state.player['role_id'] = 0
s.end(22).packet(255,255,when=23,offline=True)
s.state.player = {}
s.end(24)
s.state.player = dict(role_id=72,name='Changed')
s.packet(255,255,when=float('nan'),offline=True).packet(255,255,when=0)
s.state.player['role_id'] = 71
s.start(1,unit()).end(float('inf')).end(2).finish()

s = Scenario('malformed_wire_no_publication')
s.battle(10000,10).start(20,unit(),unit(8002,71,2)).exp(10100,21)
for main,sub,payload in [(8,2,pack('BH',4,2)+attr(10110)),(11,250,b'\x01\x02\x01'+unit()),
    (5,47,pack('BBq',1,0,400)+bytes(30)),(20,8,b'')]:
    for cut in sorted({0,1,len(payload)-1}):
        if 0 <= cut < len(payload): s.packet(main,sub,payload[:cut],22)
    s.packet(main,sub,payload+b'\xff',23)
s.end(30).finish()

s = Scenario('projected_slot_zero_distinct_identity_samples_and_replacement',compose=True)
s.packet(3,1,world()).packet(15,8,companion()).packet(15,8,companion(2,8002))
for total,when in [(10000,10),(10100,30)]:
    s.start(when-2,unit(),unit(8000,71,0)).exp(total,when-1,slot=0).end(when)
s.start(40,unit(),unit(8000,71,0)).end(50) # Slot zero is not a proven participant.
s.exp(10500,55,slot=0).packet(15,8,companion(total=0),56) # Same identity replays S8.
s.packet(15,8,companion(npc=9000,total=30,level=2),57) # New identity drops old S8.
s.exp(10600,58,slot=0).exp(7,59,slot=256).exp(8,60,slot=65535)
s.packet(15,2,pack('IBB',71,0,0),61).packet(255,255,when=62).finish()

s = Scenario('projected_int64_player_labels_and_sample_degree',compose=True)
s.packet(3,1,world())
for kind in [35,39]:
    for number in [0xffffffff,-0xffffffff,0,1]:
        s.packet(8,1,attr(number,kind=kind),when=len(s.steps))
for degree,total,when in [(0xffffffff,10000,20),(-0xffffffff,10100,30),(0,10200,40)]:
    s.start(when-3,unit()).packet(8,1,attr(degree,kind=39),when-2).exp(total,when-1,slot=None).end(when)
s.packet(5,47,pack('BBq',1,0,2**63-1)+bytes(30),50).finish()

s = Scenario('projected_companion_override_buffer_and_confirmation',compose=True)
s.packet(3,1,world()).packet(8,2,pack('BH',4,0)+attr(0xffffffff,kind=39),1)
s.packet(8,2,pack('BH',4,0)+attr(-0xffffffff,kind=35),2).packet(15,8,companion(total=30),3)
s.start(4,unit(),unit(8000,71,0)).end(5)
s.packet(15,8,companion(total=40,level=4),6)
s.packet(8,2,pack('BH',4,0)+attr(0,kind=39),7)
s.packet(8,2,pack('BH',4,0)+attr(0xffffffff,kind=35),8)
s.packet(15,8,companion(npc=9000,total=50,level=5,name='New NPC'),9)
s.packet(255,255,when=10).finish()

s = Scenario('projected_unknown_and_zero_role_keep_knowledge_until_local_identity',compose=True)
s.packet(8,1,attr(345),0).packet(15,8,companion(),1)
s.packet(3,1,world(0,'Zero'),2).packet(8,1,attr(0xffffffff,kind=35),3)
s.packet(3,1,world(71,'First'),4).packet(3,1,world(72,'Second'),5)
s.packet(3,1,world(71,'Returned'),float('nan')).packet(255,255,when=6).finish()

s = Scenario('projected_malformed_packets_preserve_prior_knowledge',compose=True)
s.packet(3,1,world()).packet(15,8,companion()).start(1,unit(),unit(8000,71,0)).exp(123,2,slot=0)
for main,sub,payload in [(15,8,companion(npc=9000)),(8,1,attr(0xffffffff,kind=35)),(3,1,world(72,'Replacement'))]:
    for cut in [1,len(payload)//2,len(payload)-1]: s.packet(main,sub,payload[:cut],3)
s.end(4).finish()

sources=['wlre/core/efficiency.py','wlre/core/event_log.py','wlre/core/state.py',
    'wlre/core/state_ownership.py','wlre/network/protocol.py','wlre/network/layouts.py',
    'wlre/network/live_data.py','wlre/network/wire.py','wlre/services/items/combat_resources.py',
    'wlre/core/state_events.py','wlre/core/state_world_events.py','wlre/core/state_battle_events.py',
    'wlre/core/state_session_events.py']
# Only normalize byte CRLF; preserve every other byte, including BOMs.
provenance={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sources}
lines=['// Generated by EfficiencyReceiveGenerateVectors.py. Synthetic offline data only.',
    'namespace Lala.Core.Tests.Battle;', 'public static class EfficiencyReceivePythonVectors', '{',
    '    public const string SourceSha256 = '+json.dumps(json.dumps(provenance,separators=(',',':')))+';',
    '    public static IEnumerable<object[]> Sequences()', '    {']
for name,steps in SCENARIOS:
    lines.append('        yield return new object[] { '+json.dumps(name)+', '+csharp_gzip_json(
        json.dumps(safe(steps),ensure_ascii=False,separators=(',',':'),allow_nan=False))+' };')
lines += ['    }','}']
Path(__file__).with_name('EfficiencyReceivePythonVectors.cs').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(f'{len(SCENARIOS)} sequences / {sum(len(steps) for _, steps in SCENARIOS)} snapshots')
