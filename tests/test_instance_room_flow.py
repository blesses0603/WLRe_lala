"""Server-room join/leave, result correlation and safe manual dispatch."""
import time
import unittest

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.instance_room_flow import expire, disconnect


def session():
    state = State(phase='world_ready', initial_data_complete=True)
    state.player = {'role_id': 678}
    logic = SessionLogic()
    logic.world_acknowledged = True
    return state, logic


def main_list(room_id=30012, sn=55, public=True):
    name = '房主'.encode('utf-16le')
    guild = '團'.encode('utf-16le')
    return Packet(85, 1, Writer().u8(1).u16(room_id)
                  .u8(len(name)).raw(name).u8(2)
                  .u8(len(guild)).raw(guild).u8(1 if public else 0)
                  .u16(sn).build())


def coop_list(room_id=91, public=True, capacity=4, members=2):
    return Packet(186, 17, Writer().u16(1).u8(1 if public else 0)
                  .u8(2).u8(1).u16(room_id).u8(capacity)
                  .u8(members).u32(1111).build())


def main_join(logic, state, *, public=True, password='', room_id=30012, sn=55):
    return logic.command({'type': 'instance_join', 'mode': 'main',
                          'room_id': room_id, 'sn': sn, 'password': password}, state)


def coop_join(logic, state, *, password='', room_id=91, confirm_cost=True):
    return logic.command({'type': 'instance_join', 'mode': 'coop',
                          'room_id': room_id, 'password': password,
                          'confirm_cost': confirm_cost}, state)


def coop_members(room_id=91, joined=True):
    body = Writer().u8(0).u8(1 if joined else 0).u16(room_id)
    body.u8(0).u8(2).u8(1).u8(2)
    for rid in (1111, 678):
        body.u32(rid).u8(1).u32(80).u32(100).u32(50).u32(60)
    return Packet(186, 3, body.build())


