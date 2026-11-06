from tools.review_navigation_awake_writes import inspect as awake_writes_probe
from tools.review_navigation_scene_settings import profile as scene_profile
from tools.review_navigation_scene_initialization import inspect as initialization_probe
from tools.review_navigation_constructor_defaults import run as defaults_probe
from tools.review_navigation_modifier_registration import oracle as modifier_registration_probe,validate_order
from tools.review_navigation_modifier_chain import oracle as chain_probe
from tools.review_navigation_funnel_apply import oracle as apply_probe
from tools.review_navigation_parts import oracle as parts_probe
from tools.review_navigation_dispatch import run as dispatch_probe
from tools.review_navigation_player_points import oracle as player_probe
from tools.review_navigation_modifier_order import run as modifier_order_probe
from tools.review_navigation_portals import oracle as portal_probe,validate_corridor
from tools.review_navigation_path_pipeline import oracle as pipeline_probe
from tools.review_navigation_prepare import oracle as prepare_probe,validate_inputs as validate_prepare
from tools.review_navigation_unwrap import oracle as unwrap_probe,validate_portals,compare_unfolding
from tools.review_navigation_funnel_wrapper import oracle as funnel_probe
from pathlib import Path
import tempfile
import math
import random
import struct
import unittest
from tools.review_navigation_search import oracle as search_probe,validate_graph as validate_search,compare as compare_search
from tools.review_navigation_path_state import oracle as path_probe,validate_fixture
from tools.review_navigation_nearest import oracle as nearest_probe,validate_query,reference_triangle
from tools.review_navigation_registration import inspect as registration_probe
from tools.review_navigation_groups import oracle as group_probe,validate_graph
from tools.review_navigation_vertices import oracle as vertex_probe,validate_inputs as validate_vertices,modeled_modf
from tools.review_navigation_bbtree import oracle as bbtree_probe,validate_inputs,validate_tree
from tools.review_navigation_areas import oracle as area_probe,validate_adjacency
from tools.review_navigation_traversal import oracle as traversal_probe
from tools.review_navigation_endpoints import run as endpoint_probe
from tools.review_navigation_rotation import from_to_oracle,multiply_oracle,validate_vector


class RotationOracleBoundaryTests(unittest.TestCase):
    def test_modifier_inventory_rejects_unknown_or_duplicate_entries(self):
        for order in ([],[0],[1],[0,1],[1,0]):validate_order(order)
        for order in (None,(0,1),[False],[2],[0,0],[0,1,0],['0']):
            with self.assertRaises(ValueError):validate_order(order)

    def test_expanded_search_bound_remains_finite(self):
        for n in (128,256):
            validate_search([[0,0,0]]*n,[[] for _ in range(n)],[1]*n,[0]*n,0,0,9,[0]*32,[[0,0,0],[0,0,0]])
        n=257
        with self.assertRaises(ValueError):
            validate_search([[0,0,0]]*n,[[] for _ in range(n)],[1]*n,[0]*n,0,0,9,[0]*32,[[0,0,0],[0,0,0]])

    def test_scene_settings_require_explicit_serialized_values(self):
        tree=dict(heuristic=2,heuristicScale=1.,maxNearestNodeDistance=100.,fullGetNearestSearch=0,scanOnStartup=0,m_Enabled=1,data=dict(cacheStartup=1))
        output=scene_profile(tree)
        self.assertEqual(output['heuristic'],2)
        self.assertEqual(output['heuristicScale'],1.)
        self.assertFalse(output['fullGetNearestSearch'])
        self.assertTrue(output['cacheStartup'])

    def test_scene_settings_reject_missing_or_invalid_data(self):
        tree=dict(heuristic=2,heuristicScale=1.,maxNearestNodeDistance=100.,fullGetNearestSearch=0,scanOnStartup=0,m_Enabled=1,data=dict(cacheStartup=1))
        for invalid in (None,{},dict(tree,data=None),dict(tree,heuristic=True),dict(tree,heuristic=4),dict(tree,heuristicScale=float('nan')),dict(tree,maxNearestNodeDistance=-1),dict(tree,fullGetNearestSearch=2),dict(tree,data={'cacheStartup':'true'})):
            with self.assertRaises(ValueError):scene_profile(invalid)
        for key in tree:
            missing=dict(tree);del missing[key]
            with self.assertRaises(ValueError):scene_profile(missing)

    def test_unknown_library_rejected_before_optional_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'unknown.so';path.write_bytes(b'not official code')
            for factory in (lambda p:awake_writes_probe(p,p,p),lambda p:initialization_probe(p,p),defaults_probe,modifier_registration_probe,chain_probe,lambda p:apply_probe(p,p),parts_probe,dispatch_probe,player_probe,modifier_order_probe,portal_probe,lambda p:pipeline_probe(p,p),prepare_probe,lambda p:unwrap_probe(p,p),lambda p:funnel_probe(p,p),search_probe,path_probe,from_to_oracle,multiply_oracle,endpoint_probe,traversal_probe,area_probe,bbtree_probe,group_probe,vertex_probe,nearest_probe,lambda path:registration_probe(path,path)):
                with self.assertRaisesRegex(ValueError,'digest'):factory(path)
            with path.open('wb') as output:output.truncate(96*1024*1024+1)
            with self.assertRaisesRegex(ValueError,'size limit'):from_to_oracle(path)

    def test_invalid_and_unbounded_inputs(self):
        for values in ((float('nan'),0,0),(float('inf'),0,0),(1000001,0,0),(1,2)):
            with self.assertRaises(ValueError):validate_vector(values,3)
        validate_vector((0,0,0),3)


