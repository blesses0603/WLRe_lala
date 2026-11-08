"""Synthetic State.apply -> SessionLogic.receive battle-context oracle; no I/O.

Only battle count/active/style/units are projected. Actual receive executes with
all services dormant and a fixed clock; post-event/coop/scheduler behavior is not
part of this bounded port. Fresh logic on retained State tests context isolation.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
from unittest.mock import patch

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'dotnet/Lala.Core.Tests/TestSupport'))
from gzip_json_fixture import csharp_gzip_json
from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet


def p(fmt, *values):
    return struct.pack('<' + fmt, *values)


def unit(pid=71, master=0, col=3, row=1, style=16):
    return p('BBIHIBBIHIHBBBBHHBBII', style, 0, pid, 2, master, col, row,
             100, 40, 90, 20, 19, 2, 1, 3, 0, 0, 1, 2, 0, 0) + b'\0' + bytes(54)


def world(role=71):
    return (3, 1, p('IBHHH', role, 0, 101, 20, 30) + bytes(13) + b'\0\0' + bytes(8) + b'\0\0\0')


def start(*units):
    return (11, 250, p('BBB', 12, 3, len(units)) + b''.join(units))


def style(value): return (11, 10, p('B', value))
def exit_role(role=71): return (11, 0, p('IH', role, 0))
def exit_unit(col=3, row=1): return (11, 1, p('BB', col, row))


SCENARIOS = []

def scenario(name, packets):
    state = State()
    logic = SessionLogic()
    steps = []
    for packet in packets:
        if packet == 'fresh_context':
            logic = SessionLogic()
            message = {'fresh_context': True}
        else:
            main, sub, payload = packet
            event = decode(Packet(main, sub, payload), state.player.get('role_id'))
            state.apply(event)
            with patch('time.monotonic', return_value=123.0):
                assert logic.receive(event, state) == []
            message = {'main': main, 'sub': sub, 'hex': payload.hex().upper()}
        steps.append({'message': message, 'expected': {
            'packet_count': state.packet_count, 'battle_count': state.battle_count,
            'active': state.battle.get('active'), 'war_style': state.battle.get('war_style'),
            'units': [{'slot': key, 'pid': value['pid'], 'exited': value.get('exited', False)}
                      for key, value in state.battle_units.items()]}})
    SCENARIOS.append((name, steps))


scenario('announcement_consumed_once_and_unit_style_is_not_evidence',
         [world(), style(16), start(unit(style=9)), (52, 1, p('H', 2)), start(unit(style=16)), start()])
scenario('latest_announcement_and_zero_are_known',
         [style(16), style(0), start(), start(), style(255), start()])
for exit_packet, label in [(exit_role(), 'role'), (exit_unit(), 'unit')]:
    scenario('first_' + label + '_exit_clears_pending_but_duplicate_keeps_later_announcement',
             [world(), start(unit()), style(16), exit_packet, start(unit()),
              exit_packet, style(9), exit_packet, exit_role(), exit_unit(), start(unit()), start()])
scenario('count_zero_exit_does_not_clear_announcement',
         [world(), (11, 5, b'\1' + unit()), style(16), exit_role(), exit_unit(), start(unit())])
scenario('remote_unknown_slot_and_master_do_not_qualify',
         [world(), start(unit(), unit(pid=8000, master=71, row=2)), style(16),
          exit_role(72), exit_unit(1, 1), exit_unit(3, 2), start(unit())])
scenario('missing_own_identity_cannot_establish_exit_key',
         [start(unit()), style(16), exit_role(), exit_unit(), start(unit()), world(),
          style(9), exit_role(), start(unit())])
scenario('zero_role_is_valid_own_identity',
         [world(0), start(unit(pid=0)), style(16), exit_unit(), start(unit(pid=0)),
          style(9), exit_role(0), start()])
scenario('winner_event_end_role_list_world_do_not_clear_pending',
         [world(), start(unit()), style(16), (11, 12, b'\1'), (20, 8, b''),
          (63, 1, b''), world(72), start(unit(pid=72))])
scenario('exit_key_includes_role_and_only_remembers_latest_key',
         [world(), start(unit()), exit_role(), style(16), world(72), exit_role(72), start(),
          exit_role(72), style(9), world(), exit_role(), style(12), world(72), exit_role(72), start()])
scenario('new_start_has_new_qualifying_exit_key',
         [world(), start(unit()), exit_unit(), style(16), start(unit()), style(9), exit_unit(), start()])
scenario('fresh_context_does_not_import_pending_or_visible_style',
         [world(), style(16), 'fresh_context', start(unit()), style(9), start(unit()),
          'fresh_context', start(unit())])
scenario('fresh_context_resets_exit_key_even_on_retained_battle',
         [world(), start(unit()), exit_role(), 'fresh_context', style(16), exit_unit(), start()])

sources = ['wlre/network/client.py', 'wlre/core/state.py', 'wlre/core/state_events.py',
           'wlre/core/state_battle_events.py', 'wlre/network/protocol.py', 'wlre/network/layouts.py']
provenance = {name: hashlib.sha256((ROOT / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
              for name in sources}
lines = ['// Generated by BattleReceiveGenerateVectors.py. Synthetic offline data only.',
         'namespace Lala.Core.Tests.Sessions.Receive;', 'public static class BattleReceivePythonVectors', '{',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
         '    public static IEnumerable<object[]> Sequences()', '    {']
for name, steps in SCENARIOS:
    lines.append('        yield return new object[] { ' + json.dumps(name) + ', ' +
                 csharp_gzip_json(json.dumps(steps, separators=(',', ':'))) + ' };')
lines += ['    }', '}']
Path(__file__).with_name('BattleReceivePythonVectors.cs').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'{len(SCENARIOS)} sequences / {sum(len(steps) for _, steps in SCENARIOS)} snapshots')
