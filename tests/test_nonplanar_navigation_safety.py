import unittest
from unittest.mock import Mock
from wlre.core.state import State
from wlre.network.wire import ProtocolError
from wlre.services.world.navigation import NavigationError
from wlre.services.world.navigation_preview import PreviewMesh
from wlre.services.world.movement import Movement


def slope():
    return dict(mesh=dict(tiles=[dict(vertices_b_int3=[[0,0,0],[1000,0,0],[0,1000,1000],[1000,1000,1000]],triangles=[[0,1,2],[1,3,2]],node_metadata=[[0,1],[0,1]])]),connections=[[(1,100,1)],[(0,100,2)]])


class NonplanarSafetyTests(unittest.TestCase):
    def test_sloped_preview_never_authorizes_movement(self):
        for mode in ('land','sky'):
            mesh=PreviewMesh(slope(),travel_mode=mode)
            route=mesh.route((100,100),(900,900))
            self.assertEqual(route['cost'],100)
            self.assertFalse(route['can_send_packets'])
            self.assertFalse(route['live_movement_verified'])
            self.assertNotEqual(route['points'][0][1],route['points'][-1][1])
            with self.assertRaisesRegex(NavigationError,'非水平'):
                mesh.route((100,100),(900,900),smooth=True)
            state=State();state.player=dict(role_id=1,scene=10001)
            state.confirm_location(10001,10,10,'S3-1')
            converter=Mock();converter.route.return_value=route
            movement=Movement(converter,Mock())
            with self.assertRaisesRegex(ProtocolError,'僅供預覽'):
                movement.start(state,90,90,0)
            self.assertFalse(movement.active)
            self.assertEqual(movement.tick(state,1),[])
            converter.to_packet.assert_not_called()
        with self.assertRaises(NavigationError):PreviewMesh(slope(),travel_mode='sea').route((100,100),(900,900))

    def test_overlapping_levels_require_observed_height(self):
        data=slope();tile=data['mesh']['tiles'][0]
        tile['vertices_b_int3']=[[0,0,0],[1000,0,0],[0,0,1000],[0,1000,0],[1000,1000,0],[0,1000,1000]]
        tile['triangles']=[[0,1,2],[3,4,5]];data['connections']=[[],[]]
        mesh=PreviewMesh(data)
        with self.assertRaisesRegex(NavigationError,'多個高度'):mesh.route((100,100),(200,200))
        route=mesh.route((100,100),(200,200),start_height=1000,end_height=1000)
        self.assertTrue(all(p[1]==1000 for p in route['points']))
        self.assertFalse(route['can_send_packets'])
        with self.assertRaises(NavigationError):mesh.route((100,100),(200,200),start_height=0,end_height=1000)
