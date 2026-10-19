"""Official 1262 room creation: guarded send, server ACK, and no duplicate fee."""
import unittest

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.instance_creation import expire, disconnect


def ready():
    state = State(phase='world_ready', initial_data_complete=True)
    state.player = {'role_id': 678}
    logic = SessionLogic()
    logic.world_acknowledged = True
    return state, logic


def main_create(logic, state, *, public=True, password=''):
    return logic.command({
        'type': 'instance_create', 'mode': 'main',
        'map_id': 30012, 'public': public, 'password': password}, state)


def coop_create(logic, state, *, dungeon_id=21, public=True, password='',
                cost=True, partner=False):
    return logic.command({
        'type': 'instance_create', 'mode': 'coop',
        'dungeon_id': dungeon_id, 'player_count': 2,
        'public': public, 'password': password,
        'confirm_cost': cost, 'confirm_partner': partner}, state)


class RoomCreation(unittest.TestCase):
    def test_main_public_room_and_authoritative_host_ack(self):
        state, logic = ready()
        self.assertEqual(main_create(logic, state),
                         [Packet(85, 3, Writer().u16(30012).u8(1).u16(0).u8(0).build())])
        with self.assertRaises(ProtocolError):
            main_create(logic, state)
        self.assertIsNotNone(state.instances['main']['create_pending'])
        self.assertIsNone(state.instances['main']['room'])
        state.apply(decode(Packet(85, 2, b'\x00')))
        self.assertTrue(state.instances['main']['create_pending']['ack'])
        self.assertIsNone(state.instances['main']['room'])
        # Unrelated server room cannot close the local pending request.
        state.apply(decode(Packet(85, 5, Writer().u8(1).u8(1).u16(30012)
                                .u8(1).u32(1111).build())))
        self.assertIsNotNone(state.instances['main']['create_pending'])
        state.apply(decode(Packet(85, 5, Writer().u8(1).u8(1).u16(30012)
                                .u8(1).u32(678).build())))
        self.assertIsNone(state.instances['main']['create_pending'])
        self.assertEqual(state.instances['main']['create_result'], 0)
        self.assertEqual(state.instances['main']['room']['host_id'], 678)
        with self.assertRaises(ProtocolError):
            main_create(logic, state)

    def test_main_private_password_and_rejection(self):
        state, logic = ready()
        self.assertEqual(main_create(logic, state, public=False, password='0123'),
                         [Packet(85, 3, Writer().u16(30012).u8(0).u16(123).build())])
        self.assertNotIn('0123', repr(state.snapshot()))
        state.apply(decode(Packet(85, 2, b'\x02')))
        self.assertIsNone(state.instances['main']['create_pending'])
        self.assertEqual(state.instances['main']['create_result'], 2)
        self.assertIn('等級不足', state.instances['main']['status'])
        with self.assertRaises(ProtocolError):
            main_create(logic, state, public=False, password='0000')
        with self.assertRaises(ProtocolError):
            main_create(logic, state, public=False, password='１234')

    def test_coop_public_and_private_with_deduction_confirmation(self):
        state, logic = ready()
        self.assertEqual(coop_create(logic, state, public=False, password='0123'),
                         [Packet(186, 1, Writer().u8(2).u8(1).u8(0).u8(0)
                                 .u32(123).u8(0).build())])
        state.apply(decode(Packet(186, 2, b'\x09')))
        self.assertTrue(state.instances['coop']['create_pending']['ack'])
        self.assertIsNone(state.instances['coop']['room'])
        roster = Writer().u8(1).u8(0).u16(91).u8(0).u8(1).u8(0).u8(2)
        for role_id in (678, 889):
            roster.u32(role_id).u8(1).u32(100).u32(100).u32(20).u32(30)
        state.apply(decode(Packet(186, 3, roster.build())))
        self.assertIsNone(state.instances['coop']['create_pending'])
        self.assertEqual(state.instances['coop']['room']['room_id'], 91)
        self.assertEqual(state.instances['coop']['create_result'], 9)
        self.assertNotIn('0123', repr(state.snapshot()))
        with self.assertRaises(ProtocolError):
            coop_create(logic, state)

    def test_named_event_creation_uses_original_npc_index(self):
        for dungeon_id, npc in ((27, 1), (28, 2)):
            with self.subTest(dungeon_id=dungeon_id):
                state, logic = ready()
                self.assertEqual(coop_create(logic, state, dungeon_id=dungeon_id),
                                 [Packet(186, 1, Writer().u8(2).u8(2).u8(npc)
                                         .u8(1).u32(0).u8(0).build())])

    def test_coop_server_rejection_and_cost_explicit(self):
        state, logic = ready()
        with self.assertRaises(ProtocolError):
            coop_create(logic, state, cost=False)
        self.assertIsNone(state.instances['coop']['create_pending'])
        coop_create(logic, state)
        state.apply(decode(Packet(186, 2, b'\x06')))
        self.assertEqual(state.instances['coop']['create_result'], 6)
        self.assertIsNone(state.instances['coop']['create_pending'])
        self.assertIn('門票不足', state.instances['coop']['status'])

    def test_timeout_prevents_retry_even_after_belated_result(self):
        state, logic = ready()
        main_create(logic, state)
        started = state.instances['main']['create_pending']['started']
        self.assertFalse(expire(state, started + 19.9))
        self.assertTrue(expire(state, started + 20))
        self.assertTrue(state.instances['main']['create_uncertain'])
        self.assertIsNone(state.instances['main']['create_pending'])
        with self.assertRaises(ProtocolError):
            main_create(logic, state)
        state.apply(decode(Packet(85, 2, b'\x00')))
        self.assertTrue(state.instances['main']['create_uncertain'])
        with self.assertRaises(ProtocolError):
            coop_create(logic, state)
        self.assertFalse(expire(state, started + 30))

    def test_disconnect_marks_outcome_uncertain(self):
        state, logic = ready()
        coop_create(logic, state)
        disconnect(state)
        self.assertTrue(state.instances['coop']['create_uncertain'])
        self.assertIsNone(state.instances['coop']['create_pending'])
        with self.assertRaises(ProtocolError):
            main_create(logic, state)

    def test_eligibility_and_parallel_mode_gates(self):
        state, logic = ready()
        state.battle['active'] = True
        with self.assertRaises(ProtocolError):
            main_create(logic, state)
        state.battle['active'] = False
        state.auto_battle['enabled'] = True
        with self.assertRaises(ProtocolError):
            main_create(logic, state)
        state.auto_battle['enabled'] = False
        coop_create(logic, state)
        with self.assertRaises(ProtocolError):
            main_create(logic, state)
        state2, logic2 = ready()
        state2.initial_data_complete = False
        with self.assertRaises(ProtocolError):
            main_create(logic2, state2)
