"""Official 1262: C85-9 entry and server-paired C186 combat."""
from _tk_native_pump import create_root
import sys
import os
import tkinter as tk
import unittest
from unittest.mock import patch

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.instance_entry import enter, expire, disconnect


def fixture():
    state = State(phase='world_ready', initial_data_complete=True)
    state.player = {'role_id': 678, 'scene': 12000}
    state.knowledge['active_npc_id'] = 1555
    logic = SessionLogic()
    logic.world_acknowledged = True
    state.apply(decode(Packet(85, 5, Writer().u8(1).u8(1).u16(30012)
                              .u8(2).u32(678).build())))
    state.apply(decode(Packet(85, 4, Writer().u16(30012).u8(2)
                              .u32(678).u32(889).build())))
    return state, logic


def begin(state):
    state.apply(decode(Packet(85, 5, b'\x03')))


def pos(role, scene):
    return dict(type='position_snapshot', role_id=role, scene=scene,
                x=10, y=20, source='S7-1')


class Entry(unittest.TestCase):
    def test_entry_only_after_start_and_own_authoritative_scene(self):
        state, logic = fixture()
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_enter', 'mode': 'main'}, state)
        begin(state)
        self.assertEqual(logic.command({'type': 'instance_enter', 'mode': 'main'}, state),
                         [Packet(85, 9)])
        self.assertEqual(state.instances['main']['phase'], 'started')
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_enter', 'mode': 'main'}, state)
        state.apply(pos(889, 30012))
        self.assertIsNotNone(state.instances['main']['enter_pending'])
        state.apply(pos(678, 9999))
        self.assertIsNotNone(state.instances['main']['enter_pending'])
        state.apply(pos(678, 30012))
        data = state.instances['main']
        self.assertIsNone(data['enter_pending'])
        self.assertEqual(data['enter_result'], 'confirmed')
        self.assertEqual(data['phase'], 'entered')
        self.assertEqual(data['entered_scene'], 30012)
        self.assertEqual(state.knowledge['active_npc_id'], 1555)
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_enter', 'mode': 'main'}, state)

    def test_guest_can_enter_but_coop_must_not_enter(self):
        state, logic = fixture()
        state.instances['main']['room']['host_id'] = 889
        begin(state)
        self.assertEqual(logic.command({'type': 'instance_enter', 'mode': 'main'}, state),
                         [Packet(85, 9)])
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_enter', 'mode': 'coop'}, state)

    def test_unconfirmed_roster_ongoing_action_and_battle_fail_closed(self):
        mutations = (
            lambda s: s.instances['main'].update(members=[]),
            lambda s: s.instances['coop'].update(room={'room_id': 77}),
            lambda s: s.instances['coop'].update(standby_uncertain=True),
            lambda s: s.instances['main'].update(start_pending={'started': 1}),
            lambda s: s.instances['main'].update(leave_pending={'started': 1}),
            lambda s: s.player.update(scene=30012),
            lambda s: s.battle.update(active=True),
        )
        for mutation in mutations:
            state, logic = fixture()
            begin(state)
            mutation(state)
            with self.subTest(mutation=mutation), self.assertRaises(ProtocolError):
                logic.command({'type': 'instance_enter', 'mode': 'main'}, state)
            self.assertIsNone(state.instances['main']['enter_pending'])

    def test_expire_disconnect_and_late_scene(self):
        state, _ = fixture()
        begin(state)
        enter(state, {'mode': 'main'}, now=100)
        self.assertFalse(expire(state, 144.9))
        self.assertTrue(expire(state, 145))
        self.assertTrue(state.instances['main']['enter_uncertain'])
        with self.assertRaises(ProtocolError):
            enter(state, {'mode': 'main'}, now=146)
        state.apply(pos(678, 30012))
        self.assertFalse(state.instances['main']['enter_uncertain'])
        self.assertEqual(state.instances['main']['enter_result'], 'confirmed')
        state2, _ = fixture()
        begin(state2)
        enter(state2, {'mode': 'main'}, now=100)
        disconnect(state2)
        self.assertTrue(state2.instances['main']['enter_uncertain'])
        self.assertIsNone(state2.instances['main']['enter_pending'])

    def test_room_close_while_pending_is_uncertain(self):
        state, logic = fixture()
        begin(state)
        logic.command({'type': 'instance_enter', 'mode': 'main'}, state)
        state.apply(decode(Packet(85, 5, b'\x02')))
        self.assertTrue(state.instances['main']['enter_uncertain'])
        self.assertIsNone(state.instances['main']['entered_scene'])

    def test_existing_battle_core_and_explicit_dungeon_completion(self):
        state, logic = fixture()
        begin(state)
        logic.command({'type': 'instance_enter', 'mode': 'main'}, state)
        state.apply(pos(678, 30012))
        state.apply({'type': 'battle_start', 'stage': 1, 'fight_number': 1, 'units': []})
        self.assertTrue(state.instances['main']['battle_active'])
        self.assertTrue(state.battle['active'])
        state.apply({'type': 'fight_exit', 'role_id': 678})
        self.assertFalse(state.instances['main']['battle_active'])
        self.assertFalse(state.instances['main']['completed'])
        state.apply(decode(Packet(85, 15)))
        self.assertTrue(state.instances['main']['completed'])

    def test_coop_matching_notification_no_fake_combat(self):
        state, _ = fixture()
        state.instances['main']['room'] = None
        coop = state.instances['coop']
        coop['room'] = {'room_id': 77, 'standby': True}
        coop['standby'] = True
        coop['phase'] = 'waiting'
        roster = (Writer().u32(901).u8(5).u8(1).u8(0).u8(1)
                  .u32(0).u32(0).u8(0).build())
        event = decode(Packet(186, 2, b'\x11\x01' + roster))
        self.assertEqual(event['type'], 'instance_coop_match')
        state.apply(event)
        self.assertEqual(coop['phase'], 'matched')
        self.assertFalse(coop['battle_active'])
        state.apply({'type': 'battle_start', 'stage': 1, 'fight_number': 2, 'units': []})
        self.assertEqual(coop['phase'], 'combat')
        state.apply({'type': 'winner', 'side': 1})
        self.assertEqual(coop['phase'], 'matched')
        self.assertIsNone(coop['reward'])
        self.assertEqual(state.knowledge['active_npc_id'], 1555)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin',
                     'Requires desktop/Xvfb')
