import unittest
from unittest.mock import Mock
from wlre.core.state import State
from wlre.network.wire import ProtocolError
from wlre.services.world.movement import Movement


class MovementAuthorityTests(unittest.TestCase):
    def test_unverified_or_missing_authority_never_starts_or_sends(self):
        for flags in ({},{'can_send_packets':True},{'live_movement_verified':True},
                      {'can_send_packets':1,'live_movement_verified':True},
                      {'can_send_packets':True,'live_movement_verified':1},
                      {'can_send_packets':False,'live_movement_verified':True}):
            with self.subTest(flags=flags):
                state=State();state.player=dict(role_id=1,scene=58001)
                state.confirm_location(58001,10,10,'S3-1')
                converter=Mock();converter.route.return_value=dict(points=[(10,0,10),(90,0,90)],**flags)
                movement=Movement(converter,Mock())
                with self.assertRaisesRegex(ProtocolError,'僅供預覽'):movement.start(state,90,90,0)
                self.assertFalse(movement.active)
                self.assertEqual(movement.tick(state,1),[])
                converter.to_packet.assert_not_called()
                self.assertFalse(state.local_movement)

    def test_explicit_synthetic_authority_retains_locomotion_unit_contract(self):
        state=State();state.player=dict(role_id=1,scene=58001)
        state.confirm_location(58001,10,10,'S3-1')
        converter=Mock();converter.route.return_value=dict(points=[(10,0,10),(90,0,90)],can_send_packets=True,live_movement_verified=True)
        converter.to_packet.side_effect=lambda scene,x,z:(x,z)
        movement=Movement(converter,Mock());movement.start(state,90,90,0)
        self.assertTrue(movement.active)
        self.assertTrue(movement.tick(state,1))
