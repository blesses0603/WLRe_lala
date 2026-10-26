"""P1a cooperative chest: S23-5 integrity and server slot authority.

No packets are sent by these tests. A 1275 item missing from the historical
1262 stackability catalog still occupies its official server bag slot.
"""
import unittest

from wlre.core.state import State
from wlre.services.instance_rewards import _safe_bag, bag_claim_problem


def item(index, item_id=65001, count=3):
    return {'index': index, 'item_id': item_id, 'count': count,
            'serial': 9, 'serial_version': 1}


class CooperativeRewardInventoryIntegrity(unittest.TestCase):
    def test_unknown_1275_item_keeps_server_slot_and_count(self):
        state = State()
        state.apply({'type': 'bag_snapshot', 'capacity': 20,
                     'items': [item(7)]})
        self.assertTrue(state.inventory['ready'])
        self.assertTrue(state.inventory['reliable'])
        self.assertEqual(list(state.inventory['items']), ['7'])
        self.assertEqual(state.inventory['items']['7']['count'], 3)
        self.assertEqual(state.inventory['items']['7']['item_id'], 65001)
        self.assertTrue(_safe_bag(state))
        self.assertIsNone(bag_claim_problem(state.inventory))

    def test_free_chest_unlocks_after_real_bag_snapshot_without_old_item_catalog(self):
        from unittest.mock import Mock
        from wlre.features.cooperative.rewards import CooperativeRewardViewMixin
        state = State(phase='world_ready', initial_data_complete=True)
        state.player = {'role_id': 678, 'scene': 20000}
        state.apply({'type': 'instance_reward_status', 'mode': 'coop',
                     'reward_count': 3, 'win_stage': 0, 'open_reward': 1,
                     'reward_mark': 1, 'npc_id': 0})
        page = CooperativeRewardViewMixin()
        page.cooperative = True
        page.auto_reward_button = Mock()
        page.reward_note = Mock()
        page.render_cooperative_rewards(
            state.instances['coop'], state.instances['main'],
            True, False, state.inventory)
        self.assertFalse(page._claim_ready)
        self.assertIn('S23-5', page.reward_note.set.call_args.args[0])
        # An actual S23-5 snapshot with an unknown current-version item
        # must no longer be discarded by the 1262 stackability catalog.
        state.apply({'type': 'bag_snapshot', 'capacity': 20,
                     'items': [item(7)]})
        page.render_cooperative_rewards(
            state.instances['coop'], state.instances['main'],
            True, False, state.inventory)
        self.assertTrue(page._claim_ready)
        self.assertIn('免費寶箱待領', page.reward_note.set.call_args.args[0])

    def test_duplicate_or_out_of_range_server_slots_are_rejected(self):
        for entries in ([item(1), item(1, item_id=65002)],
                        [item(21)], [item(0)], [item(1, count=0)]):
            with self.subTest(entries=entries):
                state = State()
                state.apply({'type': 'bag_snapshot', 'capacity': 20,
                             'items': entries})
                self.assertFalse(state.inventory['reliable'])
                self.assertEqual(state.inventory['items'], {})
                self.assertFalse(_safe_bag(state))

    def test_unknown_new_item_delta_requires_explicit_free_slot(self):
        state = State()
        state.apply({'type': 'bag_snapshot', 'capacity': 20,
                     'items': [item(7)]})
        state.apply({'type': 'bag_add', 'item': item(9, 65002, 1)})
        self.assertTrue(state.inventory['reliable'])
        self.assertEqual(state.inventory['items']['9']['item_id'], 65002)
        # When stack semantics cannot be proved, a second or ambiguous
        # delta must not manufacture an inventory position.
        state.apply({'type': 'bag_add', 'item': item(0, 65003, 2)})
        self.assertFalse(state.inventory['reliable'])
        self.assertFalse(_safe_bag(state))

    def test_full_or_unsynced_bag_does_not_unlock_claim(self):
        state = State()
        self.assertIn('S23-5', bag_claim_problem(state.inventory))
        state.apply({'type': 'bag_snapshot', 'capacity': 5,
                     'items': [item(1), item(2)]})
        self.assertFalse(_safe_bag(state))
        self.assertIn('剩餘 3 格', bag_claim_problem(state.inventory))

    def test_snapshot_preserves_unconfirmed_inventory_reservations(self):
        state = State()
        state.apply({'type': 'bag_snapshot', 'capacity': 20,
                     'items': [item(7)]})
        state.inventory['reserved']['7'] = 1
        state.inventory['holds'] = {'alchemy': [{
            'index': '7', 'identity': [65001, 9, 1],
            'count': 1, 'remaining': 1, 'before': 3,
            'exclusive': True, 'uncertain': True}]}
        state.apply({'type': 'bag_snapshot', 'capacity': 20,
                     'items': [item(7)]})
        self.assertFalse(state.inventory['reliable'])
        self.assertFalse(_safe_bag(state))
        self.assertIn('未通過', bag_claim_problem(state.inventory))


if __name__ == '__main__':
    unittest.main()
