"""Ark protocol, bounded currency consumption and real scheduler regressions."""
import struct
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch,Mock
from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.wire import Packet,Writer,ProtocolError
from wlre.network.client import SessionLogic
from wlre.services import star_ark as ark
from wlre.services.world import ark_catalog as schema


def raw_catalogs(tail=True):
    star=struct.pack('<iB6H',1,1,120,240,345,445,530,600)
    agent=struct.pack('<iB6IH',1,1,*([10]*6),8246)
    agent+=struct.pack('<BHIHHBH',2,1,10,0,1,50,40001)
    agent+=struct.pack('<BHIHHBH',1,1,10,1,1,50,40001)
    fight=struct.pack('<iHBH',1,1,0,0)+struct.pack('<3IH4H4HB',10,10,10,0,1,0,0,0,500,1,10,0,0)
    fight+=struct.pack('<BII',6,8,28)+b'\0'*36
    if tail:fight+=b'\x01'
    return dict(ArkStarData_C=star,ArkAgentData_C=agent,ArkFightData_C=fight)


def catalog():
    raw=raw_catalogs()
    c=dict(stars=schema.parse_stars(raw['ArkStarData_C']),agents=schema.parse_agents(raw['ArkAgentData_C']),
           fights=schema.parse_fights(raw['ArkFightData_C']),texts={10:'事件',20:'題目',21:'甲',22:'乙',23:'丙',24:'丁'})
    c['agents'][1]['name']='情報員';c['fights'][1]['name']='戰鬥事件'
    return c


def snapshot():
    w=Writer().u8(1).u16(0).u8(1).u8(1).u8(1).u8(1).u8(1).u8(0)
    w.raw(b'\0'*6+b'\0'*60)
    return Packet(191,1,w.build())


def events(kind=1,event_id=1):
    return Packet(191,2,Writer().u16(event_id).u8(kind).u8(1).raw(b'\0'*44).u8(0).build())