class HierarchyInputTests(unittest.TestCase):
    def test_invalid_hierarchy_never_reaches_native_memory(self):
        for adjacency in ([],[[1],[]],[[],[2],[]],[[],[1]],[[],[2,2],[1]],[[],[True]], [[],[[1]]], [[] for _ in range(258)]):
            with self.assertRaises(ValueError):validate_adjacency(adjacency)
        validate_adjacency([[],[2],[1],[]])


class BBTreeInputTests(unittest.TestCase):
    def test_invalid_geometry_rejected(self):
        for rects,centers in (([],[]),([(0,0,1,1)],[]), ([(1,0,0,1)],[(0,0,0)]),
                             ([(0,0,1,1)],[(True,0,0)]), ([(0,0,1,1)]*513,[(0,0,0)]*513)):
            with self.assertRaises(ValueError):validate_inputs(rects,centers)
        validate_inputs([(-1,-1,1,1)],[(0,0,0)])
        validate_inputs([(10000000,0,10000000,0)],[(9999989,0,0)])

    def test_tree_reference_and_bounds_failures(self):
        rects=[(0,0,1,1)]
        good=dict(boxes=[[0,0,1,1,0,-1,-1]],leaf_references=[0,None,None,None],root=0)
        validate_tree(good,rects)
        for bad in (dict(good,leaf_references=[0,0,None,None]),
                    dict(good,boxes=[[0,0,2,1,0,-1,-1]]),
                    dict(good,boxes=[[0,0,1,1,-1,0,0]]),
                    dict(good,boxes=good['boxes']*2)):
            with self.assertRaises(ValueError):validate_tree(bad,rects)


class NativeInitializationInputTests(unittest.TestCase):
    def test_group_input_bounds(self):
        for adjacency,walkable in (([],[]),([[]],[False]),([[]],[1]),([[1]],[True]),
                                  ([[True],[]],[True,True]),([[1,1],[]],[True,True]),
                                  ([[]]*257,[True]*257)):
            with self.assertRaises(ValueError):validate_graph(adjacency,walkable)
        validate_graph([[1],[]],[True,False])

    def test_vertex_input_bounds(self):
        for vertices,indices in (([],[0,0,0]),([[0,0,0]],[0,0,1]),
                                 ([[0,0,0]],[0,False,0]),([[10000001,0,0]],[0,0,0]),
                                 ([[0,float('nan'),0]],[0,0,0]),([[0,0,0]]*4097,[0,0,0])):
            with self.assertRaises(ValueError):validate_vertices(vertices,indices)
        validate_vertices([[0,-1,2]],[0,0,0])


class ModfModelTests(unittest.TestCase):
    def test_finite_contract_against_host_libm_including_signed_zero(self):
        values=[0.0,-0.0,.5,-.5,1.5,-1.5,2.5,-2.5,100000000.0,-100000000.0]
        rng=random.Random(1296)
        values.extend(struct.unpack('<f',struct.pack('<f',rng.uniform(-100000000,100000000)))[0] for _ in range(1000))
        for value in values:
            self.assertEqual(struct.pack('<2d',*modeled_modf(value)),struct.pack('<2d',*math.modf(value)))
        for value in (float('inf'),float('-inf'),float('nan'),100000001.0):
            with self.assertRaises(ValueError):modeled_modf(value)

    def test_multiple_group_input_ceiling(self):
        validate_graph([[]]*512,[True]*512,multiple=True)
        with self.assertRaises(ValueError):validate_graph([[]]*513,[True]*513,multiple=True)


