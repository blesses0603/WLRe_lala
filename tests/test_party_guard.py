import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from wlre.services.battle import auto_battle;from wlre.services.battle import party_guard
from wlre.network.client import SessionLogic
from wlre.core.state import State
from wlre.services.battle.party import apply_party
from wlre.network.wire import ProtocolError

MEMBERS=[{'role_id':rid,'name':name} for rid,name in zip((111,222,333,444),'ABCD')]
def config(enabled=True):return {'enabled':enabled,'members':copy.deepcopy(MEMBERS)}
def battle(members=(111,222,333)):
    s=State();s.player={'role_id':111,'name':'A'}
    if members:s.party['teams']['111']={'leader_id':111,'members':list(members)}
    s.battle_count=1;s.battle={'active':True,'round':1,'war_style':0,'commands':{}}
    s.battle_units={
        '3:1':{'pid':111,'master_id':0,'name':'A','col':3,'row':1,'hp':100},
        '3:2':{'pid':9101,'master_id':111,'name':'夥伴','col':3,'row':2,'hp':100},
        '1:1':{'pid':5001,'master_id':0,'name':'怪物','col':1,'row':1,'hp':100}}
    logic=SessionLogic();logic.world_acknowledged=True
    settings=auto_battle.defaults();settings['party_guard']=config();logic.auto_battle.start(s,settings)
    return s,logic

def defend(s,a,p):return auto_battle.action_command(s,a,'defend'),'normal rules'

class RequiredMembers(unittest.TestCase):
    def test_four_people_wrong_id_nearby_and_guild_do_not_count(self):
        s,_=battle((111,222,333,555));s.party['nearby']['444']={'role_id':444,'name':'D'}
        s.guild={'members':{'444':{'role_id':444,'name':'D'}}}
        s.party['teams']['999']={'leader_id':999,'members':[999,444]}
        self.assertEqual(party_guard.missing(s.snapshot(),config()),[MEMBERS[3]])
    def test_renamed_role_still_matches(self):
        s,_=battle((111,222,333,444));s.player['name']='A改名'
        self.assertEqual(party_guard.escape_reason(s.snapshot(),config()),'')
    def test_lone_local_player_matches_self(self):
        s,_=battle(());cfg={'enabled':True,'members':[MEMBERS[0]]}
        self.assertEqual(party_guard.missing(s.snapshot(),cfg),[])
    def test_unknown_local_role_never_matches_other_team(self):
        self.assertEqual(party_guard.present_ids({'party':{'teams':{'111':{'members':[111,222]}}}}),set())
    def test_old_ai_json_defaults_disabled(self):
        settings=auto_battle.defaults();settings.pop('party_guard')
        self.assertEqual(auto_battle.validate(settings)['party_guard'],party_guard.defaults())
    def test_reject_invalid_settings(self):
        for cfg in ({'enabled':True,'members':[]},{'enabled':True,'members':[MEMBERS[0]]*2},
                    {'enabled':True,'members':[{'role_id':True}]},
                    {'enabled':True,'members':[{'role_id':0}]},
                    {'enabled':True,'members':[{'role_id':2**32}]},
                    {'enabled':True,'members':MEMBERS+[{'role_id':555}]},
                    {'enabled':1,'members':MEMBERS}):
            with self.subTest(cfg=cfg),self.assertRaises(ProtocolError):party_guard.validate(cfg)
    def test_save_load_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'中文路徑'/'party_guard.json'
            self.assertEqual(party_guard.load(path),party_guard.defaults())
            party_guard.save(config(),path);self.assertEqual(party_guard.load(path),config())
            self.assertEqual(list(path.parent.iterdir()),[path]);original=path.read_bytes()
            with self.assertRaises(ValueError):party_guard.save({'enabled':True,'members':[]},path)
            self.assertEqual(path.read_bytes(),original)
            path.write_text('{bad')
            with self.assertRaises(ValueError):party_guard.load(path)

class BattleEscape(unittest.TestCase):
    def test_missing_overrides_rules_for_player_and_partner(self):
        s,l=battle()
        with patch.object(auto_battle,'choose_action',side_effect=AssertionError('ordinary AI must not run')):
            self.assertEqual(len(l.auto_battle.tick(s,l,0)),2)
        self.assertTrue(all(d['command']['mode']=='escape' for d in s.auto_battle['decisions']))
        self.assertIn('D',s.auto_battle['decisions'][0]['reason']);self.assertEqual(l.auto_battle.tick(s,l,1),[])
    def test_escape_retry_next_round_only(self):
        s,l=battle();self.assertEqual(len(l.auto_battle.tick(s,l,0)),2)
        self.assertEqual(l.auto_battle.tick(s,l,1),[]);s.battle['round']=2
        self.assertEqual(len(l.auto_battle.tick(s,l,2)),2)
    def test_join_resumes_and_leave_restores_escape(self):
        s,l=battle();l.auto_battle.tick(s,l,0)
        apply_party(s,{'type':'team_join','leader_id':111,'role_id':444})
        self.assertEqual(l.auto_battle.tick(s,l,1),[]);s.battle['round']=2
        with patch.object(auto_battle,'choose_action',side_effect=defend) as choose:
            self.assertEqual(len(l.auto_battle.tick(s,l,2)),2);self.assertEqual(choose.call_count,2)
        apply_party(s,{'type':'team_leave','role_id':444});s.battle['round']=3
        self.assertEqual(len(l.auto_battle.tick(s,l,3)),2)
        self.assertTrue(all(d['command']['mode']=='escape' for d in s.auto_battle['decisions']))
    def test_disabled_uses_original_rules(self):
        s,l=battle();l.auto_battle.settings['party_guard']['enabled']=False
        with patch.object(auto_battle,'choose_action',side_effect=defend) as choose:
            self.assertEqual(len(l.auto_battle.tick(s,l,0)),2);self.assertEqual(choose.call_count,2)
    def test_stopped_ai_sends_nothing(self):
        s,l=battle();l.auto_battle.stop(s);self.assertEqual(l.auto_battle.tick(s,l,0),[])
    def test_field_sends_no_escape(self):
        s,l=battle();s.battle['active']=False;self.assertEqual(l.auto_battle.tick(s,l,0),[])
    def test_live_edit_preserves_sent_commands(self):
        s,l=battle();l.auto_battle.tick(s,l,0);key,units=l.round_key,set(l.sent_units)
        l.command({'type':'set_party_guard','settings':config(False)},s)
        self.assertEqual((l.round_key,l.sent_units),(key,units));self.assertEqual(l.auto_battle.tick(s,l,1),[])
    def test_special_battle_still_pauses(self):
        s,l=battle();s.battle['war_style']=16;self.assertEqual(l.auto_battle.tick(s,l,0),[])
        self.assertEqual(s.auto_battle['status'],'paused')
    def test_new_session_has_no_stale_team(self):
        s,l=battle((111,222,333,444));fresh=State();fresh.player=copy.deepcopy(s.player)
        self.assertEqual([m['role_id'] for m in party_guard.missing(fresh.snapshot(),config())],[222,333,444])
    def test_manual_order_is_not_overwritten(self):
        s,l=battle();l.round_key=(1,1);l.sent_units={(3,1)}
        self.assertEqual(len(l.auto_battle.tick(s,l,0)),1)
        self.assertEqual(s.auto_battle['decisions'][0]['slot'],'3:2')

if __name__=='__main__':unittest.main(verbosity=2)
