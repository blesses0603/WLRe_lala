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


class CooperativeRoomExtractionTests(unittest.TestCase):
    """Second-batch room dialogs and explicit cooperative feature contracts."""

    def test_public_room_actions_still_inherit_from_shared_dialogs(self):
        from wlre.ui.instance_room_dialogs import InstanceRoomDialogMixin
        for name in ('open_create_dialog', 'open_join_dialog', 'request_leave'):
            with self.subTest(name=name):
                self.assertIs(getattr(InstanceModePage, name),
                              getattr(InstanceRoomDialogMixin, name))

    def test_cooperative_page_inherits_original_public_api(self):
        from wlre.features.cooperative.panel import CooperativeModePage
        self.assertTrue(issubclass(CooperativeModePage, InstanceModePage))

    def test_cooperative_count_must_match_catalog_bounds(self):
        from wlre.features.cooperative.rooms import cooperative_checked_count
        record = {'id': 28, 'min_members': 2, 'max_members': 4}
        self.assertEqual(cooperative_checked_count('2', record), 2)
        self.assertEqual(cooperative_checked_count('4', record), 4)
        for invalid in ('', 'wrong', '1', '5', None):
            with self.subTest(value=invalid):
                self.assertIsNone(cooperative_checked_count(invalid, record))

    def test_cooperative_room_commands_keep_explicit_cost_approval(self):
        from wlre.features.cooperative.rooms import (
            cooperative_create_fields, cooperative_join_fields,
        )
        record = {'id': 28, 'min_members': 2, 'max_members': 4}
        self.assertEqual(cooperative_create_fields(record, 3), {
            'dungeon_id': 28, 'player_count': 3, 'confirm_cost': True,
        })
        self.assertEqual(cooperative_join_fields(), {'confirm_cost': True})


if __name__ == '__main__':
    unittest.main()
