"""S124 commands, real session scheduling, current catalog and reset boundaries."""
from copy import deepcopy
from types import SimpleNamespace
import struct
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet,Writer,ProtocolError
from wlre.services import daily_tasks as daily
from wlre.services.world.daily_task_catalog import goal,parse_rewards,bind_catalog
from wlre.services.world.daily_task_1275 import parse_daily_tasks
from test_daily_task_1275 import sample_daily


def snapshot(progress=1,day_done=0,week_done=(0,0),day_value=50,week_value=100):
    body=bytes([day_value,week_value])+bytes([progress]*8)+bytes([progress]*12)
    return Packet(124,1,body+bytes([day_done,0,0,0,*week_done,0,0,0,1,0]))


def marks(day=0,week=(0,0),chest=0,event=0):
    return Packet(124,3,bytes([1,50,100,day,chest,event,0,*week,0,0,0]))


def notice(kind=1):return Packet(124,4,bytes([kind])+ (b'\0'*9 if kind==2 else b''))


def catalog():
    row=dict(index=200,group=1,id=1,name='登入任務',cycle=1,goal=1,
             condition_kind=1,condition_params=[1,0,0],function_kind=0,function_arg1=0,function_arg2=0,
             awards=[dict(kind=12,id=1,value=10)])
    weekly={**row,'index':900,'group':2,'id':9,'cycle':2,'name':'每週任務'}
    chest=dict(id=1,kind=1,value=20,mark=1,awards=[dict(kind=2,id=0,value=10)])
    event={**chest,'id':2,'kind':2,'mark':2}
    return dict(tasks=[row,weekly],rewards=[chest,event])


class DailyRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.data=catalog();self.runtime=SimpleNamespace(daily_tasks=self.data,catalog_identity=SimpleNamespace(key='a'*64))
        for name,value in [('current_runtime',self.runtime),('current_catalog_token',(True,'a'*64))]:
            p=patch('wlre.services.world.dynamic_bundle_runtime.'+name,return_value=value)
            p.start();self.addCleanup(p.stop)
        self.state=State(phase='world_ready',initial_data_complete=True)
        self.state.player.update(role_id=1)
        self.state.daily_tasks['role_id']=1
        self.state.inventory.update(ready=True,reliable=True,capacity=10,revision=1,items={})
        self.logic=SessionLogic();self.logic.world_acknowledged=True
        self.feed(snapshot());self.feed(Packet(124,2,b'\x01\x02'))
        self.state.daily_tasks['enabled']=False
        daily.tick(self.state,True,0)
        self.state.daily_tasks['enabled']=True

    def feed(self,packet):
        event=decode(packet);self.state.apply(event);self.logic.receive(event,self.state)

    def test_task_claim_waits_for_marks_and_notice_in_both_orders(self):
        for first in ('marks','notice'):
            with self.subTest(first=first):
                self.setUp()
                self.assertEqual(daily.tick(self.state,True,1),[Packet(124,1,b'\xc8\x00')])
                self.feed(marks(day=1) if first=='marks' else notice())
                self.assertEqual(daily.tick(self.state,True,2),[])
                self.assertIsNotNone(self.state.daily_tasks['pending'])
                self.feed(notice() if first=='marks' else marks(day=1))
                self.assertEqual(daily.tick(self.state,True,3),[])
                self.assertIsNone(self.state.daily_tasks['pending'])
                self.assertFalse(self.state.daily_tasks['uncertain'])
                self.assertEqual(daily.tick(self.state,True,4),[Packet(124,1,b'\x84\x03')])

    def test_weekly_ninth_bit_and_all_eligible_chest_flags(self):
        self.feed(marks(day=1,week=(0,1)))
        self.assertEqual(daily.tick(self.state,True,1),[Packet(124,2,b'\x01')])
        self.feed(notice(2));self.feed(marks(day=1,week=(0,1),chest=1))
        daily.tick(self.state,True,2)
        self.assertIsNotNone(self.state.daily_tasks['pending'])  # Event mark must also arrive.
        self.feed(marks(day=1,week=(0,1),chest=1,event=2));daily.tick(self.state,True,3)
        self.assertIsNone(self.state.daily_tasks['pending'])
        self.assertEqual(daily.tick(self.state,True,4),[])

    def test_duplicate_notifications_timeout_toggle_and_late_reply_do_not_resend(self):
        daily.tick(self.state,True,1)
        for _ in range(3):self.feed(notice());self.assertEqual(daily.tick(self.state,True,2),[])
        daily.tick(self.state,True,21)
        self.assertTrue(self.state.daily_tasks['uncertain'])
        self.feed(marks(day=1))
        self.logic.command(dict(type='daily_tasks',action='auto',enabled=True),self.state)
        self.assertEqual(daily.tick(self.state,True,100),[])
        with self.assertRaises(ProtocolError):
            self.logic.command(dict(type='daily_tasks',action='task',index=900),self.state)

    def test_physical_award_requires_bag_update_after_authoritative_mark(self):
        self.data['tasks'][0]['awards']=[dict(kind=10,id=100,value=1)]
        self.assertEqual(daily.tick(self.state,True,1),[Packet(124,1,b'\xc8\x00')])
        self.feed(notice());self.feed(marks(day=1));daily.tick(self.state,True,2)
        self.assertIsNotNone(self.state.daily_tasks['pending'])
        self.state.apply(dict(type='bag_snapshot',capacity=10,items=[dict(index=1,item_id=100,count=1)]))
        daily.tick(self.state,True,3)
        self.assertIsNone(self.state.daily_tasks['pending'])

    def test_errors_stop_auto_and_never_repeat_a_rejected_claim(self):
        daily.tick(self.state,True,1);self.feed(Packet(124,5,b'\x0f'))
        self.assertFalse(self.state.daily_tasks['enabled'])
        self.assertIsNone(self.state.daily_tasks['pending'])
        self.assertEqual(daily.tick(self.state,True,2),[])
        self.logic.command(dict(type='daily_tasks',action='auto',enabled=True),self.state)
        with self.assertRaisesRegex(ProtocolError,'已要求'):
            self.logic.command(dict(type='daily_tasks',action='task',index=200),self.state)

    def test_no_partial_state_no_unknown_index_and_no_undone_claim(self):
        for field,value in [('ready',False),('groups_ready',False),('role_id',2)]:
            old=self.state.daily_tasks[field];self.state.daily_tasks[field]=value
            self.assertEqual(daily.tick(self.state,True,1),[])
            self.state.daily_tasks[field]=old
        for index in (999,True,-1):
            with self.assertRaises(ProtocolError):self.logic.command(dict(type='daily_tasks',action='task',index=index),self.state)
        self.data['tasks'][0]['goal']=2
        with self.assertRaises(ProtocolError):self.logic.command(dict(type='daily_tasks',action='task',index=200),self.state)

    def test_reset_requires_fresh_snapshot_and_group_in_either_order(self):
        for first in ('groups','snapshot'):
            with self.subTest(first=first):
                self.setUp();self.state.daily_tasks['enabled']=False
                self.feed(marks(day=1,week=(0,1)))
                if first=='snapshot':self.feed(snapshot())
                else:self.feed(Packet(124,2,b'\x01\x02'))
                self.state.daily_tasks['enabled']=True
                self.assertEqual(daily.tick(self.state,True,1),[])
                if first=='snapshot':self.feed(Packet(124,2,b'\x01\x02'))
                else:self.feed(snapshot())
                self.assertEqual(daily.tick(self.state,True,2),[Packet(124,1,b'\xc8\x00')])

    def test_group_change_during_pending_is_uncertain(self):
        daily.tick(self.state,True,1);self.feed(Packet(124,2,b'\x03\x02'));self.feed(snapshot())
        self.assertEqual(daily.tick(self.state,True,2),[])
        self.assertTrue(self.state.daily_tasks['uncertain'])

    def test_global_pause_and_disconnect_preserve_pending_safety(self):
        self.state.automation['enabled']=False
        self.assertEqual(daily.tick(self.state,True,1),[])
        self.state.automation['enabled']=True;daily.tick(self.state,True,2)
        from wlre.services.coordination import command_reason,reason
        self.assertIn('每日任務',command_reason(self.state,dict(type='craft')))
        self.assertIn('每日任務',reason(self.state,'time_cube'))
        self.logic.disconnect(self.state)
        self.assertFalse(self.state.daily_tasks['enabled'])
        self.assertTrue(self.state.daily_tasks['uncertain'])

    def test_untrusted_or_changed_runtime_never_authorizes_packets(self):
        self.runtime.daily_tasks=None
        self.assertEqual(daily.tick(self.state,True,1),[])
        self.runtime.daily_tasks=self.data
        with patch('wlre.services.world.dynamic_bundle_runtime.current_catalog_token',return_value=(True,'b'*64)):
            self.assertEqual(daily.tick(self.state,True,2),[])
        self.assertFalse(self.state.daily_tasks['ready'])

    def test_invalid_wire_layouts_fail(self):
        for packet in (Packet(124,1,b'\0'*32),Packet(124,3,b'\x02\x01\x09\x01'),
                       Packet(124,3,b'\x02\x01\x01\x03'),Packet(124,4,b'\x01\x00'),
                       Packet(124,4,b'\x02'+b'\0'*8),Packet(124,5,b'\x01\x00')):
            with self.subTest(packet=packet),self.assertRaises(ProtocolError):decode(packet)

    def test_full_scheduler_uses_c124_after_cube_and_does_not_start_rooms(self):
        from wlre.network.service_scheduler import advance_services
        sent=[]
        for service in ('maintenance','expedition','crafting','auto_battle','alchemy','roaming','movement','portal_travel','flows'):
            getattr(self.logic,service).tick=lambda *a:[]
        self.logic.field_supply.tick=lambda *a:None
        for _ in range(3):advance_services(self.logic,self.state,sent.append,lambda p:None,lambda e:None,None)
        self.assertEqual(sent,[Packet(124,1,b'\xc8\x00')])


