"""Regression coverage for P1a cooperative feature extraction."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.features.cooperative.buttons import CooperativeActionsMixin
from wlre.features.cooperative.rooms import cooperative_headcount_status
from wlre.ui.instance_ui import InstanceModePage, room_headcount_status


class CooperativeFeatureStructure(unittest.TestCase):
    def test_legacy_room_actions_are_inherited_unchanged(self):
        for name in ('request_standby', 'request_reward_claim',
                     'request_reward_cancel', 'request_auto_reward'):
            with self.subTest(method=name):
                self.assertIs(getattr(InstanceModePage, name),
                              getattr(CooperativeActionsMixin, name))

    def test_cooperative_headcount_requires_verified_full_roster(self):
        room = {'room_id': 99, 'capacity': 2, 'host_id': 10, 'standby': False}
        members = [{'role_id': 10}, {'role_id': 20}]
        data = {'room': room, 'members': members}
        self.assertEqual(room_headcount_status('coop', data, can_begin=True),
                         cooperative_headcount_status(room, members, 2,
                                                      can_begin=True))
        self.assertIn('可以準備', room_headcount_status('coop', data,
                                                can_begin=True))
        self.assertIn('尚缺 1 人', room_headcount_status(
            'coop', {'room': room, 'members': members[:1]}, can_begin=True))
        self.assertIn('容量尚未同步', room_headcount_status(
            'coop', {'room': {'room_id': 99}, 'members': members}))

    def test_standby_never_sends_without_local_guard(self):
        page = CooperativeActionsMixin()
        page.cooperative = True
        page._standby_ready = False
        page._room_data = {'room': {'room_id': 99, 'standby': False}}
        sender = Mock()
        page.app = SimpleNamespace(live_active=True, send=sender)
        page._update_room_buttons = Mock()
        page.winfo_toplevel = lambda: None
        page.request_standby()
        sender.assert_not_called()
        page._standby_ready = True
        with patch('wlre.features.cooperative.buttons.messagebox.askyesno',
                   return_value=True):
            page.request_standby()
        sender.assert_called_once_with({
            'type': 'instance_coop_standby', 'mode': 'coop', 'standby': True})
        self.assertFalse(page._standby_ready)


if __name__ == '__main__':
    unittest.main()