class InstanceJoinLeave(unittest.TestCase):
    def test_main_join_requires_list_sn_and_authoritative_phase(self):
        state, logic = session()
        with self.assertRaises(ProtocolError):
            main_join(logic, state)
        state.apply(decode(main_list()))
        with self.assertRaises(ProtocolError):
            main_join(logic, state, sn=56)
        self.assertEqual(main_join(logic, state), [
            Packet(85, 5, Writer().u16(30012).u16(55).build())])
        with self.assertRaises(ProtocolError):
            main_join(logic, state)
        self.assertIsNone(state.instances['main']['room'])
        state.apply(decode(Packet(85, 3, b'\x00')))
        self.assertTrue(state.instances['main']['join_pending']['accepted'])
        self.assertIsNone(state.instances['main']['room'])
        # Different map/room must not confirm our requested join.
        state.apply(decode(Packet(85, 5, Writer().u8(1).u8(1)
                                .u16(30016).u8(2).u32(1111).build())))
        self.assertIsNotNone(state.instances['main']['join_pending'])
        state.apply(decode(Packet(85, 5, Writer().u8(1).u8(1)
                                .u16(30012).u8(2).u32(1111).build())))
        self.assertIsNone(state.instances['main']['join_pending'])
        self.assertEqual(state.instances['main']['join_result'], 0)
        self.assertEqual(state.instances['main']['room']['room_id'], 30012)

    def test_main_private_password_no_persistence_and_rejection(self):
        state, logic = session()
        state.apply(decode(main_list(public=False)))
        self.assertEqual(main_join(logic, state, password='0123'), [
            Packet(85, 5, Writer().u16(30012).u16(55).u16(123).build())])
        self.assertNotIn('0123', repr(state.snapshot()))
        state.apply(decode(Packet(85, 3, b'\x08')))
        self.assertEqual(state.instances['main']['join_result'], 8)
        self.assertIsNone(state.instances['main']['join_pending'])
        self.assertIn('密碼錯誤', state.instances['main']['status'])
        with self.assertRaises(ProtocolError):
            main_join(logic, state, password='１２３４')
        with self.assertRaises(ProtocolError):
            main_join(logic, state, password='0000')

    def test_coop_join_requires_explicit_cost_and_matching_member(self):
        state, logic = session()
        state.apply(decode(coop_list(public=False)))
        with self.assertRaises(ProtocolError):
            coop_join(logic, state, password='0123', confirm_cost=False)
        self.assertEqual(coop_join(logic, state, password='0123'), [
            Packet(186, 4, Writer().u16(91).u32(123).build())])
        self.assertNotIn('0123', repr(state.snapshot()))
        state.apply(decode(Packet(186, 2, b'\x0a')))
        self.assertTrue(state.instances['coop']['join_pending']['accepted'])
        state.apply(decode(coop_members(room_id=100)))
        self.assertIsNotNone(state.instances['coop']['join_pending'])
        state.apply(decode(coop_members()))
        self.assertIsNone(state.instances['coop']['join_pending'])
        self.assertEqual(state.instances['coop']['join_result'], 10)
        self.assertEqual(state.instances['coop']['room']['room_id'], 91)
        self.assertEqual(len(state.instances['coop']['members']), 2)

    def test_coop_full_rejected_without_sending(self):
        state, logic = session()
        state.apply(decode(coop_list(capacity=2,members=2)))
        with self.assertRaises(ProtocolError):
            coop_join(logic, state)
        self.assertIsNone(state.instances['coop']['join_pending'])

    def test_coop_server_rejects_bad_password(self):
        state, logic = session()
        state.apply(decode(coop_list(public=False)))
        coop_join(logic, state, password='4321')
        state.apply(decode(Packet(186, 2, b'\x0e')))
        self.assertEqual(state.instances['coop']['join_result'], 14)
        self.assertIn('密碼錯誤', state.instances['coop']['status'])

    def test_leaving_main_only_when_waiting_and_server_confirms(self):
        state, logic = session()
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_leave', 'mode': 'main'}, state)
        state.apply(decode(Packet(85, 5, Writer().u8(1).u8(1)
                                .u16(30012).u8(2).u32(1111).build())))
        self.assertEqual(logic.command({'type': 'instance_leave','mode':'main'}, state),
                         [Packet(85, 6)])
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_leave','mode':'main'}, state)
        self.assertIsNotNone(state.instances['main']['room'])
        state.apply(decode(Packet(85, 5, b'\x02')))
        self.assertIsNone(state.instances['main']['room'])
        self.assertIsNone(state.instances['main']['leave_pending'])
        self.assertEqual(state.instances['main']['leave_result'], 'success')

    def test_leaving_coop_only_with_server_186_13(self):
        state, logic = session()
        state.apply(decode(coop_members(joined=True)))
        self.assertEqual(logic.command({'type':'instance_leave','mode':'coop'}, state),
                         [Packet(186, 5)])
        state.apply(decode(Packet(186, 13)))
        self.assertIsNone(state.instances['coop']['room'])
        self.assertEqual(state.instances['coop']['leave_result'], 'success')

    def test_pending_timeout_prevents_retries_and_other_mode(self):
        state, logic = session()
        state.apply(decode(main_list()))
        main_join(logic, state)
        started = state.instances['main']['join_pending']['started']
        self.assertFalse(expire(state, started + 19))
        self.assertTrue(expire(state, started + 20))
        self.assertTrue(state.instances['main']['join_uncertain'])
        with self.assertRaises(ProtocolError):
            main_join(logic, state)
        with self.assertRaises(ProtocolError):
            logic.command({'type':'instance_create','mode':'coop',
                           'dungeon_id':21,'player_count':2,
                           'public':True,'password':'','confirm_cost':True}, state)
        state.apply(decode(Packet(85, 3, b'\x00')))
        self.assertTrue(state.instances['main']['join_uncertain'])

    def test_leave_timeout_and_disconnect_uncertainty(self):
        state, logic = session()
        state.apply(decode(coop_members()))
        logic.command({'type':'instance_leave','mode':'coop'}, state)
        start = state.instances['coop']['leave_pending']['started']
        self.assertTrue(expire(state, start + 20))
        self.assertTrue(state.instances['coop']['leave_uncertain'])
        with self.assertRaises(ProtocolError):
            logic.command({'type':'instance_leave','mode':'coop'}, state)
        other, logic2 = session()
        other.apply(decode(main_list()))
        main_join(logic2, other)
        disconnect(other)
        self.assertIsNone(other.instances['main']['join_pending'])
        self.assertTrue(other.instances['main']['join_uncertain'])

    def test_stale_server_list_and_other_activities(self):
        state, logic = session()
        state.apply(decode(main_list()))
        state.instances['main']['list_updated_at'] = time.monotonic() - 121
        with self.assertRaises(ProtocolError):
            main_join(logic, state)
        state.apply(decode(main_list()))
        state.auto_battle['enabled'] = True
        with self.assertRaises(ProtocolError):
            main_join(logic, state)
        state.auto_battle['enabled'] = False
        main_join(logic, state)
        with self.assertRaises(ProtocolError):
            logic.command({'type':'instance_leave','mode':'main'}, state)