class DailyCatalogTests(unittest.TestCase):
    def reward_raw(self):
        return struct.pack('<iHBII',1,7,1,20,1)+struct.pack('<BII',10,100,1)+b'\0'*27

    def test_official_condition_goals_and_strict_rewards(self):
        for kind,params,expected in [(3,[0,0,0],1),(6,[2,10,0],10),(13,[2,5,9],9),
                                     (13,[6,5,9],5),(16,[3,0,0],3),(99,[1,2,3],None)]:
            self.assertEqual(goal(dict(condition_kind=kind,condition_params=params)),expected)
        raw=self.reward_raw();self.assertEqual(parse_rewards(raw)[0]['mark'],1)
        for bad in (raw[:-1],raw+b'\0'):
            with self.assertRaises(ValueError):parse_rewards(bad)

    def test_catalog_binds_same_version_text_items_and_rejects_ambiguity(self):
        tasks=parse_daily_tasks(sample_daily());rewards=parse_rewards(self.reward_raw())
        bound=bind_catalog(tasks,rewards,{38681:'登入'},{100:{}})
        self.assertEqual(bound['tasks'][0]['goal'],1)
        with self.assertRaises(ValueError):bind_catalog(tasks,rewards,{}, {100:{}})
        with self.assertRaises(ValueError):bind_catalog(tasks,rewards,{38681:'登入'},{})
        tasks['tasks'].append(deepcopy(tasks['tasks'][0]))
        with self.assertRaises(ValueError):bind_catalog(tasks,rewards,{38681:'登入'},{100:{}})

    def test_sqlite_roundtrip_and_same_identity_corruption_rejected(self):
        from wlre.services.world.resource_database import record_inventory,read_catalog_tables
        raw=self.reward_raw()
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'catalog.sqlite3'
            record_inventory(db,'a'*64,{'tables/DailyTaskData_C.bytes':sample_daily(),
                                      'tables/DailyTaskRewardData_C.bytes':raw})
            result=read_catalog_tables(db,'a'*64,('daily_tasks','daily_rewards'))
            self.assertEqual(result['daily_rewards'][0]['id'],7)
            self.assertEqual(result['daily_tasks']['task_count'],1)
            with self.assertRaises(ValueError):record_inventory(db,'a'*64,{'tables/DailyTaskRewardData_C.bytes':raw+b'\0'})


import os
import tkinter as tk


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires Tk / Xvfb')
class DailyTaskUITests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        from wlre.ui.benefits_ui import BenefitsPanel
        self.root=tk.Tk();self.addCleanup(self.root.destroy)
        self.app=SimpleNamespace(live_active=True,snapshot={},send=Mock(),open_feature=Mock())
        self.panel=BenefitsPanel(self.root,self.app);self.app.benefits_panel=self.panel
        self.panel.pack(fill='both',expand=True);self.root.geometry('860x620');self.root.update()
        self.state=State(phase='world_ready')
        d=self.state.daily_tasks
        d.update(ready=True,groups_ready=True,catalog_ready=True,daily_group=1,weekly_group=2,
                 daily_value=50,weekly_value=100,daily_progress=[1]*8,weekly_progress=[1]*12)
        d['rows']=daily.task_rows(d,catalog());d['chests']=daily.chest_rows(d,catalog())
        self.app.snapshot=self.state.snapshot();self.panel.render(self.app.snapshot)
        self.panel.tabs.select(self.panel.daily_panel);self.root.update()

    def test_tabs_render_real_rows_selection_and_claim_have_no_confirmation_dialog(self):
        self.assertEqual([self.panel.tabs.tab(p,'text') for p in self.panel.tabs.tabs()],
                         ['魔方','每日任務','每週任務','組織','方舟'])
        panel=self.panel.daily_panel
        panel.tree.selection_set('200');panel.select();self.root.update()
        self.app.send.assert_not_called()
        self.assertIn('1/1',panel.tree.item('200','values'))
        panel.claim.invoke()
        self.app.send.assert_called_once_with(dict(type='daily_tasks',action='task',index=200))
        self.assertGreater(panel.tree.winfo_height(),80)
        self.assertLess(panel.status.get().count('\n'),5)

    def test_dungeon_destination_opens_window_without_starting_room_and_uncertain_locks_claims(self):
        d=self.state.daily_tasks;d['rows'][0].update(condition_kind=12,eligible=False)
        self.panel.render(self.state.snapshot());panel=self.panel.daily_panel
        panel.tree.selection_set('200');panel.select();panel.go.invoke()
        self.app.open_feature.assert_called_once_with('instance')
        self.app.send.assert_not_called()
        d['uncertain']=True
        self.panel.render(self.state.snapshot())
        self.assertEqual(str(panel.claim_all['state']),'disabled')
        self.assertEqual(str(panel.chest['state']),'disabled')
