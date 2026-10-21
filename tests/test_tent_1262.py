"""1262 帳篷控制與「目前活動」回歸測試；不需要正式伺服器。"""
import struct
import unittest

from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.world.tent import (
    HOUSE_SCENES, TIMEOUT, activity_text, command, expire,
)
from wlre.ui.overview_ui import summarize


def camp(owner=91, tent_id=3, x=150, y=220, kind=1, make=0):
    return struct.pack('<IHIIBB', owner, tent_id, x, y, kind, make)


def ready():
    state = State(phase='world_ready', initial_data_complete=True)
    state.player = {'role_id': 91, 'scene': 12170, 'name': '測試角色', 'x': 1, 'y': 2}
    return state


def observe(state, packet):
    event = decode(packet, state.player.get('role_id'))
    state.apply(event)
    return event


class TentProtocol1262Tests(unittest.TestCase):
    def test_single_and_batched_camp_records(self):
        event = decode(Packet(65, 1, camp()), 91)
        self.assertEqual(event['tent']['tent_id'], 3)
        self.assertEqual(event['tent']['owner_id'], 91)
        batch = decode(Packet(65, 3, camp(11) + camp(91)), 91)
        self.assertEqual([row['owner_id'] for row in batch['tents']], [11, 91])
        self.assertEqual(decode(Packet(65, 3), 91)['tents'], [])

    def test_bad_record_lengths_are_rejected(self):
        for sub, body in ((1, b'\x00'), (3, b'\x00'*15), (4, b''), (7, b'\x00'), (16, b''), (18, b'')):
            with self.subTest(sub=sub), self.assertRaises(ProtocolError):
                decode(Packet(65, sub, body), 91)

    def test_reply_events_are_not_interpreted_as_success(self):
        self.assertEqual(decode(Packet(65, 2), 91)['type'], 'tent_limit')
        self.assertEqual(decode(Packet(65, 8), 91)['type'], 'tent_entry_denied')
        self.assertEqual(decode(Packet(65, 16, b'\x02'), 91)['code'], 2)
        self.assertFalse(decode(Packet(65, 7, b'\x01\x00'), 91)['access_open'])
        self.assertEqual(decode(Packet(65, 2, b'\x01'), 91)['type'], 'unimplemented')


