"""Real S122 decoding, session commands, scheduling and stale-state boundaries."""
import unittest
from unittest.mock import patch
from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet,Writer,ProtocolError
from wlre.services import time_cube as cube
from wlre.services.coordination import command_reason,reason


def info(count=1,kind=0,check=180,keep=1):
    return Packet(122,1,Writer().u8(kind).u8(count).u16(check).u16(keep).build())


class CubeTests(unittest.TestCase):
    def setUp(self):
        self.state=State(phase='world_ready',initial_data_complete=True)
        self.state.player.update(role_id=1)
        self.state.inventory.update(ready=True,reliable=True,capacity=10,revision=1,items={})
        self.logic=SessionLogic();self.logic.world_acknowledged=True
        self.receive(info())

    def receive(self,packet):
        event=decode(packet);self.state.apply(event);self.logic.receive(event,self.state)

    def open(self):return self.logic.command(dict(type='time_cube',action='open'),self.state)

    def test_exact_empty_open_and_no_retry_after_duplicate_or_legacy_result(self):
        self.assertEqual(self.open(),[Packet(122,2)])
        self.receive(info())
        self.receive(Packet(122,2,b'legacy payload is intentionally ignored'))
        self.assertIsNotNone(self.state.time_cube['pending'])
        for _ in range(4):self.assertEqual(cube.tick(self.state,True),[])
        with self.assertRaises(ProtocolError):self.open()
        self.assertEqual(self.state.time_cube['count'],1)

    def test_both_orders_require_count_change_and_bag_update(self):
        for first in ('bag','count'):
            with self.subTest(first=first):
                self.setUp();self.open()
                bag=dict(type='bag_snapshot',capacity=10,items=[dict(index=1,item_id=100,count=1)])
                if first=='bag':self.state.apply(bag)
                else:self.receive(info(0))
                self.assertEqual(cube.tick(self.state,True),[])
                self.assertIsNotNone(self.state.time_cube['pending'])
                if first=='bag':self.receive(info(0))
                else:self.state.apply(bag)
                self.assertEqual(cube.tick(self.state,True),[])
                self.assertIsNone(self.state.time_cube['pending'])
                self.assertFalse(self.state.time_cube['uncertain'])
                self.assertEqual(cube.tick(self.state,True),[])

    def test_timeout_stays_uncertain_even_after_late_count_bag_and_toggle(self):
        self.open();due=self.state.time_cube['pending']['due']
        self.assertEqual(cube.tick(self.state,True,due),[])
        self.receive(info(0))
        self.state.inventory['revision']+=1
        for value in (False,True):self.logic.command(dict(type='time_cube',action='auto',enabled=value),self.state)
        self.receive(info(1))
        self.assertEqual(cube.tick(self.state,True,due+100),[])
        with self.assertRaisesRegex(ProtocolError,'結果不明'):self.open()

    def test_countdown_never_authorizes_open(self):
        self.receive(info(0,check=1,keep=1))
        self.assertEqual(cube.tick(self.state,True,10**12),[])
        self.assertEqual(self.state.time_cube['count'],0)
        with self.assertRaises(ProtocolError):self.open()
        self.receive(info(1))
        self.assertEqual(cube.tick(self.state,True),[Packet(122,2)])

    def test_kind_one_preserves_timer_and_lucky_bag_id_is_only_metadata(self):
        deadline=self.state.time_cube['deadline']
        self.receive(info(2,kind=1,check=0,keep=0))
        self.assertEqual(self.state.time_cube['deadline'],deadline)
        self.receive(Packet(122,3,b'\x34\x12'))
        self.assertEqual(self.state.time_cube['item_id'],0x1234)
        self.assertEqual(self.state.time_cube['count'],2)

    def test_malformed_packets_fail_before_state_mutation(self):
        for packet in (Packet(122,1,b''),info(4),info(1,kind=2),
                       Packet(122,1,info().payload+b'\x00'),Packet(122,3,b'\x00\x00')):
            with self.subTest(packet=packet),self.assertRaises(ProtocolError):decode(packet)
        self.assertEqual(self.state.time_cube['revision'],1)

    def test_global_pause_and_individual_disable_and_unready_world(self):
        self.logic.command(dict(type='automatic_flows',enabled=False),self.state)
        self.assertEqual(cube.tick(self.state,True),[])
        self.logic.command(dict(type='automatic_flows',enabled=True),self.state)
        self.logic.command(dict(type='time_cube',action='auto',enabled=False),self.state)
        self.assertEqual(cube.tick(self.state,True),[])
        self.logic.command(dict(type='time_cube',action='auto',enabled=True),self.state)
        self.assertEqual(cube.tick(self.state,False),[])
        self.logic.world_acknowledged=False
        with self.assertRaises(ProtocolError):self.open()

    def test_bag_space_and_conflicts_defer_and_resume(self):
        self.receive(info(3))
        self.state.inventory['capacity']=2
        self.assertEqual(cube.tick(self.state,True),[])
        self.state.inventory['capacity']=10
        self.state.battle['active']=True
        self.assertEqual(cube.tick(self.state,True),[])
        self.state.battle['active']=False
        self.state.room_storage['pending']={'operation':'test'}
        self.assertEqual(cube.tick(self.state,True),[])
        self.state.room_storage['pending']=None
        self.state.inventory['reserved']={'1':1}
        self.assertEqual(cube.tick(self.state,True),[])
        self.state.inventory['reserved']={}
        self.assertEqual(cube.tick(self.state,True),[Packet(122,2)])
        self.assertIn('魔方',command_reason(self.state,dict(type='craft')))
        self.assertIn('魔方',reason(self.state,'expedition'))

    def test_role_change_and_disconnect_do_not_reuse_old_authorization(self):
        self.state.player['role_id']=2
        self.assertEqual(cube.tick(self.state,True),[])
        self.state.apply(dict(type='role_list_available',roles=[]))
        self.assertFalse(self.state.time_cube['ready'])
        self.state.phase='world_ready';self.receive(info(1));self.open()
        self.logic.disconnect(self.state)
        self.assertFalse(self.state.time_cube['enabled'])
        self.assertFalse(self.state.time_cube['ready'])
        self.assertTrue(self.state.time_cube['uncertain'])

    def test_scheduler_sends_once_without_opening_ui(self):
        from wlre.network.service_scheduler import advance_services
        sent=[]
        # Stop unrelated services; preserve the actual scheduler and cube service.
        self.logic.maintenance.tick=lambda *a:[]
        self.logic.expedition.tick=lambda *a:[]
        self.logic.crafting.tick=lambda *a:[]
        self.logic.field_supply.tick=lambda *a:None
        self.logic.auto_battle.tick=lambda *a:[]
        self.logic.alchemy.tick=lambda *a:[]
        self.logic.roaming.tick=lambda *a:[]
        self.logic.movement.tick=lambda *a:[]
        self.logic.portal_travel.tick=lambda *a:[]
        self.logic.flows.tick=lambda *a:[]
        for _ in range(3):advance_services(self.logic,self.state,sent.append,lambda p:None,lambda e:None,None)
        self.assertEqual(sent,[Packet(122,2)])


