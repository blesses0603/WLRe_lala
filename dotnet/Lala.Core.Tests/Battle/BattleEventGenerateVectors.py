import base64, gzip
"""Regenerate synthetic offline battle-reducer sequences from retained Python.

Uses the actual State defaults, dispatch_local, packet decoder and local outbound
observation function. Does not invoke service observers, transport, AI or resources.
"""
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import sys

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.core.state import State
from wlre.core.state_events import dispatch_local
from wlre.network.protocol import decode
from wlre.network.outbound_observations import observed_outbound
from wlre.network.wire import Packet


def p(fmt, *values):
    return struct.pack('<' + fmt, *values)


def unit(col=3, row=1, pid=71, master=0, hp=90, sp=20, name='Fixture 星😀'):
    text = name.encode('utf-16le')
    return (p('BBIHIBBIHIHBBBBHHBBII', 16, 0, pid, 2, master, col, row, 100, 40, hp, sp,
              19, 2, 1, 3, 0, 0, 1, 2, 0x12345678, 0x87654321) +
            p('B', len(text)) + text + b''.join(p('HI', n, n * 1000) for n in range(9)))


def attrs(*values):
    return b''.join(p('BBBI', *v) for v in values)


def attack(*actors):
    # Includes unknown flags, repeated target attributes, unsigned extrema and both signs.
    result = p('B', len(actors))
    for col, row in actors:
        result += p('BBHBBB', col, row, 10001, 9, 255, 2)
        result += p('BBBBB', 3, 1, 255, 254, 3)
        result += p('BIB', 25, 0xFFFFFFFF, 2) + p('BIB', 26, 19, 1) + p('BIB', 255, 7, 0)
        result += p('BBBBB', 1, 1, 0, 0, 0)
    return result


scenarios = []


class Scenario:
    def __init__(self, name, role=71):
        self.name = name
        self.state = State()
        self.role = role
        self.steps = []
        self.record(None)

    def record(self, message):
        snapshot = self.state.snapshot()
        self.steps.append({'role_id': self.role, 'message': message, 'expected': {
            'battle_count': snapshot['battle_count'], 'battle': snapshot['battle'],
            'battle_units': snapshot['battle_units'],
            'unit_order': list(snapshot['battle_units']),
            'command_order': list(snapshot['battle'].get('commands', {}))}})

    def event(self, event, message):
        self.state.player = {} if self.role is None else {'role_id': self.role}
        dispatch_local(self.state, event, affects_navigation=lambda *_: False)
        self.record(message)

    def packet(self, main, sub, payload=b''):
        self.event(decode(Packet(main, sub, payload)),
                   {'main': main, 'sub': sub, 'hex': payload.hex().upper()})

    def start(self, *units, stage=12, fight=3):
        self.packet(11, 250, p('BBB', stage, fight, len(units)) + b''.join(units))

    def units(self, *units):
        self.packet(11, 5, p('B', len(units)) + b''.join(units))

    def command(self, col=3, row=1, target_col=1, target_row=1, skill=10001, item=None):
        payload = p('BBBBHBBB', col, row, target_col, target_row,
                    skill if item is None else item, 0, 0, 17)
        event = observed_outbound(Packet(50, 1 if item is None else 2, payload))
        self.event(event, {'command': event})

    def minimal_command(self, col, row):
        event = {'type': 'battle_command_sent', 'col': col, 'row': row}
        self.event(event, {'command': event})

    def finish(self):
        scenarios.append({'name': self.name, 'steps': self.steps})


s = Scenario('defaults-and-out-of-order-before-start')
s.packet(52, 1, p('H', 0)); s.command(); s.packet(50, 1, attack((3, 1)))
s.packet(11, 10, b'\xff'); s.packet(11, 12, b'\x00')
s.units(unit()); s.packet(51, 1, attrs((3, 1, 25, 7)))
s.start(); s.start(); s.finish()