class TentStateAndCommandsTests(unittest.TestCase):
    def test_explicit_open_and_ack(self):
        state = ready()
        packets = command(state, {'action': 'open'}, now=10)
        self.assertEqual([(p.main, p.sub, p.payload) for p in packets], [(65, 6, b'')])
        self.assertFalse(state.tent['visible'])
        self.assertEqual(state.tent['pending']['action'], 'open')
        observe(state, Packet(65, 1, camp()))
        self.assertTrue(state.tent['visible'])
        self.assertIsNone(state.tent['pending'])
        self.assertEqual(state.tent['deployed_scene'], 12170)

    def test_other_player_never_acks_local_open(self):
        state = ready()
        command(state, {'action': 'open'}, now=10)
        observe(state, Packet(65, 1, camp(owner=101)))
        self.assertFalse(state.tent['visible'])
        self.assertIsNotNone(state.tent['pending'])

    def test_scene_snapshot_does_not_guess_other_scene_closed(self):
        state = ready()
        observe(state, Packet(65, 1, camp()))
        observe(state, Packet(12, 1, struct.pack('<IHHH', 91, 12001, 3, 5)))
        self.assertFalse(state.tent['visible'])
        self.assertEqual(state.tent['deployed_scene'], 12170)
        with self.assertRaisesRegex(ProtocolError, '目前場景'):
            command(state, {'action': 'enter'}, now=12)
        observe(state, Packet(65, 3))
        self.assertEqual(state.tent['deployed_scene'], 12170)

    def test_enter_packet_requires_present_local_tent(self):
        state = ready()
        with self.assertRaises(ProtocolError):
            command(state, {'action': 'enter'}, now=10)
        observe(state, Packet(65, 3, camp()))
        packets = command(state, {'action': 'enter'}, now=10)
        self.assertEqual([(p.main, p.sub, p.payload) for p in packets],
                         [(65, 1, struct.pack('<I', 91))])
        self.assertFalse(state.tent['inside'])

    def test_house_scene_and_furniture_confirmation_both_needed(self):
        state = ready()
        observe(state, Packet(65, 1, camp()))
        command(state, {'action': 'enter'}, now=10)
        observe(state, Packet(62, 4, struct.pack('<I', 91)))
        self.assertFalse(state.tent['inside'])
        self.assertIsNotNone(state.tent['pending'])
        observe(state, Packet(12, 1, struct.pack('<IHHH', 91, 10299, 8, 9)))
        self.assertIn(10299, HOUSE_SCENES)
        self.assertTrue(state.tent['inside'])
        self.assertIsNone(state.tent['pending'])

    def test_house_scene_without_furniture_does_not_confirm_enter(self):
        state = ready()
        observe(state, Packet(65, 1, camp()))
        command(state, {'action': 'enter'}, now=10)
        observe(state, Packet(12, 1, struct.pack('<IHHH', 91, 10299, 8, 9)))
        self.assertFalse(state.tent['inside'])
        self.assertEqual(state.tent['pending']['action'], 'enter')

    def test_close_requires_deployment_and_ack(self):
        state = ready()
        with self.assertRaises(ProtocolError):
            command(state, {'action': 'close'}, now=10)
        observe(state, Packet(65, 1, camp()))
        packets = command(state, {'action': 'close'}, now=10)
        self.assertEqual([(p.main, p.sub, p.payload) for p in packets], [(65, 2, b'')])
        self.assertTrue(state.tent['visible'])
        observe(state, Packet(65, 4, struct.pack('<I', 91)))
        self.assertFalse(state.tent['visible'])
        self.assertIsNone(state.tent['deployed_scene'])
        self.assertIsNone(state.tent['pending'])

    def test_rejection_and_timeout_never_retry(self):
        state = ready()
        command(state, {'action': 'open'}, now=5)
        with self.assertRaisesRegex(ProtocolError, '等待伺服器'):
            command(state, {'action': 'open'}, now=5)
        self.assertFalse(expire(state, now=5+TIMEOUT-1))
        self.assertTrue(expire(state, now=5+TIMEOUT))
        self.assertTrue(state.tent['uncertain'])
        with self.assertRaisesRegex(ProtocolError, '結果不明'):
            command(state, {'action': 'open'}, now=30)
        self.assertFalse(expire(state, now=31))
        state2 = ready()
        command(state2, {'action': 'open'}, now=5)
        observe(state2, Packet(65, 2))
        self.assertIsNone(state2.tent['pending'])
        self.assertIn('上限', state2.tent['status'])

    def test_no_open_or_close_inside_house(self):
        state = ready()
        state.player['scene'] = 10000
        with self.assertRaisesRegex(ProtocolError, '小屋內'):
            command(state, {'action': 'open'}, now=1)
        state.tent['deployed_scene'] = 12170
        with self.assertRaisesRegex(ProtocolError, '小屋內'):
            command(state, {'action': 'close'}, now=1)

    def test_unrelated_removal_does_not_clear_own_tent(self):
        state = ready()
        observe(state, Packet(65, 1, camp()))
        observe(state, Packet(65, 4, struct.pack('<I', 100)))
        self.assertTrue(state.tent['visible'])

    def test_activity_shows_tent_status_and_awaiting(self):
        state = ready()
        self.assertIn('帳篷｜', summarize(state.snapshot(), True, {})['activity'])
        observe(state, Packet(65, 1, camp()))
        self.assertIn('150、220', activity_text(state.tent))
        self.assertIn('已展開', summarize(state.snapshot(), True, {})['activity'])
        command(state, {'action': 'close'}, now=1)
        self.assertIn('等待伺服器', summarize(state.snapshot(), True, {})['activity'])


if __name__ == '__main__':
    unittest.main()
