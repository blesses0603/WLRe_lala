import unittest
from tools.review_navigation_m12050_postprocess import endpoint_assessment


class EndpointAssessmentTests(unittest.TestCase):
    def test_corrected_end_is_not_arrival(self):
        result=endpoint_assessment([0,2,0],[3,6,0])
        self.assertEqual(result['adjustment_3d'],5)
        self.assertEqual(result['adjustment_horizontal'],3)
        self.assertEqual(result['adjustment_vertical'],4)
        self.assertIsNone(result['requested_destination_reached'])
        self.assertFalse(result['can_send_packets'])

    def test_exact_end_does_not_prove_live_arrival(self):
        result=endpoint_assessment([1,2,3],[1,2,3])
        self.assertEqual(result['adjustment_3d'],0)
        self.assertIsNone(result['requested_destination_reached'])
        self.assertFalse(result['live_movement_verified'])

    def test_invalid_xyz_rejected(self):
        for point in ([1,2], [0,float('nan'),0], [0,float('inf'),0]):
            with self.assertRaises(ValueError):endpoint_assessment(point,[0,0,0])
