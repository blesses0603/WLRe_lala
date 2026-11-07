"""Retained decoder + apply_live + efficiency observer; explicit offline times only.

Knowledge is captured after apply_live and supplied whole to C#. This is adapter parity,
not automatic C# knowledge composition or the complete State.apply coordinator.
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
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.items.combat_resources import apply_live


def pack(fmt, *values): return struct.pack('<' + fmt, *values)
def attr(value, kind=36, parameter=0): return pack('BBII', kind, 2 if value < 0 else 1, abs(value), parameter)
def unit(pid=71, master=0, slot=0):
    return (pack('BBIHIBBIHIHBBBBHHBBII', 0, 4, pid, slot, master, 1, 1, 500, 100, 400, 50,
        15, 1, 0, 0, 0, 0, 0, 0, 0, 0) + b'\x00' + bytes(54))
def safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return 'nan' if math.isnan(value) else 'inf' if value > 0 else '-inf'
    if isinstance(value, dict): return {str(k): safe(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [safe(v) for v in value]
    return value


SCENARIOS = []
class Scenario:
    def __init__(self, name):
        self.name = name; self.state = State(); self.steps = []
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
            error=error, knowledge=knowledge, expected=expected))
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

sources=['wlre/core/efficiency.py','wlre/core/event_log.py','wlre/core/state.py',
    'wlre/core/state_ownership.py','wlre/network/protocol.py','wlre/network/layouts.py',
    'wlre/network/live_data.py','wlre/network/wire.py','wlre/services/items/combat_resources.py']
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
