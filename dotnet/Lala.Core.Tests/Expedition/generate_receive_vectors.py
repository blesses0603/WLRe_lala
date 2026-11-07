"""Synthetic receive-only differential fixtures using the retained Python implementation.

Calls the real S31 decoder, defaults(), apply_expedition() and with_deadline(). Only
monotonic time is patched to the explicit observation timestamp; no automation
observer, outgoing operation, inventory mutation, catalog or transport is invoked.
Run from any directory. Output is deterministic gzip/base64 and below 500 KiB.
"""
import base64
import copy
import gzip
import json
import os
from pathlib import Path
import random
import struct
import sys
from types import SimpleNamespace
from unittest.mock import patch

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from wlre.network.expedition import decode_expedition
from wlre.network.wire import Packet, ProtocolError
from wlre.services.expedition.manager import defaults, apply_expedition


def p(fmt, *values): return struct.pack('<' + fmt, *values)


def role(index=1, npc=101, state=0, faith=90, seed=0):
    return (p('BHBHHHHHB', index, npc, state, 10+seed, 20+seed, 30+seed, 40+seed, 50+seed, 60)
            + bytes([1, 2, 3, 4, 5]) + p('BIBHBBH', faith, 4000000000, 255, 65535, 2, 7, 65535))


def team(index=1, minutes=3, quest=12, members=(101, 102, 0, 0), items=(1, 2, 0, 0)):
    return p('BH4H4HH', index, minutes, *members, *items, quest)


def snapshot(seed=0):
    return (b''.join(team(index=(255-i if seed % 2 else 7), minutes=(seed+i)%65536,
                         quest=100+i, members=(100+i, 100+i, 0, 65535)) for i in range(10))
            + p('50H', *(range(seed, seed+50))) + bytes([255])*140
            + p('BI', seed%256, 0xffffffff) + bytes([127])*27)


def project(state):
    value = copy.deepcopy(state.expedition)
    # Preserve Python's unbounded counters without depending on a JSON number reader.
    value['revision'] = str(value['revision'])
    value['claimed'] = str(value['claimed'])
    return value


sequences = []
covered = set()


class Scenario:
    def __init__(self, name, **initial):
        self.state = SimpleNamespace(expedition=defaults())
        self.state.expedition.update(initial)
        self.now = 100.25
        self.value = dict(name=name, initial=project(self.state), steps=[])
        sequences.append(self.value)

    def step(self, sub, payload=b'', *, main=31, at=None):
        self.now = self.now + .25 if at is None else at
        entry = dict(main=main, sub=sub, hex=payload.hex(), at=self.now)
        try:
            event = decode_expedition(Packet(main, sub, payload))
        except ProtocolError:
            entry['error'] = True
        else:
            entry['error'] = False
            if event is not None:
                covered.add(event['type'])
                with patch('wlre.services.expedition.manager.time.monotonic', return_value=self.now):
                    apply_expedition(self.state, event)
        entry['expected'] = project(self.state)
        self.value['steps'].append(entry)
        return self

    def reset(self):
        self.state.expedition = defaults()
        self.value['steps'].append(dict(reset=True, expected=project(self.state)))
        return self


s = Scenario('snapshot replacement and ordinal team slots', enabled=True, pending='dispatch',
             settings={'faith_min': 80, 'quests': [12, 13]}, claimed=7)
s.step(3, role(255)).step(18, team(255)).step(6, b'\xff\x03' + role(1) + role(2) + role(1, npc=999))
s.step(13, snapshot(4)).step(13, snapshot(5)).step(6, b'\0\0').step(13, snapshot()).reset()
s.step(17, p('BH', 1, 0)).step(15, b'opaque').step(6, b'\x01\x01' + role())

s = Scenario('late missing duplicates and replacement')
s.step(12, b'\x01\xff').step(27, b'\x01\xff\x01').step(35, p('BBi', 1, 64, -100))
s.step(17, p('BH', 1, 7)).step(5, b'\x01').step(24, role()).step(12, b'\x01\xff')
for kind in (64, 27, 28, 29, 30, 33, 35, 0, 31, 255):
    for value in (-2147483648, -1, 0, 2147483647):
        s.step(35, p('BBi', 1, kind, value))
s.step(27, b'\x01\x09\xff').step(3, role(faith=30)).step(26, b'\x01').step(26, b'\x01')
s.step(35, p('BBi', 1, 28, -12)).step(24, role(seed=5))

s = Scenario('results are not claims and times do not prove completion', pending='claim', enabled=True,
             claimed=2, settings={'auto_claim': True})
s.step(16, p('BBHHBII', 255, 255, 65535, 65535, 255, 0xffffffff, 0xffffffff))
s.step(17, p('BH', 255, 0), at=1000).step(18, team(255, 0), at=1001)
s.step(15).step(15, b'\x01\x02\xff').step(16, p('BBHH', 0, 255, 1, 2))
s.step(16, p('BBHH', 0, 255, 1, 2)).step(17, p('BH', 255, 65535), at=2)
s.step(18, team(255, 2), at=0).step(17, p('BH', 255, 2), at=0).step(17, p('BH', 255, 2), at=4)
s.step(21, p('BI', 255, 0xffffffff)).step(21, p('BI', 0, 0))

