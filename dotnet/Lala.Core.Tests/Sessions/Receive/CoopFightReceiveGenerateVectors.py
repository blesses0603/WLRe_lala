"""Actual State.apply -> SessionLogic.receive cooperative bookkeeping oracle.

Synthetic offline packets, dormant services, fixed clock. Project all instance
state and the supported battle context, not timers/post_event/event_flow/sends.
The source's duplicate-consumption delay=None TypeError is retained explicitly;
only that excluded delay arithmetic failure may be caught, after bookkeeping.
"""
import copy
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


def p(fmt, *values): return struct.pack('<' + fmt, *values)
def unit(pid=71, master=0, col=3, row=1, style=9):
    return p('BBIHIBBIHIHBBBBHHBBII', style, 0, pid, 2, master, col, row,
             100, 40, 90, 20, 19, 2, 1, 3, 0, 0, 1, 2, 0, 0) + b'\0' + bytes(54)
def world(role=71):
    return (3, 1, p('IBHHH', role, 0, 101, 20, 30) + bytes(13) + b'\0\0' + bytes(8) + b'\0\0\0')
def start(*units): return (11, 250, p('BBB', 12, 3, len(units)) + b''.join(units))
def style(value=16): return (11, 10, p('B', value))
def count(value): return (186, 15, p('B', value))
def winner(value=1): return (11, 12, p('B', value))
def exit_role(role=71): return (11, 0, p('IH', role, 0))
def exit_unit(col=3, row=1): return (11, 1, p('BB', col, row))
def guarded(packet): return {'guarded_exit': packet}

SCENARIOS = []
def scenario(name, packets, seed=None):
    state = State()
    state.instances['coop'].update(seed or {})
    logic = SessionLogic()
    steps = []
    for packet in packets:
        failed_delay = False
        if packet == 'fresh_context':
            logic = SessionLogic()
            message = {'fresh_context': True}
        else:
            guard_expected = isinstance(packet, dict)
            if guard_expected: packet = packet['guarded_exit']
            main, sub, payload = packet
            event = decode(Packet(main, sub, payload), state.player.get('role_id'))
            state.apply(event)
            with patch('time.monotonic', return_value=123.0):
                try:
                    assert logic.receive(event, state) == []
                except TypeError as error:
                    # Real receive reaches the independent guard, gets None, then
                    # tries 123.0 + None. Do not emulate or skip receive to hide it.
                    assert guard_expected and "'float' and 'NoneType'" in str(error)
                    assert state.instances['coop']['fight_consumed_battle'] == state.battle_count
                    failed_delay = True
            assert failed_delay == guard_expected
            message = {'main': main, 'sub': sub, 'hex': payload.hex().upper()}
        steps.append({'message': message, 'excluded_source_delay_failure': failed_delay, 'expected': {
            'packet_count': state.packet_count, 'battle_count': state.battle_count,
            'active': state.battle.get('active'), 'war_style': state.battle.get('war_style'),
            'winner_side': state.battle.get('winner_side'), 'role_id': state.player.get('role_id'),
            'units': [{'slot': key, 'pid': value['pid'], 'exited': value.get('exited', False)}
                      for key, value in state.battle_units.items()],
            'instances': copy.deepcopy(state.snapshot()['instances'])}})
    SCENARIOS.append((name, {'initial_coop': seed or {}, 'steps': steps}))

for col in range(1, 5):
    for side in (1, 2):
        scenario(f'column_{col}_winner_{side}_role_exit',
                 [world(), count(3), style(), start(unit(col=col)), winner(side), exit_role(),
                  exit_unit(col), exit_role()])
scenario('unit_exit_uses_post_service_exited_unit',
         [world(), count(2), style(), start(unit()), winner(), exit_unit(), exit_role()])
scenario('one_remaining_fight_records_victory',
         [world(), count(1), style(), start(unit()), winner(), exit_role()])
for value, label in [(None, 'unknown'), (0, 'zero'), (-3, 'negative'), (True, 'boolean'),
                     (2.5, 'float'), ('3', 'text'), ({'count': 3}, 'map'), (2**80, 'large_integer')]:
    scenario('count_' + label, [world(), style(), start(unit()), winner(), exit_role(), exit_role()],
             {'fight_count': value, 'last_fight_victory': True})
for value in (0, 3, 255):
    scenario(f'invalid_winner_{value}', [world(), count(3), style(), start(unit()), winner(value), exit_role()])
