"""v0.5.3 official room headcount feedback; no fabricated start eligibility."""
import unittest

from wlre.ui.instance_ui import room_headcount_status


class RoomHeadcount(unittest.TestCase):
    def test_normal_dungeon_with_six_minimum(self):
        # Map 30019: official 1262 StageData requires 6-12 members.
        members = [{'role_id': i} for i in range(1, 7)]
        data = {'room': {'room_id': 30019, 'host_id': 1, 'members': 2},
                'members': members[:2], 'phase': 'waiting'}
        text = room_headcount_status('main', data, 1)
        self.assertIn('2/6 人', text)
        self.assertIn('尚缺 4 人', text)
        self.assertIn('上限 12 人', text)
        self.assertNotIn('可以開始', text)

        data['members'] = members
        data['room']['members'] = 6
        text = room_headcount_status('main', data, 1, can_begin=True)
        self.assertIn('6/6 人，已達最低人數', text)
        self.assertIn('房主可以開始挑戰', text)
        text = room_headcount_status('main', data, 1, can_begin=False)
        self.assertIn('已達最低人數', text)
        self.assertIn('等待房主', text)
        self.assertNotIn('可以開始', text)

    def test_coop_waits_for_full_configured_capacity(self):
        members = [{'role_id': i} for i in (678, 889, 1000, 1001)]
        data = {'room': {'room_id': 91, 'capacity': 4,
                         'host_id': 678, 'standby': False},
                'members': members[:2]}
        self.assertIn('2/4 人，尚缺 2 人',
                      room_headcount_status('coop', data, 678))
        data['members'] = members
        self.assertIn('4/4 人，已滿員；房主可以準備',
                      room_headcount_status('coop', data, 678, can_begin=True))
        self.assertIn('等待房主或其他開始條件確認',
                      room_headcount_status('coop', data, 889))
        data['room']['standby'] = True
        self.assertIn('房間已進入準備狀態',
                      room_headcount_status('coop', data, 678, can_begin=True))

    def test_unknown_roster_never_claims_ready(self):
        normal = {'room': {'room_id': 30019, 'members': 6},
                  'members': [{'role_id': 1}, {'role_id': 2}]}
        self.assertIn('尚未完整同步',
                      room_headcount_status('main', normal, 1, can_begin=True))
        coop = {'room': {'room_id': 91, 'capacity': 2,
                         'host_id': 678, 'standby': False},
                'members': [{'role_id': 889}, {'role_id': 678}]}
        self.assertIn('尚未完整同步',
                      room_headcount_status('coop', coop, 678, can_begin=True))
        self.assertNotIn('可以準備', room_headcount_status('coop', coop, 678, can_begin=True))

    def test_unknown_room_and_capacity(self):
        self.assertIn('尚未加入房間', room_headcount_status('main', {}, 1))
        self.assertIn('尚未加入房間', room_headcount_status('coop', {}, 1))
        self.assertIn('容量尚未同步',
                      room_headcount_status('coop', {'room': {'room_id': 9}}, 1))
        self.assertIn('尚未確認此房間所屬',
                      room_headcount_status('main',
                                            {'room': {'room_id': 99999}}, 1))


if __name__ == '__main__':
    unittest.main()
