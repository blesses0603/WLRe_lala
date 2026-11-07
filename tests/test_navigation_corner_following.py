import unittest
from tools.review_navigation_corner_following import follow, distance_to_polyline


class CornerFollowingTests(unittest.TestCase):
    def test_strict_threshold_and_no_overshoot(self):
        trace,switches=follow([(0,0),(40,0),(40,100)],30,40)
        self.assertAlmostEqual(trace[1][0],350/30)
        self.assertEqual(trace[1][1],0)
        self.assertEqual(switches[0]['position'],trace[1])
        self.assertGreater(distance_to_polyline((40,0),trace),0)
        self.assertLessEqual(trace[-1][1],100)

    def test_fixed_profile_bounds(self):
        with self.assertRaises(ValueError):follow([(0,0),(100,0)],50,40)
        with self.assertRaises(ValueError):follow([(0,0),(100,0)],30,41)
        with self.assertRaises(ValueError):follow([(0,0),(100000,0)],30,40)

    def test_distance_metric(self):
        self.assertEqual(distance_to_polyline((1,3),[(0,0),(2,0)]),3)
        self.assertEqual(distance_to_polyline((3,0),[(0,0),(2,0)]),1)