scenario('missing_winner_is_unknown', [world(), count(3), style(), start(unit()), exit_role(), winner(), exit_role()])
for units, label in [([], 'missing_units'), ([unit(pid=72)], 'no_pid_match'),
                     ([unit(pid=8000, master=71)], 'master_is_not_own'),
                     ([unit(col=1), unit(col=2)], 'same_side_distinct_columns'),
                     ([unit(col=1), unit(col=3)], 'opposite_columns'),
                     ([unit(row=1), unit(row=2)], 'same_column_distinct_rows')]:
    scenario(label, [world(), count(3), style(), start(*units), winner(), exit_role()])
scenario('zero_pid_exits_but_cannot_win', [world(0), count(2), style(), start(unit(pid=0)), winner(), exit_unit()])
scenario('missing_identity_and_remote_or_unknown_slots_do_not_consume',
         [count(3), style(), start(unit(), unit(pid=8000, master=71, row=2)), winner(),
          exit_role(), exit_unit(), world(), exit_role(72), exit_unit(1), exit_unit(3, 2), exit_role()])
scenario('zero_battle_count_cannot_consume',
         [world(), count(3), (11, 5, b'\1' + unit()), style(), winner(), exit_role(), exit_unit()])
for value in (None, 0, 9):
    scenario('noncoop_style_' + str(value), [world(), count(3)] + ([] if value is None else [style(value)]) +
             [start(unit(style=16)), winner(), exit_role()])
scenario('independent_battle_guard_survives_role_changes_and_fresh_context',
         [world(), count(3), style(), start(unit(), unit(pid=72, row=2)), winner(), exit_role(),
          world(72), guarded(exit_role(72)), world(), guarded(exit_unit()),
          'fresh_context', guarded(exit_role())])
for marker, label in [(1.0, 'float'), (True, 'boolean')]:
    scenario('imported_marker_' + label,
             [world(), style(), start(unit()), winner(), guarded(exit_role())],
             {'fight_count': 3, 'fight_consumed_battle': marker, 'last_fight_victory': False})
scenario('count_receipt_clears_marker_but_not_exit_context',
         [world(), count(3), style(), start(unit(), unit(pid=72, row=2)), winner(), exit_role(),
          count(5), exit_role(), exit_unit(), world(72), exit_role(72),
          style(), start(unit(pid=72)), winner(2), exit_role(72)])
scenario('new_battle_can_consume_and_winner_does_not_retroactively_rewrite_result',
         [world(), count(3), style(), start(unit()), exit_unit(), winner(), exit_role(),
          style(), start(unit()), winner(), exit_role()])
scenario('fresh_context_keeps_consumption_marker_but_not_pending_announcement',
         [world(), count(3), style(), start(unit()), winner(), exit_role(), style(),
          'fresh_context', guarded(exit_role()), start(unit()), exit_role()])
# Actual room/match and reward receipts prove composition retains every coop field,
# including entry-observer phase changes before the receive-only bookkeeping.
room = (186, 3, p('BBHBBBB', 0, 1, 500, 1, 1, 1, 1) + p('IBIIII', 71, 0, 1, 2, 3, 4))
match = (186, 2, p('BBII', 18, 1, 71, 72))
scenario('full_instance_state_preserves_entry_reward_and_room_observers',
         [world(), room, match, count(3), style(), start(unit()), winner(),
          (186, 11, p('BBBBB', 2, 1, 1, 1, 2)), exit_role(), (186, 13, b''),
          count(4), exit_role(), style(), start(unit()), winner(2), exit_unit()])

sources = ['wlre/network/client.py', 'wlre/services/instance_combat.py', 'wlre/services/instances.py',
           'wlre/services/instance_entry.py', 'wlre/core/state.py', 'wlre/core/state_battle_events.py',
           'wlre/network/protocol.py', 'wlre/network/layouts.py', 'wlre/network/instances.py']
provenance = {name: hashlib.sha256((ROOT / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for name in sources}
lines = ['// Generated by CoopFightReceiveGenerateVectors.py. Synthetic offline data only.',
         'namespace Lala.Core.Tests.Sessions.Receive;', 'public static class CoopFightReceivePythonVectors', '{',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(provenance, separators=(',', ':'))) + ';',
         '    public static IEnumerable<object[]> Sequences()', '    {']
for name, sequence in SCENARIOS:
    lines.append('        yield return new object[] { ' + json.dumps(name) + ', ' + csharp_gzip_json(json.dumps(sequence, separators=(',', ':'))) + ' };')
lines += ['    }', '}']
Path(__file__).with_name('CoopFightReceivePythonVectors.cs').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'{len(SCENARIOS)} sequences / {sum(len(data["steps"]) for _, data in SCENARIOS)} snapshots / '
      f'{sum(step["excluded_source_delay_failure"] for _, data in SCENARIOS for step in data["steps"])} excluded source delay failures')