s = Scenario('ordered-commands-resend-round-and-report-status')
s.start(unit(), unit(1, 1, 22)); s.command(4, 4); s.command(3, 1, item=4321); s.command(1, 1)
s.command(4, 4, skill=10002); s.packet(52, 1, p('H', 0))
s.packet(50, 1, attack((4, 4), (4, 4), (2, 2)))
s.packet(50, 1, attack((4, 4), (4, 4), (2, 2)))
s.command(4, 4, skill=10003); s.packet(50, 1, attack((3, 1)))
s.packet(52, 1, p('H', 1)); s.minimal_command(0, 255)
s.packet(52, 1, p('H', 1)); s.packet(50, 1, attack((0, 255)))
s.packet(52, 1, p('H', 65535)); s.command(); s.packet(52, 1, p('H', 0))
s.packet(50, 1, attack()); s.finish()

s = Scenario('attributes-never-buffer-clamp-or-infer-damage')
s.packet(51, 1, attrs((3, 1, 25, 3))); s.units(unit())
s.packet(51, 1, attrs((3, 1, 27, 999), (3, 1, 25, 80), (3, 1, 25, 0),
                      (3, 1, 26, 65536), (1, 1, 25, 0), (3, 1, 255, 0xFFFFFFFF)))
s.packet(50, 1, attack((3, 1))); s.packet(51, 1, attrs((3, 1, 25, 0xFFFFFFFF), (3, 1, 26, 0xFFFFFFFF)))
s.packet(11, 1, p('BB', 3, 1)); s.packet(51, 1, attrs((3, 1, 25, 12)))
s.units(unit(hp=2, sp=3)); s.packet(51, 1); s.finish()

s = Scenario('unit-order-duplicate-replacement-and-start-reset')
s.units(unit(4, 4), unit(1, 2, 22), unit(4, 4, 33, hp=30))
s.packet(51, 1, attrs((4, 4, 25, 11))); s.packet(11, 1, p('BB', 4, 4))
s.units(unit(3, 1, 71), unit(1, 2, 44), unit(4, 4, 55))
s.packet(11, 10, b'\x10'); s.command(4, 4); s.packet(50, 1, attack((4, 4)))
s.packet(11, 12, b'\x02'); s.start(unit(2, 3, 66), unit(1, 1, 71), unit(2, 3, 77), stage=255, fight=255)
s.start(unit(1, 1, 71)); s.start(unit(1, 1, 71)); s.finish()

s = Scenario('own-exit-is-not-companion-master-or-slot')
s.start(unit(3, 1, 71), unit(3, 2, 8002, master=71), unit(1, 1, 72))
s.packet(11, 1, p('BB', 4, 4)); s.packet(11, 1, p('BBB', 3, 2, 255))
s.packet(11, 0, p('IH', 8002, 2)); s.packet(11, 1, p('BB', 1, 1))
s.packet(11, 0, p('IH', 72, 0)); s.packet(11, 1, p('BB', 3, 1))
s.units(unit()); s.packet(11, 1, p('BB', 3, 1)); s.start(unit())
s.packet(11, 0, p('IH', 71, 65535)); s.finish()

s = Scenario('identity-is-current-unknown-and-zero', role=None)
s.start(unit(pid=0), unit(1, 1, 71)); s.packet(11, 1, p('BB', 3, 1))
s.packet(11, 0, p('IH', 0, 0)); s.role = 71
s.packet(11, 1, p('BB', 3, 1)); s.role = 0
s.packet(11, 0, p('IH', 71, 0)); s.packet(11, 0, p('IH', 0, 0))
s.start(unit(pid=0)); s.packet(11, 1, p('BB', 3, 1))
s.role = 72; s.start(unit(1, 1, 71)); s.packet(11, 1, p('BB', 1, 1)); s.finish()

