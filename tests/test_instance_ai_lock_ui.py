"""Instance UI must not treat an armed but idle AI as a conflicting activity."""
import unittest
from unittest.mock import Mock

from wlre.core.state import State
from wlre.ui.instance_ui import creation_block_reasons, InstancePanel


class InstanceAiIntentUI(unittest.TestCase):
    def test_create_guard_allows_armed_ai_only_outside_actual_battle(self):
        state = State(phase='world_ready', initial_data_complete=True)
        state.player = {'role_id': 99}
        state.auto_battle['enabled'] = True
        snapshot = state.snapshot()
        self.assertEqual(creation_block_reasons(snapshot, 'main', True), ())
        self.assertEqual(creation_block_reasons(snapshot, 'coop', True), ())
        snapshot['battle']['active'] = True
        self.assertIn('正在戰鬥中', creation_block_reasons(snapshot, 'main', True))

    def test_main_and_coop_buttons_not_disabled_only_due_to_armed_ai(self):
        state = State(phase='world_ready', initial_data_complete=True)
        state.player = {'role_id': 99}
        state.auto_battle['enabled'] = True
        panel = InstancePanel.__new__(InstancePanel)
        panel.main_page = Mock()
        panel.coop_page = Mock()
        panel.render(state.snapshot(), live=True)
        for page in (panel.main_page, panel.coop_page):
            self.assertFalse(page.render.call_args.kwargs['activity_blocked'])
            self.assertTrue(all('自動戰鬥' not in value
                                for value in page.render.call_args.kwargs['creation_reasons']))
        state.battle['active'] = True
        panel.render(state.snapshot(), live=True)
        self.assertTrue(panel.main_page.render.call_args.kwargs['activity_blocked'])
        self.assertTrue(panel.coop_page.render.call_args.kwargs['activity_blocked'])


if __name__ == '__main__':
    unittest.main()