class StarArkTests(unittest.TestCase):
    def setUp(self):
        self.catalog=catalog();self.runtime=SimpleNamespace(ark_catalog=self.catalog,
            catalog_identity=SimpleNamespace(key='a'*64))
        for name,value in [('current_runtime',self.runtime),('current_catalog_token',(True,'a'*64))]:
            p=patch('wlre.services.world.dynamic_bundle_runtime.'+name,return_value=value)
            p.start();self.addCleanup(p.stop)
        self.state=State(phase='world_ready',initial_data_complete=True)
        self.state.apply(dict(type='world_player',player=dict(role_id=1,x=0,y=0,scene=500)))
        self.state.phase='world_ready'
        self.state.inventory.update(ready=True,reliable=True,capacity=10,items={},revision=1)
        self.state.daily_tasks.update(ready=True,groups_ready=True,catalog_ready=True,catalog_token=(True,'a'*64),
            rows=[dict(cycle=1,condition_kind=9,condition_params=[1,3,0],progress=0,goal=3),
                  dict(cycle=1,condition_kind=9,condition_params=[2,1,0],progress=0,goal=1)])
        self.feed(snapshot());self.feed(events());self.coin(1000)
        self.state.star_ark['enabled']=False
        self.logic=SessionLogic();self.logic.world_acknowledged=True
        ark.tick(self.state,True,0)

    def feed(self,p):self.state.apply(decode(p))

    def coin(self,amount,offset=0,add=True):
        self.feed(Packet(75,24,Writer().u32(amount).u32(offset).u8(int(add)).u8(0).build()))

    def progress(self,subtype,value):
        self.state.daily_tasks['rows'][subtype-1]['progress']=value

    def dispatched(self):self.feed(Packet(191,3,b'\x01\x01\x01\x00'+struct.pack('<H',3636)))

    def test_dispatch_exact_packet_waits_for_money_ship_and_daily_progress_in_any_order(self):
        for order in [('ship','coin','daily'),('daily','coin','ship'),('coin','ship','daily')]:
            with self.subTest(order=order):
                self.setUp()
                self.assertEqual(ark.begin(self.state,'dispatch',True,now=1),[Packet(191,1,b'\x01\x01\x01\x00')])
                for i,part in enumerate(order):
                    if part=='ship':self.dispatched()
                    elif part=='coin':self.coin(880,120,False)
                    else:self.progress(2,1)
                    ark.tick(self.state,True,2+i)
                    self.assertEqual(self.state.star_ark['pending'] is None,i==2)
                self.assertEqual(self.state.star_ark['confirmed'],120)
                self.assertEqual(self.state.star_ark['reserved'],120)
                with self.assertRaises(ProtocolError):ark.begin(self.state,'dispatch',True,now=8)

    def test_discount_and_unity_midpoint_rounding(self):
        a=self.state.star_ark['agents'][1]
        self.catalog['agents'][1]['skills'][0].update(initial=125,add=0)
        self.catalog['stars'][1]['prices'][0]=100
        self.assertEqual(schema.dispatch_quote(self.catalog,1,1,a)['price'],88) # 87.5 -> even
        self.catalog['agents'][1]['skills'][0]['initial']=135
        self.assertEqual(schema.dispatch_quote(self.catalog,1,1,a)['price'],86) # 86.5 -> even

    def test_cost_budget_balance_busy_and_unknown_skills_fail_closed(self):
        for key,value in [('budget',119),('hours',6)]:
            original=self.state.star_ark[key];self.state.star_ark[key]=value
            with self.assertRaises(ProtocolError):ark.begin(self.state,'dispatch',True,now=1)
            self.state.star_ark[key]=original
        self.coin(119)
        with self.assertRaisesRegex(ProtocolError,'星力不足'):ark.begin(self.state,'dispatch',True,now=1)
        self.coin(1000);self.catalog['agents'][1]['skills'][0]['kind']=99
        with self.assertRaises(ProtocolError):ark.begin(self.state,'dispatch',True,now=1)
        self.assertEqual(self.state.star_ark['reserved'],0)

    def test_timeout_and_pause_never_refund_or_resend(self):
        ark.begin(self.state,'dispatch',True,now=1)
        ark.command(self.state,dict(action='pause'),True)
        ark.tick(self.state,True,21)
        self.assertTrue(self.state.star_ark['uncertain'])
        self.assertEqual(self.state.star_ark['reserved'],120)
        with self.assertRaises(ProtocolError):ark.begin(self.state,'dispatch',True,now=30)
        self.assertEqual(ark.tick(self.state,True,30),[])

    def test_duplicate_unrelated_currency_and_mismatched_ship_stop(self):
        for variant in ('duplicate','snapshot','delta','ship','skill'):
            with self.subTest(variant=variant):
                self.setUp();ark.begin(self.state,'dispatch',True,now=1)
                if variant=='duplicate':self.coin(880,120,False);self.coin(760,120,False)
                elif variant=='snapshot':self.coin(880)
                elif variant=='delta':self.coin(990,10,False)
                elif variant=='skill':self.feed(Packet(191,6,b'\x01\x01\x02'))
                else:self.feed(Packet(191,3,b'\x01\x01\x01\x00'+struct.pack('<H',3600)))
                self.assertTrue(self.state.star_ark['uncertain'])

    def test_role_version_daily_generation_disconnect_and_error_invalidate(self):
        for variant in ('role','version','day','disconnect','error'):
            with self.subTest(variant=variant):
                self.setUp();ark.begin(self.state,'dispatch',True,now=1)
                if variant=='role':self.state.player['role_id']=2
                elif variant=='version':
                    p=patch('wlre.services.world.dynamic_bundle_runtime.current_catalog_token',return_value=(True,'b'*64))
                    p.start();self.addCleanup(p.stop)
                elif variant=='day':self.state.daily_tasks['generation']+=1
                elif variant=='disconnect':self.logic.disconnect(self.state)
                else:self.feed(Packet(191,0,b'\x04'))
                ark.tick(self.state,True,2)
                self.assertTrue(self.state.star_ark['uncertain'])

    def start_fight(self):
        self.state.auto_battle['enabled']=True
        return ark.begin(self.state,'fight',True,self.state.star_ark['events'][1],1)

    def win(self):self.feed(Packet(191,15,b'\x01\x01\x00\x01'+struct.pack('<BII',6,8,28)))

    def test_fight_requires_result_completion_and_daily_progress(self):
        self.assertEqual(self.start_fight(),[Packet(191,4,b'\x01\x01\x00')])
        self.feed(Packet(191,10,b'\x01\x01\x00'));ark.tick(self.state,True,2)
        self.assertIsNotNone(self.state.star_ark['pending'])
        self.win();ark.tick(self.state,True,3)
        self.assertIsNotNone(self.state.star_ark['pending'])
        self.progress(1,1);ark.tick(self.state,True,4)
        self.assertIsNone(self.state.star_ark['pending'])
        self.assertEqual(self.state.star_ark['events'][1]['id'],0)

    def test_fight_loss_stops_continuation_and_unknown_rewards_do_not_start(self):
        self.start_fight();self.feed(Packet(191,15,b'\x00'))
        self.assertFalse(self.state.star_ark['enabled'])
        self.assertIsNone(self.state.star_ark['pending'])
        self.state.star_ark['attempted']=[]
        self.catalog['fights'][1]['awards'][0]['kind']=20
        with self.assertRaises(ProtocolError):self.start_fight()

    def test_auto_battle_can_act_in_own_ark_fight_but_other_consumers_wait(self):
        from wlre.services.coordination import reason,command_reason
        self.start_fight();self.state.battle.update(active=True,war_style=19)
        self.assertEqual(reason(self.state,'auto_battle'),'')
        self.assertEqual(command_reason(self.state,dict(type='battle_action')),'')
        for service in ('daily_tasks','guild_actions','crafting','roaming','maintenance'):
            self.assertTrue(reason(self.state,service))
        for command in ('start_alchemy','walk','instance_start','field_item','companion'):
            self.assertTrue(command_reason(self.state,dict(type=command)))
        ark.freeze(self.state.star_ark,'測試結果不明')
        self.assertTrue(reason(self.state,'auto_battle'))
        self.assertTrue(command_reason(self.state,dict(type='battle_action')))

    def test_question_manual_answer_and_only_server_confirmed_correct_answer_is_reused(self):
        self.feed(events(3,2));ark.tick(self.state,True,0)
        self.assertEqual(ark.command(self.state,dict(action='question',index=1),True,1),[Packet(191,6,b'\x01\x02\x00')])
        question=Packet(191,11,struct.pack('<IBII4I',20,6,8,10,21,22,23,24))
        self.feed(question);self.assertEqual(ark.tick(self.state,True,2),[])
        self.assertEqual(self.state.star_ark['question']['text'],'題目')
        self.assertEqual(ark.command(self.state,dict(action='answer',index=2),True,3),[Packet(191,7,b'\x02')])
        with self.assertRaises(ProtocolError):ark.command(self.state,dict(action='answer',index=2),True,4)
        self.feed(Packet(191,12,b'\x01\x02'));self.feed(Packet(191,10,b'\x01\x02\x00'))
        self.progress(1,1);ark.tick(self.state,True,5)
        self.assertEqual(self.state.star_ark['answers'],{20:22})
        self.feed(events(3,3));ark.tick(self.state,True,6)
        ark.command(self.state,dict(action='question',index=1),True,7);self.feed(question)
        self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,8),[Packet(191,7,b'\x02')])

    def test_main_items_shops_are_not_auto_executed_and_global_pause_preserves_intent(self):
        self.state.star_ark.update(enabled=True,dispatch_enabled=False)
        self.feed(events(2,2));self.assertEqual(ark.tick(self.state,True,1),[])
        self.assertIn('尚未自動',self.state.star_ark['rows'][0]['execution'])
        self.state.automation['enabled']=False;self.state.star_ark['dispatch_enabled']=True
        self.assertEqual(ark.tick(self.state,True,2),[])
        self.assertEqual(self.state.star_ark['reserved'],0)

    def test_real_session_and_scheduler_send_once_and_never_start_dungeons(self):
        from wlre.network.service_scheduler import advance_services
        self.logic.command(dict(type='star_ark',action='settings',enabled=True,dispatch_enabled=True,
                                fights_enabled=False,hours=1,budget=120),self.state)
        # Keep unrelated daily reward interpretation out of this scenario.
        self.state.daily_tasks['enabled']=False
        sent=[]
        with patch('wlre.services.daily_tasks.tick',return_value=[]):
            for _ in range(3):advance_services(self.logic,self.state,sent.append,lambda p:None,lambda e:None,None)
        self.assertEqual(sent,[Packet(191,1,b'\x01\x01\x01\x00')])

    def test_real_s124_snapshot_progress_and_scheduler_confirm_dispatch_together(self):
        from test_daily_task_runtime import catalog as daily_catalog,snapshot as daily_snapshot
        from wlre.network.service_scheduler import advance_services
        from wlre.services.daily_tasks import defaults as daily_defaults
        base=daily_catalog()['tasks'][0]
        self.runtime.daily_tasks=dict(tasks=[
            {**base,'condition_kind':9,'condition_params':[1,3,0],'goal':3},
            {**base,'id':2,'index':201,'condition_kind':9,'condition_params':[2,1,0],'goal':1}],rewards=[])
        self.state.daily_tasks=daily_defaults();self.state.daily_tasks.update(role_id=1,enabled=False)
        self.feed(daily_snapshot(progress=0));self.feed(Packet(124,2,b'\x01\x02'))
        self.state.star_ark.update(enabled=True,fights_enabled=False)
        sent=[]
        def advance():advance_services(self.logic,self.state,sent.append,lambda p:None,lambda e:None,None)
        advance();self.assertEqual(sent,[Packet(191,1,b'\x01\x01\x01\x00')])
        self.dispatched();self.coin(880,120,False);advance()
        self.assertIsNotNone(self.state.star_ark['pending'])
        self.feed(Packet(124,3,b'\x02\x01\x02\x01'));advance();advance()
        self.assertIsNone(self.state.star_ark['pending'])
        self.assertEqual(self.state.star_ark['confirmed'],120)
        self.assertEqual(sent,[Packet(191,1,b'\x01\x01\x01\x00')])

    def test_other_bag_updates_cannot_confirm_fight_item_rewards(self):
        self.catalog['fights'][1]['awards'][0]=dict(kind=10,id=200,value=1)
        self.start_fight()
        self.feed(Packet(191,15,b'\x01\x01\x00\x01'+struct.pack('<BII',10,200,1)))
        self.feed(Packet(191,10,b'\x01\x01\x00'));self.progress(1,1)
        self.state.inventory.update(revision=2,items={'1':dict(item_id=201,count=1)})
        ark.tick(self.state,True,3);self.assertIsNotNone(self.state.star_ark['pending'])
        self.state.inventory.update(revision=3,items={'1':dict(item_id=201,count=1),'2':dict(item_id=200,count=1)})
        ark.tick(self.state,True,4);self.assertIsNone(self.state.star_ark['pending'])

    def test_other_battle_type_or_event_refresh_cannot_keep_automation_running(self):
        self.start_fight();self.state.battle.update(active=True,war_style=16)
        ark.tick(self.state,True,2)
        self.assertTrue(self.state.star_ark['uncertain'])
        self.setUp();self.start_fight();self.feed(events())
        self.assertTrue(self.state.star_ark['uncertain'])

    def test_wire_and_settings_reject_truncated_trailing_duplicate_and_invalid_values(self):
        packets=[snapshot(),events(),Packet(75,24,struct.pack('<IIBB',1000,0,1,0)),
                 Packet(191,3,b'\x01\x01\x01\x00\x10\x0e'),Packet(191,10,b'\x01\x01\x00')]
        for packet in packets:
            with self.assertRaises(ProtocolError):decode(Packet(packet.main,packet.sub,packet.payload[:-1]))
            with self.assertRaises(ProtocolError):decode(Packet(packet.main,packet.sub,packet.payload+b'\0'))
        for bad in [dict(budget=True),dict(hours=7),dict(enabled=1)]:
            value=dict(action='settings',enabled=True,dispatch_enabled=True,fights_enabled=True,hours=1,budget=120)
            value.update(bad)
            with self.assertRaises(ProtocolError):ark.command(self.state,value,True)


