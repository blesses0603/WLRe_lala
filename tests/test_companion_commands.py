import copy
import unittest
from unittest.mock import patch

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError


class CompanionCommands(unittest.TestCase):
    def setUp(self):
        self.state = State(phase='world_ready')
        self.state.knowledge.update(companions_ready=True, companions={
            '2': {'ready': True, 'index': 2, 'npc_id': 0x1234, 'stats': {'can_grow': 1}}})
        self.logic = SessionLogic()
        self.logic.world_acknowledged = True
        self.value = {'type': 'companion', 'action': 'deploy', 'index': 2, 'npc_id': 0x1234}

    def test_lua_packet_and_authoritative_acknowledgment(self):
        packet, = self.logic.command(self.value, self.state)
        self.assertEqual((packet.main, packet.sub, packet.payload), (19, 1, b'\x34\x12\x00\x00'))
        self.assertIsNone(self.state.knowledge['active_npc_id'])
        self.state.apply(decode(Packet(19, 1, b'\x34\x12\x00\x00')))
        self.assertEqual(self.state.knowledge['active_npc_id'], 0x1234)
        with patch('wlre.network.client.time.monotonic', return_value=self.logic.last_companion_time + 3):
            packet, = self.logic.command({**self.value, 'action': 'rest'}, self.state)
        self.assertEqual((packet.main, packet.sub, packet.payload), (19, 2, b''))
        self.assertEqual(self.state.knowledge['active_npc_id'], 0x1234)
        self.state.apply(decode(Packet(19, 2, b'')))
        self.assertIsNone(self.state.knowledge['active_npc_id'])

    def test_stale_identity_unsynced_battle_and_activity_are_rejected(self):
        for change in ('identity', 'sync', 'battle', 'event', 'activity', 'follow_only', 'offline'):
            with self.subTest(change=change):
                state = copy.deepcopy(self.state)
                if change == 'identity': state.knowledge['companions']['2']['npc_id'] = 999
                if change == 'sync': state.knowledge['companions_ready'] = False
                if change == 'battle': state.battle['active'] = True
                if change == 'event': state.event_flow['blocked'] = True
                if change == 'activity': state.activities['鍛鍊'] = True
                if change == 'follow_only': state.knowledge['companions']['2']['stats']['can_grow'] = 0
                if change == 'offline': state.phase = 'disconnected'
                with self.assertRaises(ProtocolError): self.logic.command(self.value, state)

    def test_duplicate_commands_and_resting_wrong_companion_are_rejected(self):
        with self.assertRaises(ProtocolError):
            self.logic.command({**self.value, 'action': 'rest'}, self.state)
        with patch('wlre.network.client.time.monotonic', return_value=100):
            self.logic.command(self.value, self.state)
            with self.assertRaises(ProtocolError): self.logic.command(self.value, self.state)
