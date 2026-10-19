"""Co-op standby uses current normal deployed NPC, never switches pets."""
import os
import tkinter as tk
import unittest
from unittest.mock import patch

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet, Writer, ProtocolError
from wlre.services.instance_standby import expire, disconnect


def make_session(host=True, capacity=2, occupied=2, standby=False):
    state = State(phase='world_ready', initial_data_complete=True)
    state.player = {'role_id': 678}
    state.knowledge['active_npc_id'] = 1555
    logic = SessionLogic()
    logic.world_acknowledged = True
    packet = member_event(host=host, capacity=capacity, occupied=occupied,
                          standby=standby)
    state.apply(decode(packet))
    return state, logic


def member_event(host=True, capacity=2, occupied=2, standby=False, room_id=91):
    ids = [678, 889, 1001, 1002] if host else [889, 678, 1001, 1002]
    body = (Writer().u8(0).u8(0).u16(room_id).u8(int(standby))
            .u8(1).u8(0).u8(capacity))
    for i in range(capacity):
        rid = ids[i] if i < occupied else 0
        body.u32(rid).u8(1 if rid else 0).u32(80 if rid else 0)
        body.u32(100 if rid else 0).u32(50 if rid else 0).u32(60 if rid else 0)
    return Packet(186, 3, body.build())


def request(logic, state, value=True):
    return logic.command(
        {'type': 'instance_coop_standby', 'mode': 'coop', 'standby': value}, state)


class StandbyNetwork(unittest.TestCase):
    def test_host_ready_and_cancel_never_touch_normal_companion(self):
        state, logic = make_session()
        self.assertEqual(request(logic, state, True),
                         [Packet(186, 7, Writer().u16(91).u8(1).build())])
        self.assertEqual(state.knowledge['active_npc_id'], 1555)
        self.assertIsNone(state.instances['coop']['standby_result'])
        with self.assertRaises(ProtocolError):
            request(logic, state, True)
        state.apply(decode(Packet(186, 20, b'\x01')))
        self.assertIsNotNone(state.instances['coop']['standby_pending'])
        state.apply(decode(member_event(room_id=88, standby=True)))
        self.assertIsNotNone(state.instances['coop']['standby_pending'])
        state.apply(decode(member_event(standby=True)))
        self.assertIsNone(state.instances['coop']['standby_pending'])
        self.assertIs(state.instances['coop']['standby_result'], True)
        self.assertTrue(state.instances['coop']['room']['standby'])
        self.assertEqual(request(logic, state, False),
                         [Packet(186, 7, Writer().u16(91).u8(0).build())])
        state.apply(decode(member_event(standby=False)))
        self.assertIs(state.instances['coop']['standby_result'], False)
        self.assertEqual(state.knowledge['active_npc_id'], 1555)

    def test_non_host_and_not_full_cannot_toggle(self):
        guest, logic = make_session(host=False)
        with self.assertRaisesRegex(ProtocolError, '房主'):
            request(logic, guest)
        short, logic = make_session(occupied=1)
        with self.assertRaisesRegex(ProtocolError, '全員到齊'):
            request(logic, short)
        state, logic = make_session()
        with self.assertRaises(ProtocolError):
            request(logic, state, 1)
        with self.assertRaises(ProtocolError):
            request(logic, state, False)

    def test_normal_companion_absent_does_not_force_deployment(self):
        state, logic = make_session()
        state.knowledge['active_npc_id'] = None
        self.assertEqual(request(logic, state), [
            Packet(186, 7, Writer().u16(91).u8(1).build())])
        self.assertIsNone(state.knowledge['active_npc_id'])

    def test_other_room_operations_block_ready(self):
        for key, value in [('create_pending', {'started': 0}),
                           ('join_pending', {'started': 0}),
                           ('leave_pending', {'started': 0}),
                           ('standby_uncertain', True)]:
            with self.subTest(key=key):
                state, logic = make_session()
                state.instances['main'][key] = value
                with self.assertRaises(ProtocolError):
                    request(logic, state)

    def test_timeout_unknown_outcome_and_disconnect(self):
        state, logic = make_session()
        request(logic, state)
        started = state.instances['coop']['standby_pending']['started']
        self.assertFalse(expire(state, started + 19))
        self.assertTrue(expire(state, started + 20))
        self.assertTrue(state.instances['coop']['standby_uncertain'])
        with self.assertRaises(ProtocolError):
            request(logic, state)
        again, logic = make_session()
        request(logic, again)
        disconnect(again)
        self.assertTrue(again.instances['coop']['standby_uncertain'])
        self.assertIsNone(again.instances['coop']['standby_pending'])


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt',
                     'Requires desktop/Xvfb')
class StandbyUI(unittest.TestCase):
    def setUp(self):
        from wlre.ui.gui import App
        self.root = tk.Tk()
        self.app = App(self.root)
        self.app.show_main()
        self.app.live_active = True
        self.page = self.app.instance_panel.coop_page

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()

    def data(self, host=True, full=True, standby=False):
        state = State().snapshot()
        state['player']['role_id'] = 678
        state['knowledge']['active_npc_id'] = 1555
        members = [{'role_id': 678}, {'role_id': 889}] if host else [
            {'role_id': 889}, {'role_id': 678}]
        state['instances']['coop'].update(
            room={'room_id': 91, 'kind': 1, 'npc_id': 0,
                  'capacity': 2, 'standby': standby},
            members=members if full else members[:1],
            phase='waiting', standby=standby,
        )
        return state

    def test_ready_button_requires_host_full_room_and_confirms(self):
        data = self.data()
        self.app.instance_panel.render(data, live=True)
        self.assertIn('NPC ID 1555', self.page.companion_note.get())
        self.assertTrue(self.page.standby_button.instate(['!disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=False):
                self.page.standby_button.invoke()
                send.assert_not_called()
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=True):
                self.page.standby_button.invoke()
                send.assert_called_once_with(
                    {'type': 'instance_coop_standby', 'mode': 'coop', 'standby': True})
                self.assertTrue(self.page.standby_button.instate(['disabled']))
        self.assertEqual(data['knowledge']['active_npc_id'], 1555)

    def test_cancel_ready_and_restricted_guest_or_partial_room(self):
        data = self.data(standby=True)
        self.app.instance_panel.render(data, live=True)
        self.assertEqual(self.page.standby_button.cget('text'), '取消準備')
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=True):
                self.page.standby_button.invoke()
                send.assert_called_once_with(
                    {'type':'instance_coop_standby', 'mode':'coop', 'standby':False})
        self.app.instance_panel.render(self.data(host=False), live=True)
        self.assertTrue(self.page.standby_button.instate(['disabled']))
        self.app.instance_panel.render(self.data(full=False), live=True)
        self.assertTrue(self.page.standby_button.instate(['disabled']))
        pending = self.data()
        pending['instances']['coop']['standby_pending'] = {
            'room_id': 91, 'started': 0, 'target': True}
        self.app.instance_panel.render(pending, live=True)
        self.assertTrue(self.page.standby_button.instate(['disabled']))
