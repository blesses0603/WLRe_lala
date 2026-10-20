"""Post-fight continuity diagnostics and AI intent gate regressions."""
import tempfile
import unittest
from pathlib import Path

from wlre.core.diagnostics import Diagnostics
from wlre.core.state import State
from wlre.network.client import post_battle_trace
from wlre.services.coordination import command_reason, reason


class PostBattleDiagnostics(unittest.TestCase):
    def test_redacted_continuation_stages_are_recorded_once(self):
        state = State(phase='world_ready', initial_data_complete=True)
        state.player = {'role_id': 123, 'name': 'confidential character'}
        state.battle_count = 3
        state.battle = {
            'active': False, 'war_style': 16,
            'post_event': {'status': 'cooperative_wait', 'delay_seconds': 2.5,
                           'reason': 'private token must not be logged'}}
        state.instances['coop']['fight_count'] = None
        scheduled = post_battle_trace(state, 'scheduled')
        self.assertEqual(scheduled['fight_count_known'], False)
        self.assertEqual(scheduled['battle_count'], 3)
        with tempfile.TemporaryDirectory() as temp:
            diagnostics = Diagnostics(temp)
            self.assertTrue(diagnostics.post_battle_trace(scheduled))
            self.assertFalse(diagnostics.post_battle_trace(scheduled))
            self.assertTrue(diagnostics.post_battle_trace(post_battle_trace(state, 'sent')))
            self.assertFalse(diagnostics.post_battle_trace({**scheduled, 'phase': 'secret'}))
            self.assertFalse(diagnostics.post_battle_trace({**scheduled, 'battle_count': 'secret'}))
            self.assertFalse(diagnostics.post_battle_trace({**scheduled, 'delay_seconds': 'secret'}))
            self.assertTrue(diagnostics.post_battle_trace(post_battle_trace(state, 'completed')))
            diagnostics.close()
            value = Path(diagnostics.path).read_text(encoding='utf-8')
        self.assertEqual(value.count('post_battle phase='), 3)
        self.assertIn('post_battle phase=sent battle_count=3 war_style=16 delay_s=2.5 fight_count_known=0', value)
        self.assertNotIn('confidential character', value)
        self.assertNotIn('private token', value)
        self.assertNotIn('secret', value)


class AiIntentGatePolicy(unittest.TestCase):
    def test_armed_ai_does_not_block_other_features_outside_combat(self):
        state = State(phase='world_ready', initial_data_complete=True)
        state.player = {'role_id': 111}
        state.auto_battle['enabled'] = True
        self.assertEqual(command_reason(state, {'type': 'allocate_points'}), '')
        self.assertEqual(command_reason(state, {'type': 'start_auto_battle'}), '')
        self.assertEqual(reason(state, 'crafting'), '')
        self.assertTrue(state.auto_battle['enabled'])

    def test_real_battle_blocks_conflicting_actions_and_keeps_intent(self):
        state = State(phase='world_ready', initial_data_complete=True)
        state.player = {'role_id': 111}
        state.auto_battle['enabled'] = True
        state.battle['active'] = True
        self.assertIn('戰鬥', command_reason(state, {'type': 'allocate_points'}))
        self.assertIn('戰鬥', reason(state, 'crafting'))
        self.assertTrue(state.auto_battle['enabled'])


if __name__ == '__main__':
    unittest.main()
