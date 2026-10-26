"""P1b normal dungeon feature regression: exact legacy API and safety gates."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.features.dungeon.buttons import DungeonActionsMixin
from wlre.features.dungeon.details import dungeon_details
from wlre.features.dungeon.panel import DungeonModePage
from wlre.features.dungeon.readiness import DungeonRoomReadinessMixin
from wlre.features.dungeon.rooms import dungeon_headcount_status
from wlre.ui.instance_ui import InstanceModePage, instance_details, room_headcount_status


STAGE = {'kind': 1, 'id': 2, 'map_id': 30012,
         'min_members': 2, 'max_members': 4}
ROSTER = [{'role_id': 678}, {'role_id': 889}]
ROOM = {'room_id': 30012, 'host_id': 678, 'members': 2}


class DungeonExtractionContract(unittest.TestCase):
    def test_public_methods_remain_inherited(self):
        self.assertTrue(issubclass(DungeonModePage, InstanceModePage))
        for name in ('request_start', 'request_enter'):
            with self.subTest(name=name):
                self.assertIs(getattr(InstanceModePage, name),
                              getattr(DungeonActionsMixin, name))
        self.assertIs(InstanceModePage.render_dungeon_readiness,
                      DungeonRoomReadinessMixin.render_dungeon_readiness)

    def test_headcount_requires_verified_roster_not_capacity(self):
        with patch('wlre.features.dungeon.rooms.entries_for',
                   return_value=(STAGE,)):
            self.assertIn('尚缺 1 人', dungeon_headcount_status(
                dict(ROOM, members=1), ROSTER[:1], 1, 678))
            full = dungeon_headcount_status(ROOM, ROSTER, 2, 678,
                                            can_begin=True)
            self.assertIn('房主可以開始挑戰', full)
            self.assertIn('2/2 人', full)
            self.assertIn('成員名單尚未完整同步', dungeon_headcount_status(
                dict(ROOM, members=1), ROSTER, 2, 678, can_begin=True))
            self.assertIn('成員名單尚未完整同步', dungeon_headcount_status(
                ROOM, ROSTER, 2, 999, can_begin=True))
            self.assertIn('超出官方人數上限', dungeon_headcount_status(
                dict(ROOM, members=5),
                [{'role_id': 678}] * 5, 5, 678))
            self.assertIn('無法判定最低人數', dungeon_headcount_status(
                dict(ROOM, room_id=999), ROSTER, 2, 678))

    def test_start_and_enter_readiness_uses_server_roster_and_cross_mode_lock(self):
        page = DungeonRoomReadinessMixin()
        page.cooperative = False
        page.catalog_records = (STAGE,)
        data = {'phase': 'waiting'}
        page.render_dungeon_readiness(data, {}, True, ROSTER, ROOM,
                                      678, 10000, False)
        self.assertTrue(page._start_ready)
        self.assertFalse(page._enter_ready)
        page.render_dungeon_readiness(data, {'join_pending': {'id': 1}},
                                      True, ROSTER, ROOM, 678, 10000, False)
        self.assertFalse(page._start_ready)
        page.render_dungeon_readiness(data, {}, True, ROSTER,
                                      dict(ROOM, members=1), 678, 10000, False)
        self.assertFalse(page._start_ready)
        page.render_dungeon_readiness(data, {}, True, ROSTER,
                                      dict(ROOM, host_id=889), 678, 10000, False)
        self.assertFalse(page._start_ready)
        data['phase'] = 'started'
        page.render_dungeon_readiness(data, {}, True, ROSTER, ROOM,
                                      678, 10000, False)
        self.assertFalse(page._start_ready)
        self.assertTrue(page._enter_ready)
        page.render_dungeon_readiness(data, {}, True, ROSTER, ROOM,
                                      678, 30012, False)
        self.assertFalse(page._enter_ready)
        page.render_dungeon_readiness(data, {}, True, ROSTER, ROOM,
                                      678, 10000, True)
        self.assertFalse(page._enter_ready)

    def test_manual_actions_require_confirmation_and_lock_before_send(self):
        page = DungeonActionsMixin()
        page.cooperative = False
        page.app = SimpleNamespace(live_active=True, send=Mock())
        page._room_data = {'room': ROOM}
        page._update_room_buttons = Mock()
        page.winfo_toplevel = Mock(return_value=None)
        page._start_ready = False
        page.request_start()
        page.app.send.assert_not_called()
        page._start_ready = True
        with patch('wlre.features.dungeon.buttons.messagebox.askyesno',
                   return_value=False):
            page.request_start()
        page.app.send.assert_not_called()
        with patch('wlre.features.dungeon.buttons.messagebox.askyesno',
                   return_value=True):
            page.request_start()
        page.app.send.assert_called_once_with({
            'type': 'instance_start', 'mode': 'main'})
        self.assertFalse(page._start_ready)
        page.request_start()
        self.assertEqual(page.app.send.call_count, 1)
        page.app.send.reset_mock()
        page._enter_ready = True
        with patch('wlre.features.dungeon.buttons.messagebox.askyesno',
                   return_value=True):
            page.request_enter()
        page.app.send.assert_called_once_with({
            'type': 'instance_enter', 'mode': 'main'})
        self.assertFalse(page._enter_ready)
        page.app.send.reset_mock()
        page.cooperative = True
        page._start_ready = True
        page._enter_ready = True
        page.request_start()
        page.request_enter()
        page.app.send.assert_not_called()

    def test_settlement_details_preserve_legacy_content(self):
        data = {
            'objectives': {
                'targets': {1: {'npc_id': 30, 'kills': 2, 'required': 3}},
                'boss': {'npc_id': 77, 'defeated': True},
                'scores': {'678': {'normal': 4, 'boss': 5}},
                'records': [{'id': 678}],
            },
            'completed': True,
        }
        text = dungeon_details(data, 678)
        self.assertEqual(text, instance_details(data, False, 678))
        for expected in ('擊殺目標', 'Boss NPC77', '個人積分',
                         '新式副本結算紀錄', '伺服器已確認'):
            self.assertIn(expected, text)
        self.assertEqual(dungeon_details({}), '')


if __name__ == '__main__':
    unittest.main()