s = Scenario('malformed-s51-discard-whole-records-and-continue')
s.start(unit()); complete = attrs((3, 1, 25, 1), (3, 1, 26, 2), (3, 1, 25, 3))
for length in range(1, 21):
    if length % 7: s.packet(51, 1, complete[:length])
s.packet(51, 1, attrs((3, 1, 25, 73), (3, 1, 26, 19)))
s.packet(1, 23); s.packet(250, 250, b'offline fixture'); s.finish()

s = Scenario('winner-round-late-unit-and-reports-do-not-resurrect')
s.start(unit()); s.command(); s.packet(11, 12, b'\x01'); s.packet(11, 12, b'\x01')
s.packet(50, 1, attack((3, 1))); s.packet(52, 1, p('H', 2)); s.command()
s.units(unit(3, 2, 22)); s.packet(11, 10, b'\xfe'); s.packet(51, 1, attrs((3, 1, 25, 3)))
s.packet(50, 1, attack()); s.start(); s.finish()

# Reproducible mixed traces exercise combinations without hand-writing an oracle.
for seed in range(12):
    rng = random.Random(790050 + seed)
    s = Scenario('seeded-mixed-' + str(seed), role=[None, 0, 71][seed % 3])
    for step in range(40):
        col, row = rng.randrange(1, 5), rng.randrange(1, 5)
        op = rng.randrange(11)
        if op == 0: s.start(unit(col, row, rng.choice([0, 71, 72])), fight=step)
        elif op == 1: s.units(unit(col, row, rng.choice([0, 71, 72]), hp=rng.randrange(101)))
        elif op == 2: s.packet(51, 1, attrs((col, row, rng.choice([25, 26, 27, 255]), rng.choice([0, 1, 65536, 0xFFFFFFFF]))))
        elif op == 3: s.packet(52, 1, p('H', rng.choice([0, 1, 2, 65535])))
        elif op == 4: s.command(col, row, item=123 if step % 2 else None)
        elif op == 5: s.packet(50, 1, attack((col, row), (3, 1)))
        elif op == 6: s.packet(11, 1, p('BB', col, row))
        elif op == 7: s.packet(11, 0, p('IH', rng.choice([0, 71, 72]), 0))
        elif op == 8: s.packet(11, 12, p('B', rng.randrange(256)))
        elif op == 9: s.packet(11, 10, p('B', rng.randrange(256)))
        else:
            s.role = rng.choice([None, 0, 71, 72])
            s.packet(51, 1, attrs((col, row, 25, 1)) + b'\xff')
    s.finish()

sources = ['wlre/core/state_battle_events.py', 'wlre/core/state_events.py', 'wlre/core/state.py',
           'wlre/network/protocol.py', 'wlre/network/outbound_observations.py']
provenance = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sources}
lines = ['// Generated by BattleEventGenerateVectors.py from retained Python. Synthetic offline data only.',
         'namespace Lala.Core.Tests.Battle;', 'public static class BattleEventPythonVectors', '{',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
         '    public static IEnumerable<object[]> Sequences()', '    {']
for scenario in scenarios:
    data = json.dumps(scenario['steps'], ensure_ascii=False, separators=(',', ':'))
    lines.append('        yield return new object[] { ' + json.dumps(scenario['name']) + ', ' + 'Decode(' + json.dumps(base64.b64encode(gzip.compress(data.encode("utf-8"),mtime=0)).decode("ascii")) + ') };')
lines += ['    }', '    private static string Decode(string encoded)', '    {', '        using var input = new System.IO.MemoryStream(System.Convert.FromBase64String(encoded));', '        using var gzip = new System.IO.Compression.GZipStream(input, System.IO.Compression.CompressionMode.Decompress);', '        using var reader = new System.IO.StreamReader(gzip, System.Text.Encoding.UTF8);', '        return reader.ReadToEnd();', '    }', '}']
Path(__file__).with_name('BattleEventPythonVectors.cs').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'{len(scenarios)} sequences, {sum(len(s["steps"]) for s in scenarios)} snapshots')
