import unittest
from wlre.core.state import State
from wlre.ui.overview_ui import summarize


class Overview(unittest.TestCase):
    def setUp(self):
        self.state=State().snapshot()
        self.state['player']={'role_id':1,'name':'測試角色'}
        self.guard={'enabled':False,'members':[]}

    def test_missing_health_and_zero_health_are_distinct(self):
        self.state['knowledge']['player']['stats']={'hp':0,'max_hp':100}
        role=summarize(self.state,True,self.guard)['role']
        self.assertIn('HP 0/100',role)
        self.assertIn('SP 待同步/待同步',role)

    def test_disconnect_does_not_claim_active_battle(self):
        self.state['battle']['active']=True
        self.assertIn('戰鬥中',summarize(self.state,True,self.guard)['activity'])
        self.assertIn('已離線',summarize(self.state,False,self.guard)['activity'])
        self.assertNotIn('戰鬥中',summarize(self.state,False,self.guard)['activity'])

    def test_supply_uncertainty_is_visible(self):
        self.state['inventory']['field_supply']={'uncertain':True,'reason':'等待重新同步'}
        result=summarize(self.state,True,self.guard)
        self.assertIn('鎖定',result['activity'])
        self.assertIn('結果未確認',result['supply'])

    def test_nearby_player_does_not_satisfy_required_member(self):
        guard={'enabled':True,'members':[{'role_id':2,'name':'隊友'}]}
        self.state['party']['nearby']={'2':{'role_id':2,'name':'隊友'}}
        self.assertIn('缺少 隊友',summarize(self.state,True,guard)['party'])
        self.state['party']['teams']={'1':{'leader_id':1,'members':[1,2]}}
        self.assertIn('已到齊',summarize(self.state,True,guard)['party'])

    def test_battle_health_uses_current_player_only(self):
        self.state['knowledge']['player']['stats']={'hp':100,'max_hp':100}
        self.state['battle']['active']=True
        self.state['battle_units']={'1:1':{'pid':1,'hp':20,'max_hp':100},'2:1':{'pid':2,'hp':50}}
        self.assertIn('HP 20/100',summarize(self.state,True,self.guard)['role'])

    def test_empty_snapshot_waits_for_login(self):
        self.assertTrue(all('等待登入' in text for text in summarize({},False,self.guard).values()))
