import math
import unittest
from tools.review_navigation_minimap_chain import local_to_packet
from wlre.services.world.smallmaps import Projection


class MinimapChainTests(unittest.TestCase):
    def test_fractional_local_coordinates_are_not_quantized(self):
        x,y=local_to_packet(.125,-.375)
        self.assertAlmostEqual(x,3000.75);self.assertAlmostEqual(y,3002.25)

    def test_matches_verified_texture_projection(self):
        projection=Projection(dict(map_width=6000,map_height=6000,small_offset_x=12,small_offset_y=12,offset_y=6000),(0,0,0))
        for u,v in ((0,0),(-191.6666666667,-319.1666666667),(100,-200)):
            expected=projection.pixel_to_packet(u+512,512-v)
            actual=local_to_packet(u,v)
            for a,b in zip(actual,expected):self.assertAlmostEqual(a,b)

    def test_invalid_inputs_refused(self):
        for u in (math.nan,math.inf,True,'1'):
            with self.assertRaises(ValueError):local_to_packet(u,0)