class ModfBitBoundaryTests(unittest.TestCase):
    def test_binary64_mask_reference_at_exponent_boundaries(self):
        # Independent IEEE-754 truncation, matching the finite-domain behavior
        # of the inspected AOSP Bionic implementation; not a device binary test.
        values=[0.0,-0.0]
        for exponent in (-1074,-1022,-1,0,19,20,26):
            value=math.ldexp(1.0,exponent)
            for near in (math.nextafter(value,0.0),value,math.nextafter(value,math.inf)):
                values.extend((near,-near))
        for value in values:
            bits=struct.unpack('<Q',struct.pack('<d',value))[0]
            exponent=((bits>>52)&2047)-1023
            mask=(1<<63) if exponent<0 else (~((1<<(52-exponent))-1)&((1<<64)-1))
            integer=struct.unpack('<d',struct.pack('<Q',bits&mask))[0]
            fraction=math.copysign(abs(value-integer),value)
            self.assertEqual(struct.pack('<2d',*modeled_modf(value)),struct.pack('<2d',fraction,integer))


class NativeNearestInputTests(unittest.TestCase):
    def test_invalid_nearest_geometry_and_queries(self):
        vertices=[[0,0,0],[1000,0,0],[0,0,1000]]
        for faces,point in (([],[0,0,0]),([[0,0,1]],[0,0,0]),([[0,1,2]]*513,[0,0,0]),
                            ([[0,1,2]],[float('nan'),0,0]),([[0,1,2]],[1001,0,0])):
            with self.assertRaises(ValueError):validate_query(vertices,faces,point,(0,0,0))
        validate_query(vertices,[[0,1,2]],(-.1,2,3),(0,0,0))

    def test_independent_closest_point_reference(self):
        tri=[[0,0,0],[10,0,0],[0,0,10]]
        self.assertEqual(reference_triangle(tri,[2,3,2]),[2,0,2])
        self.assertEqual(reference_triangle(tri,[20,3,20]),[5,0,5])
        self.assertEqual(reference_triangle(tri,[-2,3,-2]),[0,0,0])


class OuterNearestComparisonTests(unittest.TestCase):
    def test_reference_rejects_excluded_and_non_nearest_nodes(self):
        from tools.review_navigation_outer import compare
        vertices=[[0,0,0],[10000,0,0],[0,0,10000]];faces=[[0,1,2]]
        compare(vertices,faces,[2,3,2],dict(node=0,point=[2,0,2]),[True])
        compare(vertices,faces,[2,3,2],dict(node=None,point=None),[False])
        with self.assertRaises(ValueError):compare(vertices,faces,[2,3,2],dict(node=0,point=[2,0,2]),[False])
        with self.assertRaises(ValueError):compare(vertices,faces,[2,3,2],dict(node=0,point=[5,0,5]),[True])


class PathStateInputTests(unittest.TestCase):
    def test_cycles_and_invalid_references_rejected(self):
        for parents in ([0], [1,0], [None,2], [None,True], [None,-1]):
            with self.assertRaises(ValueError):
                validate_fixture([[0,0]]*len(parents),parents,[[0,0,0]]*len(parents),0)
        validate_fixture([[0,0]]*3,[None,0,1],[[0,-100,100]]*3,2)

    def test_cost_position_and_size_bounds(self):
        for costs,parents,positions,end in (
            ([],[],[],0), ([[0,0]]*257,[None]*257,[[0,0,0]]*257,0),
            ([[True,0]],[None],[[0,0,0]],0),
            ([[100000001,0]],[None],[[0,0,0]],0),
            ([[0,-1]],[None],[[0,0,0]],0),
            ([[0,0]],[None],[[10000001,0,0]],0),
            ([[0,0]],[None],[[float('nan'),0,0]],0),
            ([[0,0]],[None],[[0,0,0]],True)):
            with self.assertRaises(ValueError):validate_fixture(costs,parents,positions,end)


