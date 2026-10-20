"""Co-op auto battle diagnostics expose no actor identity or raw commands."""
import tempfile
import unittest

from wlre.core.diagnostics import Diagnostics
from wlre.core.state import State
from wlre.network.service_scheduler import auto_battle_status_event


class AutoBattleHealthTests(unittest.TestCase):
    def test_status_event_has_only_counts_and_current_round(self):
        state = State()
        state.player = {'role_id': 71, 'name': 'private-role-name'}
        state.battle = {'active': True, 'war_style': 16, 'round': 3}
        state.battle_units['3:1'] = {'col': 3, 'row': 1, 'pid': 71, 'hp': 90,
                                      'name': 'private-role-name'}
        state.battle_units['3:2'] = {'col': 3, 'row': 2, 'pid': 123, 'master_id': 71,
                                      'hp': 40, 'name': 'private-pet-name'}
        state.battle_units['1:1'] = {'col': 1, 'row': 1, 'pid': 33, 'hp': 100}
        state.auto_battle = {'status': 'waiting', 'enabled': True,
                             'reason': 'do not log private-role-name',
                             'decisions': [{'unit': 'private-pet-name'}]}
        event = auto_battle_status_event(state)
        self.assertEqual((event['battle_war_style'], event['battle_round'],
                          event['battle_active'], event['owned_living']),
                         (16, 3, True, 2))

        with tempfile.TemporaryDirectory() as directory:
            diagnostics = Diagnostics(directory)
            self.assertTrue(diagnostics.auto_battle_status(event))
            self.assertFalse(diagnostics.auto_battle_status(event))
            diagnostics.close()
            saved = diagnostics.path.read_text(encoding='utf-8')
        self.assertIn('auto_battle state=waiting enabled=1 battle_active=1', saved)
        self.assertIn('war_style=16 round=3 owned_living=2', saved)
        self.assertNotIn('private-role-name', saved)
        self.assertNotIn('private-pet-name', saved)
        self.assertNotIn('do not log', saved)

    def test_bad_or_untrusted_status_diagnostics_are_rejected(self):
        valid = {
            'type': 'auto_battle_status', 'status': 'paused', 'enabled': True,
            'battle_active': True, 'battle_war_style': 21,
            'battle_round': 1, 'owned_living': 1}
        with tempfile.TemporaryDirectory() as directory:
            diagnostics = Diagnostics(directory)
            for mutated in (
                {'status': 'password=secret'}, {'battle_round': 'password=secret'},
                {'battle_war_style': True}, {'battle_war_style': 256},
                {'owned_living': -1}, {'enabled': 1},
                {'battle_active': 'private'}, {'type': 'something_else'}
            ):
                with self.subTest(mutated=mutated):
                    self.assertFalse(diagnostics.auto_battle_status({**valid, **mutated}))
            self.assertTrue(diagnostics.auto_battle_status(valid))
            diagnostics.close()
            saved = diagnostics.path.read_text(encoding='utf-8')
        self.assertNotIn('secret', saved)
        self.assertNotIn('private', saved)
        self.assertEqual(saved.count('auto_battle state=paused'), 1)


if __name__ == '__main__':
    unittest.main()
