"""The assistant only configures existing services; it owns no success ledger."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.wire import ProtocolError
from wlre.services import daily_assistant as assistant, time_cube, star_ark
from wlre.services.social import guild_actions


class DailyAssistantTests(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.logic = SessionLogic()

    def configure(self, **settings):
        return self.logic.command(dict(type='daily_assistant', action='configure', **settings), self.state)

    def stop(self, **settings):
        return self.logic.command(dict(type='daily_assistant', action='stop', **settings), self.state)

    def test_defaults_and_view_are_read_only(self):
        before = self.state.snapshot()
        result = assistant.view(before)
        self.assertEqual(before, self.state.snapshot())
        self.assertEqual(result['budgets']['gold'], dict(limit=450, reserved=0, confirmed=0))
        self.assertEqual(result['budgets']['star'], dict(limit=120, reserved=0, confirmed=0))
        self.assertTrue(result['settings']['cube_enabled'])
        self.assertEqual(result['rows'], [])
        result['services']['star_ark']['status'] = 'fake'
        self.assertEqual(before, self.state.snapshot())
        self.assertEqual(assistant.view({})['budgets']['gold']['confirmed'], None)

    def test_partial_and_repeated_config_preserve_ledgers_and_other_services(self):
        self.state.star_ark.update(reserved=100, confirmed=90, uncertain=True)
        untouched = deepcopy(self.state.guild_actions)
        for _ in range(3):
            self.assertEqual(self.configure(cube_enabled=False, ark_dispatch_enabled=False,
                                           ark_fights_enabled=True, ark_questions_enabled=False,
                                           star_budget=60), [])
            self.assertFalse(self.state.time_cube['enabled'])
            self.assertEqual(self.state.star_ark['reserved'], 100)
            self.assertEqual(self.state.star_ark['confirmed'], 90)
            self.assertTrue(self.state.star_ark['uncertain'])
            self.assertEqual(self.state.guild_actions, untouched)
        self.assertEqual(self.configure(ark_fights_enabled=False), [])
        self.assertFalse(self.state.star_ark['enabled'])

    def test_invalid_settings_roll_back_every_service(self):
        for invalid in ({'star_budget': -1}, {'star_budget': True}, {'ark_hours': 7},
                        {'ark_fights_enabled': 1}, {'guild_target': 0}, {'guild_sell_id': 11},
                        {'gold_budget': 2**32}, {'rewards_enabled': 'yes'}, {'unknown': True}):
            before = self.state.snapshot()
            with self.assertRaises(ProtocolError):
                self.configure(cube_enabled=False, **invalid)
            self.assertEqual(self.state.snapshot(), before)

    def test_catalog_validation_rolls_back_earlier_controls(self):
        before = self.state.snapshot()
        with patch.object(guild_actions, 'runtime_catalog', return_value=(None, None, 'missing')):
            with self.assertRaisesRegex(ProtocolError, 'missing'):
                self.configure(cube_enabled=False, rewards_enabled=False, guild_donate_enabled=True)
        self.assertEqual(self.state.snapshot(), before)

    def test_pending_config_rejected_atomically_but_stop_preserves_evidence(self):
        for name in ('guild_actions', 'star_ark'):
            data = getattr(self.state, name)
            data.update(pending={'kind': 'test'}, reserved=200, confirmed=100, uncertain=True)
        before = self.state.snapshot()
        with self.assertRaises(ProtocolError):
            self.configure(cube_enabled=False, star_budget=50)
        self.assertEqual(self.state.snapshot(), before)
        self.assertEqual(self.stop(), [])
        for name in ('guild_actions', 'star_ark'):
            data = getattr(self.state, name)
            for key in ('pending', 'reserved', 'confirmed', 'uncertain'):
                self.assertEqual(data[key], before[name][key])
        self.assertFalse(self.state.time_cube['enabled'])
        self.assertFalse(self.state.daily_tasks['enabled'])
        self.assertFalse(self.state.guild_actions['sign_enabled'])
        self.assertFalse(self.state.guild_actions['donate_enabled'])
        self.assertFalse(self.state.star_ark['enabled'])

    def test_stop_subset_and_bad_stop_are_atomic(self):
        self.stop(services=['time_cube'])
        self.assertFalse(self.state.time_cube['enabled'])
        self.assertTrue(self.state.daily_tasks['enabled'])
        for services in ([], 'time_cube', ['time_cube', 'invalid'], ['time_cube', 'time_cube']):
            before = self.state.snapshot()
            with self.assertRaises(ProtocolError):
                self.stop(services=services)
            self.assertEqual(self.state.snapshot(), before)

    def test_stopped_cube_still_confirms_pending_without_new_packets(self):
        self.state.time_cube['pending'] = dict(count_updated=True, bag_revision=0, due=100)
        self.state.inventory.update(reliable=True, revision=1)
        self.stop()
        self.assertEqual(time_cube.tick(self.state, True, 1), [])
        self.assertIsNone(self.state.time_cube['pending'])
        self.assertFalse(self.state.time_cube['enabled'])
        self.assertFalse(self.state.time_cube['uncertain'])
        self.assertEqual(time_cube.tick(self.state, True, 2), [])

    def test_stop_does_not_interrupt_guild_payment_confirmation(self):
        self.state.player['role_id'] = 1
        self.state.guild.update(ready=True, serial=7, members={'1': {'role_id': 1}})
        data = self.state.guild_actions
        data.update(role=1, guild=7, reserved=150, remaining=4,
                    pending=dict(kind='donate', role=1, guild=7, epoch=0, token='v',
                                 gold_ack=True, remaining_ack=True, sell_ack=True,
                                 before_remaining=5, quote={'price': 150}, due=100))
        self.state.gold['reliable'] = True
        self.stop()
        with patch.object(guild_actions, 'runtime_catalog', return_value=(None, 'v', 'waiting')):
            self.assertEqual(guild_actions.tick(self.state, True, 1), [])
        self.assertIsNone(data['pending'])
        self.assertEqual(data['confirmed'], 150)
        self.assertEqual(data['reserved'], 150)
        self.assertFalse(data['donate_enabled'])

    def test_stop_does_not_interrupt_ark_payment_confirmation(self):
        self.state.player['role_id'] = 1
        data = self.state.star_ark
        data.update(reserved=120, pending=dict(kind='dispatch', role=1, token='v',
                    daily_generation=0, paid=True, ship_ack=True, task_before=0,
                    quote={'price': 120}, due=100))
        self.stop()
        with patch.object(star_ark, 'runtime_catalog', return_value=(None, 'v', 'waiting')):
            self.assertEqual(star_ark.tick(self.state, True, 1), [])
        self.assertIsNone(data['pending'])
        self.assertEqual(data['confirmed'], 120)
        self.assertEqual(data['reserved'], 120)
        self.assertFalse(data['enabled'])

    def test_projection_uses_real_daily_rows_unknown_is_manual(self):
        self.state.phase = 'world_ready'
        self.state.daily_tasks.update(ready=True, groups_ready=True, catalog_ready=True, rows=[
            dict(cycle=1, index=1, condition_kind=16, condition_params=[], progress=0, goal=3),
            dict(cycle=1, index=2, condition_kind=999, condition_params=[], progress=0, goal=1),
            dict(cycle=2, index=3, condition_kind=16, progress=0, goal=3)])
        before = self.state.snapshot()
        result = assistant.view(before)
        self.assertEqual([row['index'] for row in result['rows']], [1, 2])
        self.assertEqual([row['classification'] for row in result['rows']], ['blocked', 'manual'])
        self.assertEqual(before, self.state.snapshot())
        self.state.time_cube['uncertain'] = True
        self.assertEqual(assistant.view(self.state.snapshot())['rows'][0]['classification'], 'blocked')
        self.assertEqual(self.state.daily_tasks['rows'][0]['progress'], 0)

    def test_budget_only_does_not_resume_paused_ark(self):
        self.stop()
        self.configure(star_budget=240, ark_hours=2)
        self.assertFalse(self.state.star_ark['enabled'])
        settings = assistant.view(self.state.snapshot())['settings']
        for key in ('ark_dispatch_enabled', 'ark_fights_enabled', 'ark_questions_enabled'):
            self.assertFalse(settings[key])
        self.configure(ark_questions_enabled=True)
        self.assertTrue(self.state.star_ark['enabled'])
        self.assertTrue(self.state.star_ark['questions_enabled'])
        self.assertFalse(self.state.star_ark['dispatch_enabled'])
        self.assertFalse(self.state.star_ark['fights_enabled'])

    def test_projection_budget_and_unknown_question_blockers(self):
        self.state.phase = 'world_ready'
        self.state.initial_data_complete = True
        self.state.player['role_id'] = 1
        self.state.star_ark.update(ready=True, role=1, catalog_token='v',
                                  quote={'price': 120}, reserved=120, budget=120)
        self.state.daily_tasks.update(ready=True, groups_ready=True, catalog_ready=True, rows=[
            dict(cycle=1, index=1, condition_kind=9, condition_params=[2], progress=0, goal=1)])
        row = assistant.view(self.state.snapshot())['rows'][0]
        self.assertEqual(row['classification'], 'blocked')
        self.assertIn('星力消耗上限', row['reason'])
        self.state.daily_tasks['rows'][0]['condition_params'] = [1]
        self.state.star_ark.update(pending={'kind': 'question'},
                                  question={'selected': None, 'known_answer': None})
        row = assistant.view(self.state.snapshot())['rows'][0]
        self.assertEqual(row['classification'], 'manual')
        self.assertIn('選擇答案', row['reason'])
        self.state.star_ark['question']['selected'] = 1
        self.assertEqual(assistant.view(self.state.snapshot())['rows'][0]['classification'], 'progress')

    def test_role_and_server_day_resets_follow_service_ledgers_only(self):
        data = self.state.guild_actions
        data.update(reserved=450, confirmed=450)
        self.configure(guild_donate_enabled=False, gold_budget=500)
        self.assertEqual(assistant.view(self.state.snapshot())['budgets']['gold']['confirmed'], 450)
        guild_actions.apply_actions(self.state, dict(type='ui_sell_day_reset'))
        self.assertEqual(assistant.view(self.state.snapshot())['budgets']['gold'],
                         dict(limit=500, reserved=0, confirmed=0))
        self.state.star_ark.update(reserved=120, confirmed=120)
        guild_actions.apply_actions(self.state, dict(type='role_list_available'))
        star_ark.apply_ark(self.state, dict(type='role_list_available'))
        result = assistant.view(self.state.snapshot())
        self.assertEqual(result['budgets']['gold'], dict(limit=450, reserved=0, confirmed=0))
        self.assertEqual(result['budgets']['star'], dict(limit=120, reserved=0, confirmed=0))


if __name__ == '__main__':
    unittest.main()
