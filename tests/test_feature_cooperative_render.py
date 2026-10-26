"""P1a third batch: cooperative status, rewards and shared list regression."""
import unittest
from unittest.mock import Mock

from wlre.ui.instance_ui import InstanceModePage
from wlre.ui.instance_room_list import InstanceRoomListMixin
from wlre.features.cooperative.rewards import CooperativeRewardViewMixin
from wlre.features.cooperative.rooms import CooperativeRoomStatusMixin


class CooperativeRenderingStructure(unittest.TestCase):
    def test_original_ui_exposes_shared_list_and_coop_view(self):
        self.assertIs(InstanceModePage.render_room_list,
                      InstanceRoomListMixin.render_room_list)
        self.assertIs(InstanceModePage.render_cooperative_standby,
                      CooperativeRoomStatusMixin.render_cooperative_standby)
        self.assertIs(InstanceModePage.render_cooperative_rewards,
                      CooperativeRewardViewMixin.render_cooperative_rewards)

    def test_coop_standby_requires_server_confirmed_members(self):
        page = CooperativeRoomStatusMixin()
        page.cooperative = True
        page._standby_ready = False
        page.standby_note = Mock()
        room = {'room_id': 91, 'capacity': 2, 'standby': False}
        page.render_cooperative_standby(True, {'phase': 'waiting'}, room,
                                        [{'role_id': 678}], 678, 678, 2,
                                        False, False)
        self.assertIn('等待成員到齊', page.standby_note.set.call_args.args[0])
        page._standby_ready = True
        page.render_cooperative_standby(True, {'phase': 'waiting'}, room,
                                        [{'role_id': 678}, {'role_id': 889}],
                                        678, 678, 2, False, False)
        self.assertIn('可以按準備', page.standby_note.set.call_args.args[0])
        page.render_cooperative_standby(False, {}, {}, [], None, 678,
                                        None, False, False)
        self.assertEqual(page.standby_note.set.call_args.args[0],
                         '協力準備：尚未登入')

    def test_free_reward_requires_reliable_four_empty_slots(self):
        page = CooperativeRewardViewMixin()
        page.cooperative = True
        page.auto_reward_button = Mock()
        page.reward_note = Mock()
        reward = {'open_reward': 1, 'reward_mark': 1, 'reward_count': 1,
                  'win_stage': 1, 'npc_id': 20}
        data = {'reward': reward}
        bag = {'ready': True, 'reliable': True, 'capacity': 10,
               'items': {1: {}, 2: {}}, 'reserved': {}}
        page.render_cooperative_rewards(data, {}, True, False, bag)
        self.assertTrue(page._claim_ready)
        self.assertIn('免費寶箱待領', page.reward_note.set.call_args.args[0])
        busy_bag = dict(bag, items={i: {} for i in range(8)})
        page.render_cooperative_rewards(data, {}, True, False, busy_bag)
        self.assertFalse(page._claim_ready)
        self.assertIn('包包空位未確認', page.reward_note.set.call_args.args[0])

    def test_pending_and_uncertain_reward_never_claimable(self):
        page = CooperativeRewardViewMixin()
        page.cooperative = True
        page.auto_reward_button = Mock()
        page.reward_note = Mock()
        data = {'reward': {'open_reward': 1, 'reward_mark': 1}}
        bag = {'ready': True, 'reliable': True, 'capacity': 10,
               'items': {}, 'reserved': {}}
        page.render_cooperative_rewards(data, {'join_pending': {'id': 91}},
                                        True, False, bag)
        self.assertFalse(page._claim_ready)
        data['reward_uncertain'] = True
        page.render_cooperative_rewards(data, {}, True, False, bag)
        self.assertFalse(page._claim_ready)
        self.assertFalse(page._cancel_ready)
        self.assertIn('結果不明', page.reward_note.set.call_args.args[0])
        data['reward_uncertain'] = False
        data['reward']['open_reward'] = 2
        page.render_cooperative_rewards(data, {}, True, False, bag)
        self.assertFalse(page._claim_ready)
        self.assertIn('付費寶箱待處理', page.reward_note.set.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
