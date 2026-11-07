import math
import unittest
from tools.review_navigation_click_pixels import target_bounds
from tools.review_navigation_minimap_chain import local_to_packet


class ClickPixelTests(unittest.TestCase):
    def test_independent_local_conversion(self):
        for u,v in ((0,0),(-200,300),(111.125,-222.5)):
            left,top,scale=43,-17,.275
            x=left+(u+512)*scale;y=top+(512-v)*scale
            bounds=target_bounds((x,x),(y,y),(left,left),(top,top),(scale,scale))
            for b,want in zip(bounds,local_to_packet(u,v)):
                self.assertAlmostEqual(b[0],want);self.assertEqual(b[0],b[1])

    def test_interval_contains_interior_and_crop_offset(self):
        bounds=target_bounds((757,761),(408,412),(672,678),(180,184),(.27,.28))
        for x in (757,759,761):
            for y in (408,410,412):
                for s in (.27,.275,.28):
                    point=target_bounds((x,x),(y,y),(675,675),(182,182),(s,s))
                    for axis in (0,1):
                        self.assertLessEqual(bounds[axis][0],point[axis][0])
                        self.assertGreaterEqual(bounds[axis][1],point[axis][1])

    def test_missing_or_bad_calibration_rejected(self):
        for scale in ((0,.3),(-1,-.5),(.3,.2),(math.nan,.3),(True,.3)):
            with self.assertRaises(ValueError):
                target_bounds((759,759),(410,410),(675,675),(182,182),scale)
