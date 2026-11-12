"""Owned synthetic observations only; never execute client Lua or cast a skill."""
import unittest
from wlre.services.items.skill_effects import recovery_kind,recovery_description


class SkillEffectsTest(unittest.TestCase):
    def test_reviewed_categories_and_unknown_byte_values(self):
        expected={6:'sp',7:'hp',14:'hp_sp'}
        for value in range(256):
            with self.subTest(value=value):self.assertEqual(recovery_kind({'FightWay':value}),expected.get(value,'unknown'))

    def test_missing_malformed_and_unreviewed_values_stay_unknown(self):
        for value in (None,True,False,6.0,'6',-1,256,10**100):
            self.assertEqual(recovery_kind({'FightWay':value}),'unknown')
        for row in ({},None,[],False,6):self.assertEqual(recovery_kind(row),'unknown')

    def test_picker_uses_current_catalog_but_only_observed_skills(self):
        from unittest.mock import patch
        from wlre.ui.auto_battle import model
        from wlre.services.items.live_combat_catalog import _pinned
        state={'player':{'role_id':7},'battle':{'active':True},'battle_units':{'1:1':{'pid':7,'col':1,'row':1,'name':'合成角色'}}}
        observed=[{'id':1001,'level':1,'source':'已學'}]
        with patch.object(model,'skill_rows',return_value=observed):
            token=_pinned.set({'skills':{'1001':{'name':'合成技能','FightWay':6},'1002':{'name':'未學技能','FightWay':14}},'items':{}})
            try:
                entries=dict(model.confirmed_skill_entries(state,'player'))
                self.assertIn('恢復 SP（恢復量未知）',entries[1001])
                self.assertNotIn(1002,entries)
            finally:_pinned.reset(token)
            token=_pinned.set({'skills':{},'items':{}})
            try:self.assertIn('恢復效果未驗證',dict(model.confirmed_skill_entries(state,'player'))[1001])
            finally:_pinned.reset(token)

    def test_cost_target_status_and_variables_are_not_recovery(self):
        row={'FightWay':1,'ReduceSP':100,'TargetKind':1,'HitStatus':241,'VariableA':999,'VariableB':999,'VariableC':100,'VariableD':999}
        self.assertEqual(recovery_kind(row),'unknown')
        self.assertEqual(recovery_description(row),'恢復效果未驗證')
        for way,text in ((6,'恢復 SP'),(7,'恢復 HP'),(14,'恢復 HP／SP')):
            row['FightWay']=way
            self.assertEqual(recovery_description(row),text+'（恢復量未知）')
            self.assertEqual(row['ReduceSP'],100)


if __name__=='__main__':unittest.main()
