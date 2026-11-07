"""A double-click approaches a current official NPC through normal locomotion only."""
import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.wire import ProtocolError
from wlre.services.world.npc_approach import approach
from wlre.services.world.navigation import Mesh, NavigationError
from wlre.services.world.movement import Movement


class NPCApproachTests(unittest.TestCase):
    def setUp(self):
        self.state=State(phase='world_ready')
        self.state.player.update(role_id=1,scene=12500,x=0,y=800)
        self.state.location.update(confirmed=dict(scene=12500,x=0,y=800,packet_number=1),
                                   confirmed_is_current=True)
        self.row=dict(index=7,npc_id=900,x=100,y=200,event_count=0)
        self.runtime=SimpleNamespace(stages={12500:dict(pos_x_ratio=2,pos_y_ratio=4)},
            npc_index=SimpleNamespace(for_scene=lambda _:[self.row]))
        p=patch('wlre.services.world.npc_approach.official_runtime',return_value=self.runtime)
        p.start();self.addCleanup(p.stop)
        self.command=dict(type='npc_approach',scene=12500,npc_index=7,npc_id=900)
        self.movement=Mock()

    def test_current_npc_ratios_and_nearby_point_instead_of_raw_coordinates(self):
        approach(self.state,self.movement,self.command,10)
        args=self.movement.start.call_args.args
        self.assertEqual(args[1:3],(100,800))
        self.assertEqual(args[3],10)
        self.assertLessEqual(math.dist(args[1:3],(200,800)),141)
        self.assertFalse(self.state.npc_dialogue.get('active'))
        self.assertEqual(self.state.player['x'],0)

    def test_unreachable_side_tries_a_different_nearby_reachable_point(self):
        self.movement.start.side_effect=[NavigationError('wall'),{}]
        approach(self.state,self.movement,self.command,10)
        self.assertEqual(self.movement.start.call_count,2)
        point=self.movement.start.call_args.args[1:3]
        self.assertLessEqual(math.dist(point,(200,800)),141)

    def test_all_nearby_candidates_unreachable_does_not_guess_a_teleport(self):
        self.movement.start.side_effect=NavigationError('not in mesh')
        with self.assertRaisesRegex(ProtocolError,'找不到'):
            approach(self.state,self.movement,self.command,10)
        self.assertEqual(self.state.player['scene'],12500)
        self.assertFalse(self.state.npc_dialogue.get('active'))

    def test_already_near_stops_without_starting_a_new_route(self):
        self.state.location['confirmed']['x']=150
        approach(self.state,self.movement,self.command,10)
        self.movement.start.assert_not_called()
        self.movement.stop.assert_called_once()

    def test_wrong_scene_identity_or_unknown_ratios_never_starts_movement(self):
        for change in ({'scene':60014},{'npc_id':901},{'npc_index':8}):
            with self.subTest(change=change),self.assertRaises(ProtocolError):
                approach(self.state,self.movement,dict(self.command,**change),10)
        self.runtime.stages[12500].pop('pos_x_ratio')
        with self.assertRaises(ProtocolError):approach(self.state,self.movement,self.command,10)
        self.movement.start.assert_not_called()

    def test_combat_or_event_gate_does_not_try_other_candidates(self):
        self.state.battle['active']=True
        with self.assertRaises(ProtocolError):approach(self.state,self.movement,self.command,10)
        self.movement.start.assert_not_called()
        self.state.battle['active']=False
        self.movement.start.side_effect=ProtocolError('活動阻擋')
        with self.assertRaisesRegex(ProtocolError,'活動阻擋'):
            approach(self.state,self.movement,self.command,10)
        self.assertEqual(self.movement.start.call_count,1)

    def test_command_dispatch_uses_real_navigation_and_emits_only_walk_packets(self):
        class Converter:
            def route(self,repository,scene,start,end,start_height=None):
                # Synthetic authorization isolates NPC orchestration from navigation acceptance.
                return {**repository.load(scene).route(start,end),
                        'can_send_packets':True,'live_movement_verified':True}
            def to_packet(self,scene,x,z):return x,z
        mesh=Mesh({'tiles':[{'vertices_b_int3':[[0,0,0],[1000,0,0],[1000,0,1000],[0,0,1000]],
                            'triangles':[[0,1,2],[0,2,3]]}]})
        mesh.scene_id='fixture'
        logic=SessionLogic();logic.world_acknowledged=True
        logic.roaming.enabled=True;self.state.roaming['enabled']=True
        logic.movement=Movement(Converter(),SimpleNamespace(load=lambda _:mesh))
        with patch('wlre.network.commands.time.monotonic',return_value=0):
            self.assertEqual(logic.command(self.command,self.state),[])
        self.assertTrue(logic.movement.active)
        self.assertFalse(logic.roaming.enabled)
        self.assertFalse(self.state.roaming['enabled'])
        self.assertEqual(self.state.local_movement['target']['x'],100)
        packets=logic.movement.tick(self.state,.2)
        self.assertTrue(packets)
        self.assertTrue(all((p.main,p.sub)==(6,1) for p in packets))
        self.assertFalse(self.state.npc_dialogue.get('active'))
        self.assertEqual(self.state.player['x'],0)

    def test_finished_reported_path_can_start_manual_dialogue_without_faking_server_fix(self):
        from wlre.network.npc_dialogue import request_npc
        self.test_command_dispatch_uses_real_navigation_and_emits_only_walk_packets()
        self.row['event_count']=1
        self.state.apply(dict(type='movement_request',x=100,y=800))
        self.assertEqual(self.state.local_movement['status'],'finished')
        self.assertFalse(self.state.location['confirmed_is_current'])
        with patch('wlre.network.npc_dialogue.NPCIndex',return_value=self.runtime.npc_index):
            packet,=request_npc(self.state,dict(self.command,confirmed=True,x=100,y=200))
        self.assertEqual((packet.main,packet.sub),(20,1))
        self.assertEqual(packet.payload,b'\x07\x00')
        self.assertFalse(self.state.location['confirmed_is_current'])
        self.assertEqual(self.state.location['confirmed']['x'],0)
        self.assertEqual(self.state.player['x'],0)

    def test_unfinished_stale_or_wrong_lineage_cannot_use_local_completion(self):
        from copy import deepcopy
        from wlre.services.world.npc_position import interaction_position_problem
        self.test_command_dispatch_uses_real_navigation_and_emits_only_walk_packets()
        self.state.apply(dict(type='movement_request',x=100,y=800))
        snapshot=self.state.snapshot()
        self.assertIsNone(interaction_position_problem(snapshot))
        for change in ({'status':'running'},{'status':'stopped'},{'role_id':2},
                       {'base_fix_packet':99},{'steps_sent':0},
                       {'catalog_token':('other','stale')},{'navigation_revision':99},
                       {'x':float('nan')},{'x':500}):
            bad=deepcopy(snapshot);bad['local_movement'].update(change)
            with self.subTest(change=change):self.assertIsNotNone(interaction_position_problem(bad))
        bad=deepcopy(snapshot);bad['navigation']['stale']=True
        self.assertIsNotNone(interaction_position_problem(bad))
        bad=deepcopy(snapshot);bad['local_movement']['catalog_token']=list(snapshot['local_movement']['catalog_token'])
        self.assertIsNone(interaction_position_problem(bad))