class CubeIconTests(unittest.TestCase):
    def test_official_pngs_decode_at_original_sprite_dimensions(self):
        from PIL import Image
        from wlre.paths import RESOURCE_ROOT
        from wlre.ui.function_icons import icon_image
        for name,size in (('MainIcon_023',(59,57)),('Btn_CategoryLoginAward002',(60,60))):
            with self.subTest(name=name):
                with Image.open(RESOURCE_ROOT/'assets'/'function-icons'/(name+'.png')) as image:
                    self.assertEqual(image.format,'PNG')
                    self.assertEqual(image.size,size)
                    image.verify()
                rendered=icon_image(name)
                self.assertEqual(rendered.size,(34,34))
                self.assertIsNotNone(rendered.getbbox())


# Native UI coverage runs on CI's Xvfb / Windows desktop.
import os
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import Mock


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires Tk / Xvfb')
class CubeUITests(unittest.TestCase):
    def setUp(self):
        from wlre.ui.benefits_ui import BenefitsPanel
        self.root=tk.Tk()
        self.app=SimpleNamespace(live_active=True,snapshot={},send=Mock())
        self.panel=BenefitsPanel(self.root,self.app)
        self.panel.pack(fill='both',expand=True)
        self.root.geometry('720x440');self.root.update()
        self.addCleanup(self.root.destroy)

    def test_cube_subtab_and_controls_send_only_explicit_commands(self):
        self.assertEqual([self.panel.tabs.tab(p,'text') for p in self.panel.tabs.tabs()],['魔方','每日任務','每週任務','組織'])
        state=State(phase='world_ready',initial_data_complete=True)
        state.time_cube.update(ready=True,count=1,deadline=0)
        self.panel.render(state.snapshot());self.root.update()
        # A real PhotoImage must survive tab rebuilds; opening never sends a packet.
        button=self.panel.tabs.buttons[str(self.panel.cube)]
        self.assertTrue(button.cget('image'))
        self.assertTrue(hasattr(button,'_function_icon'))
        from wlre.ui.function_icons import icon_photo
        self.assertIsNotNone(icon_photo(self.root,'福利'))
        self.panel.tabs._rebuild()
        self.assertTrue(self.panel.tabs.buttons[str(self.panel.cube)].cget('image'))
        self.app.send.assert_not_called()
        self.panel.auto.invoke()
        self.app.send.assert_called_once_with(dict(type='time_cube',action='auto',enabled=False))
        self.app.send.reset_mock();self.panel.open_button.invoke()
        self.app.send.assert_called_once_with(dict(type='time_cube',action='open'))
        self.assertGreater(self.panel.open_button.winfo_height(),0)
        self.assertLessEqual(self.panel.open_button.winfo_rooty()+self.panel.open_button.winfo_height(),
                             self.root.winfo_rooty()+self.root.winfo_height())

    def test_pending_and_uncertain_disable_open_and_pause_is_visible(self):
        state=State(phase='world_ready')
        state.time_cube.update(ready=True,count=3,pending={'count':3})
        self.panel.render(state.snapshot())
        self.assertEqual(str(self.panel.open_button['state']),'disabled')
        state.time_cube.update(pending=None,uncertain=True)
        state.automation['enabled']=False
        self.panel.render(state.snapshot())
        self.assertIn('暫停',self.panel.status.get())
        self.assertEqual(str(self.panel.open_button['state']),'disabled')


if __name__=='__main__':unittest.main()
