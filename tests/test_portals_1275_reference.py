"""1275 topology may be listed in UI but must never cause movement or C20-8."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from wlre.services.world.portals import Portals
from wlre.services.world.portal_policy import allowed_rows, destination_problem


class Portals1275ReferenceTests(unittest.TestCase):
    def test_verified_stage_link_is_visible_but_never_activatable(self):
        runtime=SimpleNamespace(
            doors={10000:[{'index':1}]},
            stages={10000:{'name_id':1,'is_open':True},
                    12050:{'name_id':2,'is_open':True}},
            texts={1:'起點',2:'目的地'},
            topology={'binary_links':{},'eve_links':{
                10000:[{'destination':12050,'source_scaled_xy':[100,200]}]}})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                   'wlre.services.world.runtime_1275.active_runtime',
                   return_value=runtime):
            p=Portals()
        self.assertEqual(p.data['source_revision'],1275)
        self.assertEqual(p.data['door_count'],1)
        rows=allowed_rows(p,10000,None,recovery=True)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['destination'],12050)
        self.assertFalse(rows[0]['direct_eligible'])
        self.assertFalse(rows[0]['direct_door_index'])
        self.assertIn('尚未驗證', destination_problem(rows[0]))
        with self.assertRaises(ValueError):
            p.direct_target(rows[0],10000)
        with self.assertRaises(ValueError):
            p.target(rows[0],10000)

    def test_unverified_1275_destination_rejected_even_with_image(self):
        link={'source_revision':1275,'destination':12050}
        class AnyMap:
            def has_image(self,dest):
                raise AssertionError('1275 safety must not rely on map image')
        self.assertIn('尚未驗證', destination_problem(link,AnyMap()))


if __name__=='__main__':
    unittest.main()
