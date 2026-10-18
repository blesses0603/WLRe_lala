"""Completed-battle EXP efficiency regressions using authoritative S8 totals.

No skill EXP, guessed gains, unconfirmed battle end, or unrelated companion
activity is allowed to pollute an observed player/companion rate series.
"""
import unittest

from wlre.core.state import State
from wlre.core.efficiency import observe, rates, progress, cumulative, need


class EfficiencyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.state=State()
        self.state.player={'role_id':71,'name':'Fixture'}
        self.state.knowledge['player']['stats']={
            'exp':20000,'level':15,'degree':0,
        }
        self.state.knowledge['companions']={
            '2':{'npc_id':8002,'ready':True,
                 'stats':{'exp':10000,'level':12,'degree':0,'name':'Pet Two'}},
            '3':{'npc_id':8003,'ready':True,
                 'stats':{'exp':22000,'level':16,'degree':0,'name':'Idle Pet'}},
        }

    def event(self,kind,when,**payload):
        observe(self.state,{'type':kind,'_observed_at':when,**payload})

    def start(self,time,pet_slot=2):
        units=[{'pid':71,'master_id':0,'npc_index':0}]
        if pet_slot is not None:
            units.append({'pid':8000+pet_slot,'master_id':71,'npc_index':pet_slot})
        self.event('battle_start',time,units=units)

    def pet_exp(self,slot,total,when):
        self.state.knowledge['companions'][str(slot)]['stats']['exp']=total
        self.event('attribute_set',when,entity=f'follow:{slot}',
                   human_kind=4,kind=36,parameter=0,value=total)

    def test_idle_companion_retains_rates_during_other_battles(self):
        self.start(0)
        self.pet_exp(2,10000,5)
        self.event('event_end',10)
        self.start(20)
        self.pet_exp(2,10120,25)
        self.event('event_end',30)
        before=rates(self.state.efficiency['rows']['follow:2'])
        self.assertEqual(before[0][1],1)
        self.assertAlmostEqual(before[0][0],360.0)
        self.start(40,pet_slot=None)
        self.event('event_end',50)
        pet=self.state.efficiency['rows']['follow:2']
        self.assertEqual(rates(pet),before)
        self.assertEqual(pet['earned'],120)
        self.assertEqual(pet['last_total'],10120)
        self.assertEqual(pet['history'],[(0,10),(120,30)])

    def test_missing_exp_from_participant_is_not_fabricated_or_erased(self):
        self.start(0)
        self.pet_exp(2,10000,5)
        self.event('event_end',10)
        self.start(20)
        self.pet_exp(2,10090,25)
        self.event('event_end',30)
        old=rates(self.state.efficiency['rows']['follow:2'])
        self.start(40)
        self.event('event_end',50)
        row=self.state.efficiency['rows']['follow:2']
        self.assertEqual(row['earned'],90)
        self.assertEqual(row['count'],1)
        self.assertIsNone(row['last_total'])
        self.assertIsNone(row['last_gain'])
        self.assertEqual(rates(row),old)
        self.start(60)
        self.pet_exp(2,10200,65)
        self.event('event_end',70)
        row=self.state.efficiency['rows']['follow:2']
        self.assertEqual(row['earned'],90)  # Missing S8 cannot prove a gain.
        self.assertEqual(row['count'],1)
        self.assertIsNone(row['last_gain'])

    def test_non_battle_exp_rebases_without_fake_battle_gain(self):
        self.start(0)
        self.pet_exp(2,10000,5)
        self.event('event_end',10)
        self.pet_exp(2,10500,20)  # Quest/reward, outside a battle.
        self.start(30)
        self.pet_exp(2,10540,35)
        self.event('event_end',40)
        row=self.state.efficiency['rows']['follow:2']
        self.assertEqual(row['earned'],40)
        self.assertEqual(row['last_gain'],40)

    def test_skill_exp_does_not_count_as_character_exp(self):
        self.start(0)
        self.event('attribute_set',5,entity='self',kind=36,parameter=111,value=900000)
        self.event('event_end',10)
        self.assertEqual(self.state.efficiency['rows']['self']['count'],0)
        self.assertEqual(self.state.efficiency['rows']['self']['earned'],0)

    def test_authoritative_level_clears_inference_marker(self):
        # Keep the EXP total consistent with the newly confirmed level.
        self.state.knowledge['companions']['2']['stats']['exp']=cumulative(12,0)+50
        self.event('login_result',1,result=0)
        row=self.state.efficiency['rows']['follow:2']
        row['level_inferred']=True
        row['degree_inferred']=True
        self.event('initial_data_complete',2)
        row=self.state.efficiency['rows']['follow:2']
        self.assertFalse(row.get('level_inferred',False))
        self.assertFalse(row.get('degree_inferred',False))
        self.assertEqual(row['level'],12)
        self.assertEqual(row['degree'],0)

    def test_real_level_threshold_has_valid_next_level(self):
        level=15
        total=cumulative(level,0)+need(level+1,0)
        remaining,pct,_=progress(total,level+1,0)
        self.assertEqual(remaining,need(level+2,0))
        self.assertEqual(pct,0.0)


if __name__ == '__main__':
    unittest.main()
