"""Explicit goals continue with real guarded packet builders and server events."""
import unittest
from types import SimpleNamespace
from contextlib import nullcontext
from unittest.mock import patch,Mock
from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet,ProtocolError
from wlre.services.world.movement import Movement
from wlre.services.world.navigation import Mesh
from test_npc_dialogue_v058 import s20_effect


class AutomaticFlowTests(unittest.TestCase):
    def setUp(self):
        self.state=State(phase='world_ready',initial_data_complete=True)
        self.state.player.update(role_id=1,scene=12500,x=0,y=800)
        self.state.location.update(confirmed=dict(scene=12500,x=0,y=800,packet_number=1),confirmed_is_current=True)
        self.logic=SessionLogic();self.logic.world_acknowledged=True
        self.npc=dict(index=7,npc_id=900,x=100,y=200,event_count=1)
        runtime=SimpleNamespace(stages={12500:dict(pos_x_ratio=2,pos_y_ratio=4)},
            npc_index=SimpleNamespace(for_scene=lambda _:[self.npc]))
        for name in ('wlre.services.world.npc_approach.official_runtime',):
            p=patch(name,return_value=runtime);p.start();self.addCleanup(p.stop)
        for name in ('wlre.network.npc_dialogue.NPCIndex','wlre.network.automatic_flows.NPCIndex'):
            p=patch(name,return_value=runtime.npc_index);p.start();self.addCleanup(p.stop)
        class Converter:
            def route(self,repository,scene,start,end,start_height=None):return repository.load(scene).route(start,end)
            def to_packet(self,scene,x,z):return x,z
        mesh=Mesh({'tiles':[{'vertices_b_int3':[[0,0,0],[1000,0,0],[1000,0,1000],[0,0,1000]],'triangles':[[0,1,2],[0,2,3]]}]})
        mesh.scene_id='fixture'
        self.logic.movement=Movement(Converter(),SimpleNamespace(load=lambda _:mesh))

    def approach(self):
        with patch('wlre.network.commands.time.monotonic',return_value=0):
            self.logic.command(dict(type='npc_approach',scene=12500,npc_index=7,npc_id=900),self.state)

    def arrive(self):
        self.approach()
        packets=self.logic.movement.tick(self.state,.2)
        self.assertTrue(packets)
        self.state.apply(dict(type='movement_request',x=100,y=800))

    def test_reach_npc_then_interact_and_continue_without_extra_commands(self):
        self.approach()
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,0),[])
        self.logic.movement.tick(self.state,.2)
        self.state.apply(dict(type='movement_request',x=100,y=800))
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,1),[Packet(20,1,b'\x07\x00')])
        self.assertFalse(self.state.location['confirmed_is_current'])
        event=decode(s20_effect());self.state.apply(event);self.logic.receive(event,self.state)
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,2),[Packet(20,6,b'\x00')])
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,3),[])
        event=decode(s20_effect(6,1));self.state.apply(event);self.logic.receive(event,self.state)
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,4),[])
        self.assertEqual(self.state.npc_dialogue['phase'],'choice_unavailable')

    def test_new_target_stop_role_or_version_change_never_uses_old_npc_goal(self):
        for variant in ('stop','route','role','version'):
            with self.subTest(variant=variant):
                self.state.local_movement=None
                self.state.location['confirmed_is_current']=True
                self.logic.flows.next_tick=0
                self.arrive()
                if variant=='stop':self.logic.command({'type':'stop_walk'},self.state)
                elif variant=='route':self.state.local_movement['route_id']+=1
                elif variant=='role':self.state.player['role_id']=2
                with patch('wlre.network.automatic_flows.current_catalog_token',return_value=('different',None)) if variant=='version' else nullcontext():
                    self.assertEqual(self.logic.flows.tick(self.logic,self.state,10),[])
                self.state.player['role_id']=1
                self.logic.flows.next_tick=0

    def test_a_new_room_goal_cancels_an_older_npc_interaction_goal(self):
        self.approach()
        self.logic.flows.remember({'type':'instance_join','mode':'main','room_id':30012},self.state,0)
        self.assertNotIn('npc',self.logic.flows.goals)
        self.logic.movement.tick(self.state,.2)
        self.state.apply(dict(type='movement_request',x=100,y=800))
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,1),[])
        self.assertFalse(self.state.npc_dialogue.get('active'))

    def test_global_pause_prevents_goals_and_clears_future_work_without_unlocking_event(self):
        self.arrive();self.state.event_flow['blocked']=True
        self.logic.command({'type':'automatic_flows','enabled':False},self.state)
        self.assertFalse(self.state.automation['enabled'])
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,1),[])
        self.assertTrue(self.state.event_flow['blocked'])
        self.assertFalse(self.logic.flows.goals)

    def room(self,mode='main',host=1):
        data=self.state.instances[mode]
        data.update(phase='waiting',room=dict(room_id=30012,host_id=host,members=2,capacity=2,standby=False),
                    members=[{'role_id':host},{'role_id':2 if host==1 else 1}])
        self.logic.flows.remember({'type':'instance_join','mode':mode,'room_id':30012},self.state,0)
        return data

    def test_normal_room_waits_for_roster_then_starts_and_enters_once(self):
        data=self.room();data['members']=[]
        row=dict(kind=1,map_id=30012,min_members=2,max_members=4)
        with patch('wlre.services.instance_start.entries_for',return_value=[row]),patch('wlre.services.instance_entry.entries_for',return_value=[row]):
            self.assertEqual(self.logic.flows.tick(self.logic,self.state,0),[])
            data['members']=[{'role_id':1},{'role_id':2}]
            self.assertEqual(self.logic.flows.tick(self.logic,self.state,1),[Packet(85,7)])
            self.assertEqual(self.logic.flows.tick(self.logic,self.state,2),[])
            event=decode(Packet(85,5,b'\x03'));self.state.apply(event);self.logic.receive(event,self.state)
            self.assertEqual(self.logic.flows.tick(self.logic,self.state,3),[Packet(85,9)])
            self.assertEqual(self.logic.flows.tick(self.logic,self.state,4),[])

    def test_guest_never_starts_room_and_uncertain_room_never_resends(self):
        data=self.room(host=2)
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,0),[])
        data['enter_uncertain']=True;data['phase']='started'
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,1),[])
        self.assertNotIn('room',self.logic.flows.goals)

    def test_coop_ready_and_free_reward_enable_use_existing_guards(self):
        data=self.room(mode='coop')
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,0),[Packet(186,7,b'\x3c\x75\x01')])
        self.assertTrue(data['auto_claim_enabled'])
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,1),[])
        # A deliberate cancel prevents the coordinator from enabling ready again.
        self.logic.flows.remember({'type':'instance_coop_standby','standby':False},self.state,2)
        self.assertNotIn('room',self.logic.flows.goals)

    def test_crafting_waits_for_pending_material_ack_before_start(self):
        recipe={'tool_id':39001}
        self.state.crafting.update(ready=True,queue={'1':{'index':1,'item_id':100}},human_index=0,human_id=0)
        self.logic.crafting.pending={'action':'add'}
        self.logic.flows.remember({'type':'craft','action':'add'},self.state,0)
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,0),[])
        self.logic.crafting.pending=None
        with patch('wlre.services.items.crafting.RECIPES',{'100':recipe}),patch('wlre.services.items.crafting.tool_for',return_value=3):
            self.assertEqual(self.logic.flows.tick(self.logic,self.state,1),[Packet(64,2,b'\x03\x00\x01\x00\x00\x00\x00\x00')])
            self.assertEqual(self.logic.flows.tick(self.logic,self.state,2),[])
        self.assertTrue(self.state.crafting['auto_continue'])

    def test_failed_add_does_not_start_an_older_queue(self):
        self.state.crafting.update(ready=True,queue={'1':{'index':1,'item_id':100}})
        self.logic.flows.remember({'type':'craft','action':'add'},self.state,0)
        event={'type':'craft_failed','reason':'包包空間不足','index':1,'points':0}
        self.state.apply(event);self.logic.receive(event,self.state)
        self.assertNotIn('craft',self.logic.flows.goals)
        self.assertEqual(self.logic.flows.tick(self.logic,self.state,1),[])

    def test_room_list_refresh_is_automatic_only_while_visible_and_rate_limited(self):
        from wlre.ui.instance_ui import InstanceModePage
        page=SimpleNamespace(_automatic_refresh_ready=True,
                             app=SimpleNamespace(live_active=True,worker=Mock(is_alive=lambda:True)),
                             winfo_ismapped=Mock(return_value=False),refresh_rooms=Mock())
        with patch('wlre.ui.instance_ui.time.monotonic',return_value=100):
            InstanceModePage.automatic_refresh_rooms(page)
            page.refresh_rooms.assert_not_called()
            page.winfo_ismapped.return_value=True
            InstanceModePage.automatic_refresh_rooms(page)
            InstanceModePage.automatic_refresh_rooms(page)
            page.refresh_rooms.assert_called_once()
        with patch('wlre.ui.instance_ui.time.monotonic',return_value=160):
            InstanceModePage.automatic_refresh_rooms(page)
        self.assertEqual(page.refresh_rooms.call_count,2)
        page._automatic_refresh_due=0;page.app.live_active=False
        InstanceModePage.automatic_refresh_rooms(page)
        self.assertEqual(page.refresh_rooms.call_count,2)

    def test_rejected_initial_command_does_not_register_goal(self):
        with self.assertRaises(ProtocolError):
            self.logic.command(dict(type='npc_start',confirmed=False),self.state)
        self.assertFalse(self.logic.flows.goals)


if __name__=='__main__':unittest.main()