for pending in (None, '', 'dispatch', 'claim', 'faith'):
    for uncertain in (False, True):
        s = Scenario(f'rejections pending={pending!r} uncertain={uncertain}', enabled=True,
                     pending=pending, uncertain=uncertain, status='existing', claimed=1 << 80,
                     revision=1 << 80, settings={'preserved': ['opaque', 1, False, None]})
        s.step(20, b'\x00').step(25, b'\xff').step(6, b'\x01\x01'+role()).step(13, snapshot())
        s.step(18, team()).step(16, p('BBHH', 0, 1, 0, 0)).step(15).reset()

s = Scenario('quest replacement collisions unknown indices and show ignored')
s.step(13, snapshot(1))
for show in (0, 1, 255):
    s.step(19, b''.join(p('BH', [0, 255, 7][i%3], i+1) for i in range(50)) + bytes([show]))
s.step(13, snapshot(3)).step(19, b''.join(p('BH', 0, i) for i in range(50)) + b'\0')

s = Scenario('all byte slots remain bounded and snapshots replace')
s.step(6, b'\xff\xff' + b''.join(role(i) for i in range(255)))
s.step(3, role(255)).step(3, role(255, npc=65535)).step(5, b'\x01')
s.step(6, b'\0\0').step(13, snapshot())

rng = random.Random(310615)
subs = [6, 3, 24, 5, 26, 12, 27, 35, 13, 15, 16, 17, 18, 19, 20, 25, 21, 255]
for run in range(48):
    s = Scenario(f'seeded receive sequence {run}', enabled=bool(run%2),
                 pending=[None, '', 'dispatch', 'claim', 'faith'][run%5], uncertain=run%7==0)
    for step in range(64):
        sub = subs[(run+step)%len(subs)]
        index = rng.choice([0, 1, 2, 3, 255])
        if sub == 6:
            n = rng.randrange(6)
            payload = bytes([rng.randrange(256), n]) + b''.join(role(rng.randrange(4), seed=rng.randrange(100)) for _ in range(n))
        elif sub in (3, 24): payload = role(index, npc=rng.randrange(65536), state=rng.randrange(256), faith=rng.randrange(256))
        elif sub in (5, 26): payload = bytes([index])
        elif sub == 12: payload = bytes([index, rng.randrange(256)])
        elif sub == 27: payload = bytes([index, rng.randrange(256), rng.randrange(256)])
        elif sub == 35: payload = p('BBi', index, rng.choice([27, 28, 29, 30, 33, 35, 64, 255]), rng.randint(-2147483648, 2147483647))
        elif sub == 13: payload = snapshot(rng.randrange(500))
        elif sub == 15: payload = rng.randbytes(rng.randrange(20))
        elif sub == 16: payload = p('BBHH', rng.randrange(256), index, rng.randrange(65536), rng.randrange(65536)) + rng.randbytes(9*rng.randrange(4))
        elif sub == 17: payload = p('BH', index, rng.choice([0, 1, 65535]))
        elif sub == 18: payload = team(index, rng.choice([0, 1, 65535]), rng.randrange(65536))
        elif sub == 19: payload = b''.join(p('BH', rng.randrange(256), rng.randrange(65536)) for _ in range(50)) + bytes([rng.randrange(256)])
        elif sub in (20, 25): payload = bytes([rng.randrange(256)])
        elif sub == 21: payload = p('BI', rng.randrange(256), rng.randrange(1 << 32))
        else: payload = rng.randbytes(10)
        s.step(sub, payload)
        if step%13 == 0: s.step(sub, payload)  # Same evidence is not deduplicated.
        if sub not in (15, 255) and step%7 == 0:
            s.step(sub, payload[:-1]).step(sub, payload+b'\0')
        if step%17 == 0: s.step(sub, payload, main=30)
        if step == 31 and run%4 == 0: s.reset()

expected_kinds = {'outpost_snapshot', 'outpost_role', 'outpost_remove', 'outpost_status', 'outpost_faith',
                 'outpost_attribute', 'expedition_snapshot', 'expedition_started', 'expedition_result',
                 'expedition_time', 'expedition_team', 'expedition_quests', 'expedition_rejected', 'expedition_level'}
assert covered == expected_kinds
raw = json.dumps(sequences, ensure_ascii=False, separators=(',', ':')).encode()
encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
source = '''// Generated by generate_receive_vectors.py. Synthetic offline Python differential evidence.
using System.IO.Compression;
using System.Text.Json;
namespace Lala.Core.Tests.Expedition;
public static class PythonExpeditionReceiveVectors
{
    public static IEnumerable<object[]> Sequences()
    {
        using var bytes = new MemoryStream(Convert.FromBase64String(Data));
        using var gzip = new GZipStream(bytes, CompressionMode.Decompress);
        using var document = JsonDocument.Parse(gzip);
        foreach (var sequence in document.RootElement.EnumerateArray())
            yield return [sequence.GetProperty("name").GetString()!, sequence.GetRawText()];
    }
    private const string Data = """
''' + '\n'.join(encoded[i:i+120] for i in range(0, len(encoded), 120)) + '\n""";\n}\n'
assert len(source.encode()) < 500_000
Path(__file__).with_name('PythonExpeditionReceiveVectors.cs').write_text(source, encoding='utf-8')
print(f'{len(sequences)} sequences; {sum(len(s["steps"]) for s in sequences)} steps; {len(source.encode())} fixture bytes; {len(raw)} raw JSON bytes')
