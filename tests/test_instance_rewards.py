"""Phase 07: authoritative instance completion and safe co-op free rewards."""
import sys
import os
import tkinter as tk
import unittest
from unittest.mock import patch

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet, Writer, ProtocolError
from wlre.services.instance_rewards import (
    tick, expire, disconnect, _safe_bag
)


def ready():
    state = State(phase='world_ready', initial_data_complete=True)
    state.player = {'role_id': 678, 'scene': 12000}
    state.knowledge['active_npc_id'] = 1555
    state.inventory = {'ready': True, 'reliable': True, 'capacity': 20,
                       'items': {}, 'reserved': {}, 'revision': 1}
    logic = SessionLogic()
    logic.world_acknowledged = True
    return state, logic


def status(state, open_reward=1, reward_mark=1, count=3, win=3):
    state.apply(decode(Packet(186, 11, Writer().u8(count).u8(win)
                              .u8(open_reward).u8(reward_mark).u8(0).build())))


def action(logic, state, kind, **kwargs):
    return logic.command({'type': kind, 'mode': 'coop', **kwargs}, state)


class CompletionAndRewards(unittest.TestCase):
    def test_normal_complete_only_on_authoritative_notice(self):
        state, _ = ready()
        state.instances['main']['phase'] = 'entered'
        state.apply({'type': 'winner', 'side': 1})
        self.assertFalse(state.instances['main']['completed'])
        state.apply(decode(Packet(85, 15)))
        self.assertTrue(state.instances['main']['completed'])
        self.assertEqual(state.instances['main']['completion_source'], 'S85-15')
        self.assertEqual(state.instances['main']['phase'], 'completed')

    def test_new_dungeon_completion_only_after_server_notice(self):
        state, _ = ready()
        state.apply({'type': 'instance_new_info', 'mode': 'main', 'kind': 100})
        self.assertTrue(state.instances['main']['completed'])
        self.assertEqual(state.instances['main']['completion_source'], 'S85-21-100')

    def test_coop_progress_does_not_fake_full_completion(self):
        state, _ = ready()
        status(state, 0, 0, count=3, win=2)
        self.assertFalse(state.instances['coop']['completed'])
        status(state, 1, 1, count=3, win=3)
        self.assertTrue(state.instances['coop']['completed'])
        self.assertEqual(state.instances['coop']['completion_source'], 'S186-11')

    def test_claim_free_once_with_exact_packet_and_award_receipt(self):
        state, logic = ready()
        status(state)
        self.assertEqual(action(logic, state, 'instance_reward_claim', action='free'),
                         [Packet(186, 10)])
        pending = state.instances['coop']['claim_pending']
        self.assertIsNotNone(pending)
        with self.assertRaises(ProtocolError):
            action(logic, state, 'instance_reward_claim', action='free')
        self.assertEqual(tick(state), [])
        payload = Writer().u8(10).u32(12345).u32(2).build()
        state.apply(decode(Packet(186, 10, payload)))
        data = state.instances['coop']
        self.assertIsNone(data['claim_pending'])
        self.assertEqual(data['claim_result'], 'confirmed')
        self.assertEqual(data['received_awards'],
                         [{'kind': 10, 'id': 12345, 'value': 2}])
        with self.assertRaises(ProtocolError):
            action(logic, state, 'instance_reward_claim', action='free')
        status(state, 0, 0)
        self.assertIsNone(data['reward_handled_fingerprint'])
        self.assertEqual(state.knowledge['active_npc_id'], 1555)

    def test_s186_10_strict_length_and_no_payload_is_not_award(self):
        state, logic = ready()
        with self.assertRaises(ProtocolError):
            decode(Packet(186, 10, b'\0' * 8))
        with self.assertRaises(ProtocolError):
            decode(Packet(186, 10, b'\0' * 45))
        status(state)
        action(logic, state, 'instance_reward_claim', action='free')
        state.apply(decode(Packet(186, 10)))
        self.assertIsNotNone(state.instances['coop']['claim_pending'])
        self.assertIsNone(state.instances['coop']['claim_result'])
        status(state, 0, 0)
        self.assertEqual(state.instances['coop']['claim_result'],
                         'server_closed_unverified_awards')

    def test_previous_award_receipt_never_confirms_new_empty_response(self):
        state, logic = ready()
        status(state)
        action(logic, state, 'instance_reward_claim', action='free')
        state.apply(decode(Packet(186, 10, Writer().u8(10).u32(1234).u32(1).build())))
        self.assertEqual(len(state.instances['coop']['received_awards']), 1)
        status(state, 0, 0)
        status(state, 1, 1)
        action(logic, state, 'instance_reward_claim', action='free')
        self.assertEqual(state.instances['coop']['received_awards'], [])
        state.apply(decode(Packet(186, 10)))
        status(state, 0, 0)
        self.assertEqual(state.instances['coop']['claim_result'],
                         'server_closed_unverified_awards')

    def test_paid_reward_never_claimed_and_cancel_is_manual(self):
        state, logic = ready()
        action(logic, state, 'instance_auto_reward', enabled=True)
        status(state, 2, 1)
        self.assertEqual(tick(state), [])
        with self.assertRaises(ProtocolError):
            action(logic, state, 'instance_reward_claim', action='free')
        with self.assertRaises(ProtocolError):
            action(logic, state, 'instance_reward_cancel')
        self.assertEqual(action(logic, state, 'instance_reward_cancel',
                                confirm_cancel=True), [Packet(186, 21)])
        self.assertEqual(tick(state), [])
        status(state, 0, 0)
        self.assertEqual(state.instances['coop']['cancel_result'], 'confirmed')

    def test_disabled_by_default_and_opt_in_auto_free_one_shot(self):
        state, logic = ready()
        status(state)
        self.assertFalse(state.instances['coop']['auto_claim_enabled'])
        self.assertEqual(tick(state), [])
        self.assertEqual(action(logic, state, 'instance_auto_reward', enabled=True), [])
        self.assertEqual(tick(state, 100), [Packet(186, 10)])
        self.assertEqual(tick(state, 100.1), [])
        state.apply(decode(Packet(186, 10, Writer().u8(1).u32(0).u32(25).build())))
        self.assertEqual(tick(state, 101), [])
        state.apply(decode(Packet(186, 11, bytes([3, 3, 1, 1, 0]))))
        self.assertEqual(tick(state, 102), [])
        action(logic, state, 'instance_auto_reward', enabled=False)
        self.assertEqual(tick(state, 103), [])
        disconnect(state)
        self.assertFalse(state.instances['coop']['auto_claim_enabled'])

    def test_bag_full_unreliable_reserved_and_no_reward_mark(self):
        state, logic = ready()
        action(logic, state, 'instance_auto_reward', enabled=True)
        status(state, 1, 0)
        self.assertEqual(tick(state), [])
        status(state, 1, 1)
        for bad in ({'ready': False}, {'reliable': False},
                    {'capacity': 3}, {'items': {str(i): {} for i in range(18)}},
                    {'reserved': {'1': 1}}, {'holds': {'battle': {'1': 1}}}):
            with self.subTest(bad=bad):
                bag = state.inventory.copy()
                bag.update(bad)
                state.inventory = bag
                self.assertEqual(tick(state), [])
                self.assertIsNone(state.instances['coop']['claim_pending'])
        state.inventory = {'ready': True, 'reliable': True, 'capacity': 20,
                           'items': {}, 'reserved': {}, 'revision': 1}
        self.assertTrue(_safe_bag(state))
        self.assertEqual(tick(state), [Packet(186, 10)])

    def test_does_not_claim_during_postbattle_or_other_pending_tasks(self):
        state, logic = ready()
        status(state)
        action(logic, state, 'instance_auto_reward', enabled=True)
        state.battle['post_event'] = {'status': 'cooperative_wait'}
        self.assertEqual(tick(state), [])
        self.assertIsNone(state.instances['coop']['claim_pending'])
        state.battle['post_event']['status'] = 'completed'
        state.maintenance['pending'] = {'started': 1}
        self.assertEqual(tick(state), [])
        state.maintenance['pending'] = None
        self.assertEqual(tick(state), [Packet(186, 10)])

    def test_pending_timeout_disconnect_freeze_auto_and_manual(self):
        state, logic = ready()
        status(state)
        action(logic, state, 'instance_auto_reward', enabled=True)
        self.assertEqual(tick(state, 100), [Packet(186, 10)])
        self.assertFalse(expire(state, 124.9))
        self.assertTrue(expire(state, 125))
        self.assertTrue(state.instances['coop']['reward_uncertain'])
        self.assertEqual(tick(state, 126), [])
        with self.assertRaises(ProtocolError):
            action(logic, state, 'instance_reward_claim', action='free')
        state2, logic2 = ready()
        status(state2)
        action(logic2, state2, 'instance_reward_claim', action='free')
        disconnect(state2)
        self.assertTrue(state2.instances['coop']['reward_uncertain'])
        with self.assertRaises(ProtocolError):
            action(logic2, state2, 'instance_reward_cancel', confirm_cancel=True)

    def test_old_room_actions_block_when_reward_pending(self):
        state, logic = ready()
        status(state)
        action(logic, state, 'instance_reward_claim', action='free')
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_create', 'mode': 'main',
                           'map_id': 30012, 'public': True}, state)
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_enter', 'mode': 'main'}, state)

    def test_cooperative_postbattle_wait_uses_single_server_event(self):
        state, logic = ready()
        state.instances['coop']['fight_count'] = 3
        state.battle_count = 1
        state.battle = {'active': True, 'war_style': 16, 'winner_side': 1}
        state.battle_units['4:1'] = {'col': 4, 'row': 1, 'pid': 678}
        event = {'type': 'fight_exit', 'role_id': 678}
        state.apply(event)
        with patch('wlre.network.client.time.monotonic', return_value=100):
            logic.receive(event, state)
        self.assertEqual(state.battle['post_event']['status'], 'cooperative_wait')
        self.assertEqual(state.battle['post_event']['delay_seconds'], 5)
        with patch('wlre.network.client.time.monotonic', return_value=104.9):
            self.assertEqual(logic.flush_events(state), [])
        with patch('wlre.network.client.time.monotonic', return_value=105):
            packets = logic.flush_events(state)
        self.assertEqual(packets, [Packet(20, 6, b'\x00')])
        with patch('wlre.network.client.time.monotonic', return_value=200):
            self.assertEqual(logic.flush_events(state), [])
        self.assertFalse(state.instances['coop']['completed'])

    def test_unknown_fight_count_follows_official_default_continuation_once(self):
        state, logic = ready()
        state.battle_count = 1
        state.battle = {'active': True, 'war_style': 16, 'winner_side': 1}
        event = {'type': 'fight_exit', 'role_id': 678}
        state.apply(event)
        with patch('wlre.network.client.time.monotonic', return_value=100):
            logic.receive(event, state)
        self.assertEqual(logic.post_battle_due, 102.5)
        self.assertEqual(state.battle['post_event']['status'], 'cooperative_wait')
        self.assertEqual(state.battle['post_event']['delay_seconds'], 2.5)
        self.assertTrue(state.event_flow['blocked'])
        self.assertIsNone(state.instances['coop']['fight_count'])
        with patch('wlre.network.client.time.monotonic', return_value=102.49):
            self.assertEqual(logic.flush_events(state), [])
        with patch('wlre.network.client.time.monotonic', return_value=102.5):
            self.assertEqual(logic.flush_events(state), [Packet(20, 6, b'\x00')])
        with patch('wlre.network.client.time.monotonic', return_value=103):
            self.assertEqual(logic.flush_events(state), [])
        # One continuation is not evidence of completing an instance.
        self.assertFalse(state.instances['coop']['completed'])


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin',
                     'Requires desktop/Xvfb')
