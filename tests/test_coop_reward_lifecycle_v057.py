"""v0.5.7 cooperative reward/room ordering, manual release and safe diagnostics."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wlre.core.diagnostics import Diagnostics
from wlre.core.state import State
from wlre.network.client import coop_state_trace, run_client
from wlre.network.protocol import decode
from wlre.network.wire import Packet, Writer, ProtocolError, encode
from wlre.services.instance_room_flow import coop_completed_no_chest, leave
from wlre.ui.instance_ui import creation_block_reasons


def ready():
    state = State(phase='world_ready', initial_data_complete=True)
    state.player = {'role_id': 678, 'scene': 12000}
    return state


def reward_packet(open_reward=1, mark=1, win=3, count=3):
    return Packet(186, 11, Writer().u8(count).u8(win).u8(open_reward)
                  .u8(mark).u8(0).build())


def member_event(room_id, standby=True):
    return {'type': 'instance_members', 'mode': 'coop',
            'room_id': room_id, 'host_id': 678,
            'standby': standby, 'kind': 1, 'npc_id': 0,
            'capacity': 1, 'members': [{'role_id': 678}]}


def member_packet(room_id, standby=True):
    payload = (Writer().u8(1).u8(1).u16(room_id).u8(int(standby))
               .u8(1).u8(0).u8(1)
               .u32(678).u8(0).u32(100).u32(100).u32(80).u32(80))
    return Packet(186, 3, payload.build())


class CoopLifecycle(unittest.TestCase):
    def test_first_room_snapshot_does_not_erase_earlier_reward_and_completion(self):
        state = ready()
        state.apply(decode(reward_packet()))
        data = state.instances['coop']
        self.assertEqual(data['reward']['open_reward'], 1)
        self.assertTrue(data['completed'])
        state.apply(member_event(23))
        self.assertEqual(data['reward']['open_reward'], 1)
        self.assertEqual(data['completion_source'], 'S186-11')
        self.assertTrue(data['completed'])
        self.assertEqual(data['room']['room_id'], 23)

    def test_real_room_transition_still_clears_unclaimed_old_session_evidence(self):
        state = ready()
        state.apply(member_event(23))
        state.apply(decode(reward_packet(open_reward=0, mark=0)))
        self.assertTrue(state.instances['coop']['completed'])
        state.apply(member_event(24))
        data = state.instances['coop']
        self.assertIsNone(data['reward'])
        self.assertFalse(data['completed'])
        self.assertIsNone(data['completion_source'])

    def test_room_change_does_not_erase_unresolved_claim_evidence(self):
        state = ready()
        state.apply(member_event(23))
        state.apply(decode(reward_packet()))
        data = state.instances['coop']
        data['claim_pending'] = {'fingerprint': (3, 3, 1, 1, 0), 'started': 1}
        state.apply(member_event(24))
        self.assertIsNotNone(data['claim_pending'])
        self.assertEqual(data['reward']['open_reward'], 1)

    def test_manual_leave_only_when_server_confirmed_completed_and_empty_chest(self):
        state = ready()
        state.apply(member_event(23, standby=True))
        data = state.instances['coop']
        data['phase'] = 'matched'
        state.battle['post_event'] = {'status': 'completed'}
        self.assertFalse(coop_completed_no_chest(data))
        with self.assertRaises(ProtocolError):
            leave(state, {'mode': 'coop'})
        state.apply(decode(reward_packet(open_reward=1)))
        self.assertFalse(coop_completed_no_chest(data))
        with self.assertRaises(ProtocolError):
            leave(state, {'mode': 'coop'})
        state.apply(decode(reward_packet(open_reward=0, mark=0)))
        self.assertTrue(coop_completed_no_chest(data))
        self.assertEqual(leave(state, {'mode': 'coop'}), [Packet(186, 5)])
        self.assertIsNotNone(data['leave_pending'])
        with self.assertRaises(ProtocolError):
            leave(state, {'mode': 'coop'})

    def test_missing_reward_does_not_unlock_buttons_and_is_explained(self):
        state = ready()
        state.apply(member_event(23, standby=True))
        state.instances['coop']['phase'] = 'matched'
        state.battle['post_event'] = {'status': 'completed'}
        snap = state.snapshot()
        reasons = creation_block_reasons(snap, 'coop', True)
        self.assertIn('協力戰後尚未同步 S186-11 獎勵狀態', reasons)
        self.assertFalse(coop_completed_no_chest(state.instances['coop']))
        state.apply(decode(reward_packet(open_reward=0, mark=0)))
        self.assertNotIn('協力戰後尚未同步 S186-11 獎勵狀態',
                         creation_block_reasons(state.snapshot(), 'coop', True))

    def test_anonymous_log_accepts_known_transition_and_rejects_private_strings(self):
        state = ready()
        state.player['name'] = 'PRIVATE-CHARACTER'
        state.apply(decode(reward_packet(open_reward=1)))
        trace = coop_state_trace(state, 'instance_reward_status')
        self.assertEqual(trace['source'], 'instance_reward_status')
        self.assertTrue(trace['reward_known'])
        self.assertEqual(trace['open_reward'], 1)
        self.assertNotIn('PRIVATE-CHARACTER', str(trace))
        with tempfile.TemporaryDirectory() as folder:
            diagnostic = Diagnostics(folder)
            self.assertTrue(diagnostic.coop_state_trace(trace))
            self.assertFalse(diagnostic.coop_state_trace(trace))
            self.assertFalse(diagnostic.coop_state_trace({**trace, 'source': 'PRIVATE-CHARACTER'}))
            self.assertFalse(diagnostic.coop_state_trace({**trace, 'phase': 'PRIVATE-CHARACTER'}))
            self.assertFalse(diagnostic.coop_state_trace({**trace, 'open_reward': 'PRIVATE-CHARACTER'}))
            self.assertFalse(diagnostic.coop_state_trace({**trace, 'room_known': 'PRIVATE-CHARACTER'}))
            diagnostic.close()
            logged = Path(diagnostic.path).read_text(encoding='utf8')
            self.assertIn('coop_state source=instance_reward_status', logged)
            self.assertIn('reward_known=1 open_reward=1', logged)
            self.assertNotIn('PRIVATE-CHARACTER', logged)
            # 日誌時間戳的毫秒可能剛好是 678；只檢查被匿名化的事件內容。
            trace_lines = [line.partition('coop_state ')[2] for line in logged.splitlines()
                           if 'coop_state ' in line]
            self.assertEqual(len(trace_lines), 1)
            self.assertNotIn('678', trace_lines[0])

    def test_wire_reward_then_first_room_info_survives_and_trace_is_present(self):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.recv.side_effect = [
            encode(reward_packet(), 0),
            encode(member_packet(23), 0),
            b'',
        ]
        events = []
        with patch('wlre.network.client.socket.create_connection', return_value=connection):
            state = run_client('fixture.invalid', 1, {'rx_xor': 0, 'tx_xor': 0},
                               events.append, duration=None)
        self.assertEqual(state.instances['coop']['reward']['open_reward'], 1)
        transitions = [v for v in events if v.get('type') == 'coop_state_trace']
        self.assertEqual([x['source'] for x in transitions],
                         ['instance_reward_status', 'instance_members'])
        self.assertTrue(all(x['reward_known'] for x in transitions))
        self.assertFalse(any(x.get('reason') == 'client_error' for x in events))


if __name__ == '__main__':
    unittest.main()
