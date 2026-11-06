import unittest
from wlre.services.world.navigation_funnel import smooth_corridor,covered
from wlre.services.world.navigation import NavigationError


class FunnelTests(unittest.TestCase):
    def test_square_straight_line_both_directions_and_windings(self):
        a,b,c,d=(0,0,0),(1000,0,0),(0,0,1000),(1000,0,1000)
        triangles=[(a,b,c),(b,d,c)];start=(100,0,100);end=(900,0,900)
        self.assertEqual(smooth_corridor(triangles,start,end),[start,end])
        self.assertEqual(smooth_corridor(list(reversed(triangles)),end,start),[end,start])
        self.assertEqual(smooth_corridor([tuple(reversed(t)) for t in triangles],start,end),[start,end])

    def test_nonplanar_and_disconnected_rejected(self):
        for triangles in ([((0,0,0),(1,1,0),(0,0,1))],
                          [((0,0,0),(1,0,0),(0,0,1)),((2,0,2),(3,0,2),(2,0,3))]):
            with self.assertRaises(NavigationError):smooth_corridor(triangles,(0,0,0),(1,0,1))

    def test_corridor_guard_detects_outside_and_gap(self):
        triangle=((0,0,0),(1,0,0),(0,0,1))
        self.assertFalse(covered((.1,0,.1),(2,0,2),[triangle]))
        self.assertFalse(covered((0,0,0),(3,0,0),[triangle,((2,0,0),(3,0,0),(2,0,1))]))
        with self.assertRaises(NavigationError):smooth_corridor([triangle],(.1,0,.1),(2,0,2))

    def test_corner_cannot_cut_through_missing_square(self):
        a,b,c,d,e,f=(0,0,0),(2,0,0),(0,0,1),(1,0,1),(2,0,1),(2,0,3)
        triangles=[(a,b,c),(b,d,c),(b,e,d),(d,e,f)]
        start=(.1,0,.5);end=(1.9,0,2.8)
        result=smooth_corridor(triangles,start,end)
        self.assertGreater(len(result),2)
        self.assertTrue(all(covered(x,y,triangles) for x,y in zip(result,result[1:])))


if __name__=='__main__':unittest.main()
