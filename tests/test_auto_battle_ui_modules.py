"""AutoPlay UI restructuring must retain the original public entry points."""
import unittest

from wlre.services.battle.auto_battle import defaults
from wlre.ui import auto_battle_ui as old_api
from wlre.ui.auto_battle import model, action_editor, rule_card


class AutoBattleUiModulesTest(unittest.TestCase):
    def test_original_editor_exports_keep_class_identity(self):
        self.assertIs(old_api.ActionEditor, action_editor.ActionEditor)
        self.assertIs(old_api.RuleCard, rule_card.RuleCard)
        self.assertIs(old_api.RuleDraft, model.RuleDraft)
        self.assertIs(old_api.action_entries, model.action_entries)
        self.assertIs(old_api.confirmed_skill_entries, model.confirmed_skill_entries)
        self.assertTrue(callable(old_api.open_settings))

    def test_all_rule_cards_remain_defined_and_validated(self):
        self.assertEqual(len(old_api.GROUPS), 7)
        self.assertEqual({group[1] for group in old_api.GROUPS},
                         {'deadAction','enemyHpAction','lowHpAction','lowSpAction',
                          'roundAction','repeatAction','orderAction'})
        draft = old_api.RuleDraft(defaults())
        self.assertEqual(len(list(draft.rows('player'))), 14)
        self.assertEqual(len(list(draft.rows('partner'))), 14)

    def test_action_editor_still_provides_save_and_cleanup(self):
        for name in ('populate','poll','cleanup','save','pick','change_kind'):
            self.assertTrue(callable(getattr(old_api.ActionEditor, name)))
        for name in ('collect','render','step'):
            self.assertTrue(callable(getattr(old_api.RuleCard, name)))


if __name__ == '__main__':
    unittest.main()
