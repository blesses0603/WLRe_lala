import math
import unittest
from wlre.services.world.navigation_surface_3d import segment_on_surface


class Surface3DTests(unittest.TestCase):
    def test_slope_requires_correct_height_not_just_xz(self):
        tri=[[(0,0,0),(1,0,0),(0,1,1)]]
        self.assertTrue(segment_on_surface((.1,.1,.1),(.2,.2,.2),tri))
        self.assertFalse(segment_on_surface((.1,0,.1),(.2,0,.2),tri))

    def test_fold_requires_portal_waypoint(self):
        a,b,c,d=(0,0,0),(1,0,0),(1,0,1),(0,0,1)
        e,f=(2,1,0),(2,1,1)
        tris=[(a,b,c),(a,c,d),(b,e,f),(b,f,c)]
        start,middle,end=(.5,0,.5),(1,0,.5),(1.5,.5,.5)
        self.assertFalse(segment_on_surface(start,end,tris))
        self.assertTrue(segment_on_surface(start,middle,tris))
        self.assertTrue(segment_on_surface(middle,end,tris))

    def test_overlapping_floors_do_not_bridge(self):
        tris=[[(0,h,0),(1,h,0),(0,h,1)] for h in (0,1)]
        self.assertFalse(segment_on_surface((.2,0,.2),(.2,1,.2),tris))
        self.assertTrue(segment_on_surface((.2,1,.2),(.3,1,.2),tris))

    def test_tolerance_does_not_flatten_one_millith_height_step(self):
        tri=[[(0,0,0),(1,0,0),(0,0,1)]]
        self.assertTrue(segment_on_surface((.1,1e-6,.1),(.2,1e-6,.2),tri))
        self.assertFalse(segment_on_surface((.1,.001,.1),(.2,.001,.2),tri))
        for tolerance in (0,.001,math.nan):
            with self.assertRaises(ValueError):segment_on_surface((0,0,0),(0,0,0),tri,plane_tolerance=tolerance)

    def test_lateral_tolerance_is_world_scaled_on_tiny_triangles(self):
        tri=[[(0,0,0),(.001,0,0),(0,0,.001)]]
        self.assertTrue(segment_on_surface((-5e-6,0,.0001),(-5e-6,0,.0002),tri))
        self.assertFalse(segment_on_surface((-.001,0,.0001),(-.001,0,.0002),tri))

    def test_degenerate_and_nonfinite_refused(self):
        with self.assertRaises(ValueError):segment_on_surface((0,0,0),(1,0,0),[[(0,0,0)]*3])
        with self.assertRaises(ValueError):segment_on_surface((math.inf,0,0),(1,0,0),[[(0,0,0),(1,0,0),(0,1,1)]])
