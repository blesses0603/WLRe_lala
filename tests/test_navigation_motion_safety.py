import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from tools.review_navigation_motion_matrix import motion
from wlre.services.world.navigation_motion_safety import check_preview,exact_waypoint_step
from wlre.services.world.movement import Movement
from wlre.core.state import State
from wlre.network.wire import ProtocolError


def fixture():
    a,b,c,d=(0,0,0),(800,0,0),(800,0,200),(0,0,200)
    e,f,g,h=(1000,0,0),(1000,0,200),(800,0,1000),(1000,0,1000)
    faces=[(a,b,c),(a,c,d),(b,e,f),(b,f,c),(c,f,h),(c,h,g)]
    mesh=SimpleNamespace(faces=faces,walkable=set(range(6)),adjacency={0:{1:0,3:0},1:{0:0},2:{3:0},3:{0:0,2:0,4:0},4:{3:0,5:0},5:{4:0}})
    points=[(100,0,100),(900,0,200),(900,0,900)]
    return mesh,dict(points=points,faces=[1,0,3,4,5],can_send_packets=False)


class MotionSafetyTests(unittest.TestCase):
    def check(self,mesh,route,segments):return check_preview(mesh,route,segments,catalog_key='test',expected_catalog_key='test')

    def test_exact_path_fallback_and_no_packet_authority(self):
        mesh,route=fixture();segments=list(zip(route['points'],route['points'][1:]))
        result=self.check(mesh,route,segments)
        self.assertEqual(result['status'],'geometry_preview_only')
        self.assertTrue(result['fallback']['geometry_contained'])
        for candidate in (result,result['fallback']):
            state=State();state.player=dict(role_id=1,scene=58001);state.confirm_location(58001,10,10,'S3-1')
            converter=Mock();converter.route.return_value=candidate
            movement=Movement(converter,Mock())
            with self.assertRaisesRegex(ProtocolError,'僅供預覽'):movement.start(state,90,90,0)
            self.assertEqual(movement.tick(state,1),[]);converter.to_packet.assert_not_called()

    def test_early_switch_gets_exact_waypoint_candidate(self):
        mesh,route=fixture();segments=motion(route['points'],60)['segments']
        result=self.check(mesh,route,segments)
        self.assertEqual(result['modeled_motion_containment'],'rejected')
        self.assertTrue(result['fallback']['geometry_contained'])
        self.assertFalse(result['can_send_packets'])

    def test_exact_step_preserves_corners_at_large_or_small_steps(self):
        mesh,route=fixture();points=route['points']
        for distance in (3500/120,3500/30,10000):
            pos=points[0];index=0
            for _ in range(100):
                step=exact_waypoint_step(points,index,pos,distance)
                from wlre.services.world.navigation_funnel import covered
                self.assertTrue(all(covered(a,b,mesh.faces) for a,b in step['segments']))
                self.assertFalse(step['can_send_packets'])
                pos,index=step['position'],step['index']
                if step['done']:break
            else:self.fail('Bounded path did not complete')
            self.assertEqual(pos,tuple(points[-1]))
        with self.assertRaises(ValueError):exact_waypoint_step(points,0,(400,0,400),10)

    def test_unsafe_shortcut_rejected_and_stale_version_fails(self):
        mesh,route=fixture()
        route['points']=[(100,0,100),(900,0,900)]
        result=self.check(mesh,route,[(route['points'][0],route['points'][1])])
        self.assertEqual(result['status'],'rejected');self.assertIsNone(result['fallback'])
        self.assertEqual(check_preview(mesh,route,[],catalog_key='old',expected_catalog_key='new')['reason'],'catalog_mismatch')

    def test_nonplanar_and_forbidden_face_rejected(self):
        mesh,route=fixture();route['points'][1]=(900,1,100)
        self.assertEqual(self.check(mesh,route,[])['reason'],'nonplanar')
        mesh,route=fixture();mesh.walkable.remove(1)
        self.assertEqual(self.check(mesh,route,[])['reason'],'forbidden_faces')
