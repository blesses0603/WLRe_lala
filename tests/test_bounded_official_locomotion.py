import math
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from wlre.core.state import State
from wlre.services.world.navigation_preview import PreviewMesh,PreviewRepository
from wlre.services.world.official_movement import OfficialMovementAdapter
from wlre.services.world.movement import Movement
from wlre.services.world.roaming import Roaming
from wlre.network.wire import ProtocolError

KEY='b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6'

class BoundedOfficialLocomotionTests(unittest.TestCase):
    def setUp(self):
        self.runtime=SimpleNamespace(catalog_identity=SimpleNamespace(key=KEY),stages={10001:dict(model_id=10001,map_height=1000)})
        result=dict(mesh=dict(tiles=[dict(vertices_b_int3=[[0,0,0],[10000,0,0],[0,0,10000],[10000,0,10000]],
                    triangles=[[0,1,2],[1,3,2]],node_metadata=[[0,1],[0,1]])]),connections=[[[1,1,1]],[[0,1,2]]])
        self.mesh=PreviewMesh(result);self.mesh.scene_id='M10001'
        self.enterContext(patch.object(PreviewRepository,'load',return_value=(self.mesh,[0,0,0])))
        self.adapter=OfficialMovementAdapter(runtime_getter=lambda:self.runtime)
        self.movement=Movement(self.adapter,self.adapter)
        self.state=State();self.state.player=dict(role_id=1,scene=10001)
        self.state.confirm_location(10001,500,500,'S3-1')
        self.state.navigation.update(scene=10001,stale=False)
        self.transport=Mock()

    def run_tick(self,now):
        packets=self.movement.tick(self.state,now)
        for p in packets:self.transport(p)
        return packets

    def test_four_point_cycle_uses_official_contract_without_false_live_claim(self):
        roaming=Roaming(self.adapter);roaming.start(self.state,self.movement)
        previous=(500,500);count=0
        for tick in range(200):
            now=tick*.2;roaming.tick(self.state,self.movement,now)
            for p in self.run_tick(now):
                xy=struct.unpack('<HH',p.payload)
                self.assertLessEqual(math.dist(previous,xy),70.000001)
                self.assertLessEqual(math.dist((500,500),xy),300.000001)
                self.assertNotEqual(xy,previous);previous=xy;count+=1
            if self.state.roaming['goals_started']>=5:break
        self.assertGreaterEqual(self.state.roaming['goals_started'],5)
        self.assertGreater(count,0)
        self.assertFalse(self.state.local_movement['live_movement_verified'])
        self.assertFalse(self.state.local_movement['runtime_collision_verified'])
        self.assertFalse(self.movement.converter._route['can_send_packets'])
        self.assertFalse(self.movement.converter._route['live_movement_verified'])

    def test_tick_is_bounded_no_replay_or_catchup_burst(self):
        self.movement.start(self.state,700,500,0)
        self.assertEqual(self.run_tick(.19),[])
        self.assertLessEqual(len(self.run_tick(.2)),1)
        before=self.transport.call_count
        self.assertEqual(self.run_tick(.2),[])
        self.assertEqual(self.transport.call_count,before)
        self.assertLessEqual(len(self.run_tick(1.2)),1)
        self.assertEqual(self.run_tick(100),[])
        self.assertFalse(self.movement.active)
        self.assertTrue(self.movement.execution_interrupted)

    def test_actual_server_correction_and_stop_interrupt_without_auto_retry(self):
        for event in ({'type':'position_snapshot','role_id':1,'scene':10001,'x':501,'y':500},
                      {'type':'movement_stop'}, {'type':'walk','role_id':1,'x':999,'y':999}):
            with self.subTest(event=event):
                roaming=Roaming(self.adapter);roaming.start(self.state,self.movement)
                roaming.tick(self.state,self.movement,0)
                self.movement.observe(event,self.state)
                self.assertEqual(self.run_tick(.2),[])
                started=self.state.roaming['goals_started'];roaming.tick(self.state,self.movement,.3)
                self.assertEqual(self.state.roaming['goals_started'],started)
                self.assertEqual(self.state.roaming['status'],'blocked')

    def test_version_navigation_and_battle_changes_stop_before_packet(self):
        self.movement.start(self.state,700,500,0)
        self.state.navigation['stale']=True
        self.assertEqual(self.run_tick(.2),[])
        self.state.navigation['stale']=False
        self.movement.start(self.state,700,500,1)
        self.runtime.stages[10001]['map_height']=999
        self.assertEqual(self.run_tick(1.2),[])
        self.runtime.stages[10001]['map_height']=1000
        self.movement.start(self.state,700,500,2)
        self.state.battle['active']=True
        self.assertEqual(self.run_tick(2.2),[])

    def test_bounds_distance_and_outside_mesh_fail_before_transport(self):
        for kwargs in ({'bounds':(500,500,50)}, {'max_distance':100}):
            with self.assertRaises(ValueError):self.movement.start(self.state,700,500,0,**kwargs)
        with self.assertRaises(ValueError):self.movement.start(self.state,1200,500,0)
        self.transport.assert_not_called();self.assertFalse(self.movement.active)

    def test_four_point_preflight_rejects_edge_and_preserves_disabled_state(self):
        self.state.confirm_location(10001,10,10,'S3-1')
        roaming=Roaming(self.adapter)
        with self.assertRaises(ValueError):roaming.start(self.state,self.movement)
        self.assertFalse(roaming.enabled);self.transport.assert_not_called()

    def test_server_stop_after_locally_finished_leg_still_requires_restart(self):
        self.movement.start(self.state,510,500,0)
        for i in range(1,10):self.run_tick(i*.2)
        self.assertFalse(self.movement.active)
        self.movement.observe({'type':'movement_stop'},self.state)
        self.assertTrue(self.movement.execution_interrupted)

    def test_speed_mutation_does_not_emit(self):
        self.movement.start(self.state,700,500,0);self.movement.speed=4000
        self.assertEqual(self.run_tick(.2),[]);self.transport.assert_not_called()

    def test_unknown_position_and_invalid_bounds_stop(self):
        with self.assertRaises(ValueError):
            self.movement.start(self.state,700,500,0,bounds=(500,500,float('nan')))
        self.movement.start(self.state,700,500,0)
        self.state.local_movement=None
        self.assertEqual(self.run_tick(.2),[])
        self.assertTrue(self.movement.execution_interrupted)

    def test_new_authoritative_fix_stops_even_before_observe_callback(self):
        self.movement.start(self.state,700,500,0)
        self.state.packet_count+=1
        self.state.confirm_location(10001,501,500,'S3-1')
        self.assertEqual(self.run_tick(.2),[])
        self.assertTrue(self.movement.execution_interrupted)

    def test_scheduler_outbound_state_roundtrip_uses_mock_transport_only(self):
        from wlre.network.protocol import decode_outbound_movement
        roaming=Roaming(self.adapter);roaming.start(self.state,self.movement)
        for tick in range(200):
            now=tick*.2;roaming.tick(self.state,self.movement,now)
            for packet in self.run_tick(now):
                event=decode_outbound_movement(packet);event['sync_mode']=True
                self.state.apply(event)
            if self.state.roaming['goals_started']>=5:break
        self.assertGreaterEqual(self.state.roaming['goals_started'],5)
        self.assertGreater(self.transport.call_count,0)
        self.assertFalse(self.state.local_movement['live_movement_verified'])

    def test_decoded_server_stop_and_correction_packets_stop_execution(self):
        from wlre.network.protocol import decode
        from wlre.network.wire import Packet
        for packet in (Packet(6,2,b'\0'),Packet(7,1,struct.pack('<IHHH',1,10001,501,500))):
            with self.subTest(main=packet.main):
                self.state=State();self.state.player=dict(role_id=1,scene=10001)
                self.state.confirm_location(10001,500,500,'S3-1')
                self.state.navigation.update(scene=10001,stale=False)
                self.movement.start(self.state,700,500,0)
                event=decode(packet,local_role_id=1)
                self.state.apply(event);self.movement.observe(event,self.state)
                self.assertEqual(self.run_tick(.2),[])
                self.assertTrue(self.movement.execution_interrupted)
