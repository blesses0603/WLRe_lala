import unittest
from tools.review_navigation_mode_matrix import reference_graph, explain_forbidden, audit_model


class ModeMatrixTests(unittest.TestCase):
    def decoded(self):
        return dict(mesh={'tiles':[dict(vertices_b_int3=[[0,0,0],[1000,0,0],[1000,0,1000],[0,0,1000],[500,0,500]],
            triangles=[[0,1,4],[1,2,4],[2,3,4],[3,0,4]],
            node_metadata=[[0,1|(tag<<19)] for tag in range(4)])]},
            connections=[[[1,10,0],[3,11,0]],[[0,13,0],[2,14,0]],[[1,17,0],[3,18,0]],[[0,19,0],[2,20,0]]])

    def test_all_modes_and_disabled_walkability(self):
        data=self.decoded()
        for mode,expected in [('land',{0,3}),('sea',{2}),('sky',{0,1,2,3})]:
            self.assertEqual(reference_graph(data,mode).walkable,expected)
            self.assertEqual(audit_model(data,1,mode)['unreachable'],0)
        data['mesh']['tiles'][0]['node_metadata'][2][1]&=~1
        self.assertEqual(audit_model(data,1,'sea')['status'],'no_eligible_nodes')

    def test_tag_and_missing_arc_are_distinct_causes(self):
        data=self.decoded();data['connections'][0]=[]
        reasons=explain_forbidden(data,[1],[[0,1]],'land')
        self.assertEqual(reasons,{'travel_tag_excluded':1,'serialized_arc_missing':1})

    def test_unknown_tag_is_not_sky_permission(self):
        data=self.decoded();data['mesh']['tiles'][0]['node_metadata'][0][1]=1|(4<<19)
        self.assertNotIn(0,reference_graph(data,'sky').walkable)