class EntryUI(unittest.TestCase):
    def setUp(self):
        from wlre.ui.gui import App
        self.root = create_root()
        self.app = App(self.root)
        self.app.show_main()
        self.app.live_active = True
        self.page = self.app.instance_panel.main_page

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()

    def test_click_requires_server_started_and_explicit_confirmation(self):
        snap = State().snapshot()
        snap['player'].update(role_id=678, scene=12000)
        snap['instances']['main'].update(
            room={'room_id': 30012, 'host_id': 678, 'members': 2},
            phase='started', members=[{'role_id': 678}, {'role_id': 889}])
        self.app.instance_panel.render(snap, live=True)
        self.assertTrue(self.page.enter_button.instate(['!disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=False):
                self.page.enter_button.invoke()
                send.assert_not_called()
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=True):
                self.page.enter_button.invoke()
                send.assert_called_once_with({'type': 'instance_enter', 'mode': 'main'})
        self.assertTrue(self.page.enter_button.instate(['disabled']))
        snap['instances']['main']['enter_pending'] = {'started': 1}
        self.app.instance_panel.render(snap, live=True)
        self.assertTrue(self.page.enter_button.instate(['disabled']))
        snap['instances']['main']['enter_pending'] = None
        snap['instances']['main']['phase'] = 'waiting'
        self.app.instance_panel.render(snap, live=True)
        self.assertTrue(self.page.enter_button.instate(['disabled']))
        self.app.instance_panel.render(snap, live=False)
        self.assertTrue(self.page.enter_button.instate(['disabled']))
        self.assertTrue(self.app.instance_panel.coop_page.enter_button.instate(['disabled']))