class RewardUI(unittest.TestCase):
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

    def snapshot(self, reward=1):
        data = State().snapshot()
        data['player']['role_id'] = 678
        data['inventory'].update(ready=True, reliable=True, capacity=20, items={})
        data['instances']['coop']['reward'] = dict(
            reward_count=3, win_stage=3, open_reward=reward,
            reward_mark=1, npc_id=0)
        return data

    def test_manual_free_claim_requires_confirmation(self):
        data = self.snapshot()
        self.app.instance_panel.render(data, live=True)
        self.assertTrue(self.page.claim_button.instate(['!disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=False):
                self.page.claim_button.invoke()
                send.assert_not_called()
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=True):
                self.page.claim_button.invoke()
                send.assert_called_once_with(
                    {'type': 'instance_reward_claim', 'mode': 'coop', 'action': 'free'})
        self.assertTrue(self.page.claim_button.instate(['disabled']))
        data['instances']['coop']['claim_pending'] = {'started': 1}
        self.app.instance_panel.render(data, live=True)
        self.assertTrue(self.page.claim_button.instate(['disabled']))

    def test_paid_button_must_never_auto_claim(self):
        data = self.snapshot(reward=2)
        self.app.instance_panel.render(data, live=True)
        self.assertTrue(self.page.claim_button.instate(['disabled']))
        self.assertTrue(self.page.cancel_reward_button.instate(['!disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=True):
                self.page.cancel_reward_button.invoke()
                send.assert_called_once_with(
                    {'type': 'instance_reward_cancel', 'mode': 'coop',
                     'confirm_cancel': True})
        self.assertTrue(self.page.cancel_reward_button.instate(['disabled']))

    def test_auto_claim_is_explicit_and_bag_space_is_a_gate(self):
        data = self.snapshot()
        data['inventory']['reliable'] = False
        self.app.instance_panel.render(data, live=True)
        self.assertTrue(self.page.claim_button.instate(['disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=True):
                self.page.auto_reward_button.invoke()
                send.assert_called_once_with(
                    {'type': 'instance_auto_reward', 'mode': 'coop', 'enabled': True})
        self.assertTrue(self.page.auto_reward_button.instate(['disabled']))
