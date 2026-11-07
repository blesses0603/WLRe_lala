import math
import unittest
from tools.review_navigation_motion_matrix import motion,departure_sample
from tools.review_navigation_corner_following import follow
from wlre.services.world.navigation_funnel import covered


class MotionMatrixTests(unittest.TestCase):
    def test_segment_model_matches_reviewed_bangkok_follower(self):
        points=[(4836,5154),(3680,3980),(3010,3870),(1850,4915)]
        nav=[(x*10,0,y*10) for x,y in points]
        for fps in (30,60,120):
            expected,_=follow(points,fps,40);actual=motion(nav,fps)
            self.assertTrue(actual['complete'])
            self.assertLess(math.dist([actual['stop'][0]/10,actual['stop'][2]/10],expected[-1]),1e-7)
            self.assertLessEqual(math.dist(actual['stop'],nav[-1]),400)
            for a,b in zip(actual['segments'],actual['segments'][1:]):self.assertEqual(a[1],b[0])

    def test_early_switch_can_leave_allowed_l_corridor(self):
        def rect(x0,z0,x1,z1):
            a,b,c,d=(x0,0,z0),(x1,0,z0),(x1,0,z1),(x0,0,z1)
            return [(a,b,c),(a,c,d)]
        triangles=rect(-100,-100,1100,100)+rect(900,-100,1100,1100)
        points=[(0,0,0),(1000,0,0),(1000,0,1000)]
        self.assertTrue(all(covered(a,b,triangles) for a,b in zip(points,points[1:])))
        result=motion(points,60)
        unsafe=[(a,b) for a,b in result['segments'] if not covered(a,b,triangles)]
        self.assertTrue(unsafe)
        self.assertGreater(departure_sample(unsafe[0],triangles),1)

    def test_unreviewed_inputs_and_timeout(self):
        for points in ([(0,0,0),(1,1,0)],[(0,0,0),(math.nan,0,0)]):
            with self.assertRaises(ValueError):motion(points,60)
        result=motion([(0,0,0),(1e9,0,0)],30)
        self.assertFalse(result['complete']);self.assertEqual(result['frames'],5400)