class NativeSearchBoundaryTests(unittest.TestCase):
    def fixture(self):
        return dict(positions=[[0,0,0],[100,0,0]],connections=[[[1,10]],[]],
                    flags=[1,1],penalties=[0,0],start=0,end=1,tag_mask=9,
                    tag_penalties=[0]*32,points=[[0,0,0],[100,0,0]])

    def test_invalid_graph_state_and_native_overflow_rejected(self):
        good=self.fixture();validate_search(**good)
        for change in (dict(start=True),dict(end=2),dict(flags=[1,1<<24]),
                       dict(connections=[[[1,10],[1,10]],[]]),
                       dict(connections=[[[0,10]],[]]),dict(connections=[[[1,-1]],[]]),
                       dict(positions=[[0,0,0],[0,0,0]]),dict(penalties=[0,100001]),
                       dict(tag_mask=-1),dict(tag_penalties=[0]*31),
                       dict(points=[[float('nan'),0,0],[100,0,0]]),
                       dict(positions=[[0,0,0],[1,0,0]],connections=[[[1,100000]],[]],
                            points=[[1000000,0,0],[-1000000,0,0]])):
            with self.assertRaises(ValueError):validate_search(**dict(good,**change))

    def test_independent_cost_check_rejects_wrong_routes_and_false_success(self):
        fixture=self.fixture()
        good=dict(status='complete_prepared_search',total_cost=10,path_nodes=[0,1],
                  vector_path=[[0.,0.,0.],[struct.unpack('<f',struct.pack('<f',100*struct.unpack('<f',struct.pack('<f',.001))[0]))[0],0.,0.]])
        compare_search(fixture,good)
        for bad in (dict(good,total_cost=11),dict(good,path_nodes=[0,0,1]),
                    dict(good,vector_path=[[0,0,0],[0,0,0]]),
                    dict(status='native_no_route_error_boundary')):
            with self.assertRaises(ValueError):compare_search(fixture,bad)
        fixture['flags'][1]=0
        compare_search(fixture,dict(status='native_no_route_error_boundary'))
        with self.assertRaises(ValueError):compare_search(fixture,good)


class NativePreparationInputTests(unittest.TestCase):
    def test_invalid_mesh_bookkeeping_stops_before_native_state(self):
        good=dict(vertices=[[0,0,0],[1000,0,0],[0,0,1000]],faces=[[0,1,2]],
                  connections=[[]],flags=[1],penalties=[0],start_point=[0,1,0],end_point=[0,0,0],tag_mask=9)
        validate_prepare(**good)
        for change in (dict(flags=[True]),dict(flags=[1<<24]),dict(connections=[[[1,1]]]),
                       dict(penalties=[-1]),dict(tag_mask=-1),dict(end_point=[float('nan'),0,0]),
                       dict(faces=[[0,0,0]])):
            with self.assertRaises(ValueError):validate_prepare(**dict(good,**change))

    def test_empty_walkable_multiple_group_state_is_permitted(self):
        validate_graph([[],[]],[False,False],multiple=True)
        with self.assertRaises(ValueError):validate_graph([[]],[False])


class NativePortalInputTests(unittest.TestCase):
    def test_invalid_or_unbounded_portals(self):
        for left,right in (([],[]),([[0,0,0]],[[0,0,0]]),
                           ([[0,0,0]]*129,[[0,0,0]]*129),
                           ([[0,0,0],[1,0,0]],[[0,0,0],[2,0,0]]),
                           ([[float('nan'),0,0]]*2,[[float('nan'),0,0]]*2),
                           ([[1001,0,0]]*2,[[1001,0,0]]*2)):
            with self.assertRaises(ValueError):validate_portals(left,right)

    def test_local_unfolded_geometry_check_detects_distortion(self):
        left=[[0,0,0],[1,0,1],[3,0,0]];right=[[0,0,0],[1,0,-1],[3,0,0]]
        good=dict(left=[[0,0],[1,1],[3,0]],right=[[0,0],[1,-1],[3,0]])
        compare_unfolding(left,right,good)
        with self.assertRaises(ValueError):compare_unfolding(left,right,dict(good,right=[[0,0],[1,-2],[3,0]]))


class NativePortalEdgeTests(unittest.TestCase):
    def test_bad_edges_or_route_are_never_guessed(self):
        good=dict(vertices=[[0,0,0],[1000,0,0],[0,500,1000],[1000,500,1000]],
                  faces=[[0,1,2],[1,3,2]],connections=[[[1,10,1]],[[0,10,2]]],route=[0,1])
        validate_corridor(**good)
        for change in (dict(route=[0,0]),dict(route=[True,1]),dict(route=[0,2]),
                       dict(connections=[[[1,10,0]],[[0,10,2]]]),
                       dict(connections=[[[1,10,255]],[[0,10,2]]]),
                       dict(connections=[[],[[0,10,2]]]),
                       dict(connections=[[[1,1<<28,1]],[[0,10,2]]]),
                       dict(faces=[[0,0,1],[1,3,2]])):
            with self.assertRaises(ValueError):validate_corridor(**dict(good,**change))

    def test_single_node_corridor_has_no_invented_portals(self):
        validate_corridor([[0,0,0],[1000,0,0],[0,0,1000]],[[0,1,2]],[[]],[0])
