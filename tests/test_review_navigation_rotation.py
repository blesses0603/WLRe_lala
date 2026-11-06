from pathlib import Path
import tempfile
import math
import random
import struct
import unittest
from tools.review_navigation_registration import inspect as registration_probe
from tools.review_navigation_groups import oracle as group_probe,validate_graph
from tools.review_navigation_vertices import oracle as vertex_probe,validate_inputs as validate_vertices,modeled_modf
from tools.review_navigation_bbtree import oracle as bbtree_probe,validate_inputs,validate_tree
from tools.review_navigation_areas import oracle as area_probe,validate_adjacency
from tools.review_navigation_traversal import oracle as traversal_probe
from tools.review_navigation_endpoints import run as endpoint_probe
from tools.review_navigation_rotation import from_to_oracle,multiply_oracle,validate_vector


class RotationOracleBoundaryTests(unittest.TestCase):
    def test_unknown_library_rejected_before_optional_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'unknown.so';path.write_bytes(b'not official code')
            for factory in (from_to_oracle,multiply_oracle,endpoint_probe,traversal_probe,area_probe,bbtree_probe,group_probe,vertex_probe,lambda path:registration_probe(path,path)):
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
