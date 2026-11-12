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

    def test_hp_sp_skill_thresholds_and_actor_profiles_remain_independent(self):
        from wlre.services.items.live_combat_catalog import _pinned
        token=_pinned.set({'skills':{},'items':{}})
        try:
            draft=model.RuleDraft(defaults())
            for who,offset in (('player',0),('partner',1000)):
                for key,sid,value in (('lowHpAction',1001,123),('lowSpAction',1002,45)):
                    row=dict(draft.value['profiles'][who][key],id=sid+offset,kind=1,value=value+offset)
                    draft.set_action(who,key,0,row)
            import json
            restored=model.RuleDraft(json.loads(json.dumps(draft.value)))
            self.assertEqual(restored.value,draft.value)
            restored.value['profiles']['player']['lowHpAction']['value']=999
            self.assertEqual(restored.value['profiles']['player']['lowSpAction']['value'],45)
            self.assertEqual(restored.value['profiles']['partner']['lowHpAction']['id'],2001)
        finally:_pinned.reset(token)

    def test_target_labels_follow_action_and_rule(self):
        self.assertEqual(model.target_options({'id':-3,'kind':2},'lowSpAction'),({1:'最低SP',2:'座標順序',3:'最高SP'},True))
        self.assertEqual(model.target_options({'id':-2,'kind':2},'lowHpAction')[0][1],'最低HP')
        for sid in (0,60021,60041):self.assertFalse(model.target_options({'id':sid,'kind':1},'lowSpAction')[1])
        self.assertEqual(model.target_options({'id':10001,'kind':1},'lowSpAction')[0][3],'最高HP')
        self.assertIn('友方最低SP',model.target_options({'id':1001,'kind':1},'lowSpAction')[0][1])

    def test_action_editor_still_provides_save_and_cleanup(self):
        for name in ('populate','poll','cleanup','save','pick','change_kind'):
            self.assertTrue(callable(getattr(old_api.ActionEditor, name)))
        for name in ('collect','render','step'):
            self.assertTrue(callable(getattr(old_api.RuleCard, name)))


class AutoBattleNativeTargetTest(unittest.TestCase):
    def test_editor_preserves_disabled_policy_and_switches_to_sp_labels(self):
        import tkinter as tk
        try:root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        root.withdraw();saved=[]
        try:
            editor=action_editor.ActionEditor(root,{'id':60021,'kind':1,'target':3}, {}, 'player', saved.append,rule_key='lowSpAction')
            root.update()
            self.assertEqual(str(editor.target_combo.cget('state')),'disabled')
            editor.save()
            self.assertEqual(saved[0]['target'],3)
            editor=action_editor.ActionEditor(root,{'id':-3,'kind':2,'target':3}, {}, 'player', saved.append,rule_key='lowSpAction')
            root.update()
            self.assertEqual(tuple(editor.target_combo.cget('values')),('最低SP','座標順序','最高SP'))
            self.assertEqual(editor.target_combo.current(),2)
            editor.target_combo.current(0);editor.save()
            self.assertEqual(saved[-1]['target'],1)
        finally:root.destroy()


if __name__ == '__main__':
    unittest.main()