class ArkCatalogTests(unittest.TestCase):
    def test_exact_supported_fight_layouts_and_malformed_records(self):
        for tail in (False,True):
            raw=raw_catalogs(tail)
            self.assertEqual(schema.parse_fights(raw['ArkFightData_C'])[1]['fight'],1)
            for name,parse in [('ArkStarData_C',schema.parse_stars),('ArkAgentData_C',schema.parse_agents),('ArkFightData_C',schema.parse_fights)]:
                with self.assertRaises(ValueError):parse(raw[name]+b'!')
                with self.assertRaises(ValueError):parse(raw[name][:-2])


class ArkGuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:self.root=tk.Tk();self.root.withdraw()
        except tk.TclError:self.skipTest('需要原生 Tk 顯示環境')
        self.addCleanup(self.root.destroy)

    def test_settings_pause_and_non_fight_items_do_not_emit_actions(self):
        from wlre.ui.star_ark_ui import StarArkPanel
        app=SimpleNamespace(live_active=True,send=Mock())
        panel=StarArkPanel(self.root,app);d=ark.defaults()
        panel.render(dict(phase='world_ready',star_ark=d))
        panel.budget.set('240');panel.settings()
        self.assertEqual(app.send.call_args.args[0]['budget'],240)
        d['status']='收到新狀態';panel.render(dict(phase='world_ready',star_ark=d))
        self.assertEqual(panel.budget.get(),'240')
        panel.pause.invoke();self.assertEqual(app.send.call_args.args[0]['action'],'pause')
