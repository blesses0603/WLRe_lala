"""Official 1262 C85-7 host start, ACK, safety and existing companion."""
import os
import tkinter as tk
import unittest
from unittest.mock import patch

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.instance_start import expire, disconnect


def start_fixture(*, owner=True, count=2, roster=2, waiting=True):
    state = State(phase='world_ready', initial_data_complete=True)
    state.player = {'role_id': 678}
    state.knowledge['active_npc_id'] = 1555
    logic = SessionLogic()
    logic.world_acknowledged = True
    host = 678 if owner else 889
    state.apply(decode(Packet(85, 5, Writer().u8(1).u8(1).u16(30012)
                             .u8(count).u32(host).build())))
    if roster:
        state.apply(decode(Packet(85, 4, Writer().u16(30012).u8(roster)
                                 .raw(b''.join(Writer().u32(rid).build()
                                               for rid in ([678, 889, 1000][:roster]))).build())))
    if not waiting:
        state.apply(decode(Packet(85, 5, b'\x03')))
    return state, logic


def command(logic, state):
    return logic.command({'type': 'instance_start', 'mode': 'main'}, state)


class StartChallenge(unittest.TestCase):
    def test_owner_start_has_empty_packet_and_never_changes_companion(self):
        state, logic = start_fixture()
        self.assertEqual(command(logic, state), [Packet(85, 7)])
        self.assertEqual(state.knowledge['active_npc_id'], 1555)
        self.assertEqual(state.instances['main']['phase'], 'waiting')
        self.assertIsNotNone(state.instances['main']['start_pending'])
        with self.assertRaises(ProtocolError):
            command(logic, state)
        state.apply(decode(Packet(85, 5, b'\x03')))
        self.assertIsNone(state.instances['main']['start_pending'])
        self.assertEqual(state.instances['main']['start_result'], 'confirmed')
        self.assertEqual(state.instances['main']['phase'], 'started')
        self.assertEqual(state.knowledge['active_npc_id'], 1555)
        with self.assertRaises(ProtocolError):
            command(logic, state)

    def test_non_owner_or_insufficient_members_cannot_start(self):
        for opts in ({'owner': False}, {'count': 1, 'roster': 1},
                     {'count': 3, 'roster': 2}, {'count': 2, 'roster': 0},
                     {'waiting': False}):
            with self.subTest(opts=opts):
                state, logic = start_fixture(**opts)
                with self.assertRaises(ProtocolError):
                    command(logic, state)
                self.assertIsNone(state.instances['main']['start_pending'])

    def test_late_start_and_room_departure_are_uncertain_not_retried(self):
        state, logic = start_fixture()
        command(logic, state)
        started = state.instances['main']['start_pending']['started']
        self.assertFalse(expire(state, started + 19.9))
        self.assertTrue(expire(state, started + 20))
        self.assertTrue(state.instances['main']['start_uncertain'])
        with self.assertRaises(ProtocolError):
            command(logic, state)
        state.apply(decode(Packet(85, 5, b'\x03')))
        self.assertTrue(state.instances['main']['start_uncertain'])
        other, logic2 = start_fixture()
        command(logic2, other)
        other.apply(decode(Packet(85, 5, b'\x02')))
        self.assertTrue(other.instances['main']['start_uncertain'])
        self.assertIsNone(other.instances['main']['start_pending'])

    def test_disconnect_and_cross_mode_blocks(self):
        state, logic = start_fixture()
        command(logic, state)
        disconnect(state)
        self.assertTrue(state.instances['main']['start_uncertain'])
        self.assertIsNone(state.instances['main']['start_pending'])
        for k in ('create_pending', 'join_pending', 'leave_pending',
                  'standby_pending', 'start_pending'):
            state, logic = start_fixture()
            state.instances['coop'][k] = {'started': 0}
            with self.subTest(other_pending=k), self.assertRaises(ProtocolError):
                command(logic, state)
        state, logic = start_fixture()
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_start', 'mode': 'coop'}, state)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt',
                     'Requires desktop/Xvfb')
class StartChallengeUI(unittest.TestCase):
    def setUp(self):
        from wlre.ui.gui import App
        self.root = tk.Tk()
        self.app = App(self.root)
        self.app.show_main()
        self.app.live_active = True
        self.page = self.app.instance_panel.main_page

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()

    def snapshot(self, *, owner=True, count=2, roster=2):
        state = State().snapshot()
        state['player']['role_id'] = 678
        state['knowledge']['active_npc_id'] = 1555
        state['instances']['main'].update(
            room={'room_id': 30012, 'host_id': 678 if owner else 889,
                  'members': count}, phase='waiting',
            members=[{'role_id': rid} for rid in ([678, 889, 1000][:roster])])
        return state

    def test_start_button_host_only_and_confirmation(self):
        data = self.snapshot()
        self.app.instance_panel.render(data, live=True)
        self.assertTrue(self.page.start_button.instate(['!disabled']))
        self.assertIn('已達最低人數', self.page.headcount_note.get())
        self.assertIn('房主可以開始挑戰', self.page.headcount_note.get())
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=False):
                self.page.start_button.invoke()
                send.assert_not_called()
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=True):
                self.page.start_button.invoke()
                send.assert_called_once_with({'type': 'instance_start', 'mode': 'main'})
        self.assertTrue(self.page.start_button.instate(['disabled']))
        self.assertEqual(data['knowledge']['active_npc_id'], 1555)

    def test_denies_guest_short_or_pending_start(self):
        for opts in ({'owner': False}, {'count': 1, 'roster': 1},
                     {'count': 3, 'roster': 2}):
            with self.subTest(opts=opts):
                self.app.instance_panel.render(self.snapshot(**opts), live=True)
                self.assertTrue(self.page.start_button.instate(['disabled']))
                self.assertNotIn('房主可以開始挑戰', self.page.headcount_note.get())
        data = self.snapshot()
        data['instances']['main']['start_pending'] = {
            'room_id': 30012, 'started': 0}
        self.app.instance_panel.render(data, live=True)
        self.assertTrue(self.page.start_button.instate(['disabled']))
        self.app.instance_panel.render(self.snapshot(), live=False)
        self.assertTrue(self.page.start_button.instate(['disabled']))
