import unittest
from types import SimpleNamespace
from tools.navigation_same_geometry_control import independent_cost, compare_algorithms


class SameGeometryTests(unittest.TestCase):
    def test_label_correction_revisits_cheaper_late_path(self):
        graph=SimpleNamespace(serialized_connections=[[(1,100,0),(2,1,0)],[(3,1,0)],[(1,1,0)],[]],
                              adjacency=[{1:None,2:None},{3:None},{1:None},{}],metadata=[[0,1]]*4)
        self.assertEqual(independent_cost(graph,0,3)['cost'],3)
        with self.assertRaises(ValueError):independent_cost(graph,0,3,max_relaxations=1)
        self.assertIsNone(independent_cost(graph,3,0)['cost'])

    def decoded(self):
        return dict(origin=[0,0,0],mesh={'tiles':[dict(vertices_b_int3=[[0,0,0],[1000,0,0],[0,0,1000],[1000,0,1000]],
            triangles=[[0,1,2],[1,3,2]],node_metadata=[[0,1],[7,1]])]},connections=[[[1,123,0]],[[0,999,0]]])

    def test_same_geometry_does_not_claim_historical_equivalence(self):
        r=compare_algorithms(self.decoded(),{'map_height':100},(10,90),(90,10),travel_mode='land')
        self.assertEqual(r['official']['cost'],130)
        self.assertTrue(r['unfiltered_algorithm']['allowed_by_preview_graph'])
        self.assertFalse(r['historical_parity_verified'])
        self.assertFalse(r['can_send_packets'])
        self.assertNotIn('points',r)

    def test_unfiltered_connection_is_not_official_authority(self):
        data=self.decoded();data['connections']=[[],[]]
        r=compare_algorithms(data,{'map_height':100},(10,90),(90,10),travel_mode='land')
        self.assertEqual(r['official']['status'],'no_route')
        self.assertEqual(r['unfiltered_algorithm']['status'],'ready')
        self.assertEqual(r['unfiltered_algorithm']['forbidden_edges'],[[0,1]])
