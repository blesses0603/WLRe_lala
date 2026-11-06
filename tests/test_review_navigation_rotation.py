from pathlib import Path
import tempfile
import unittest
from tools.review_navigation_bbtree import oracle as bbtree_probe,validate_inputs,validate_tree
from tools.review_navigation_areas import oracle as area_probe,validate_adjacency
from tools.review_navigation_traversal import oracle as traversal_probe
from tools.review_navigation_endpoints import run as endpoint_probe
from tools.review_navigation_rotation import from_to_oracle,multiply_oracle,validate_vector


class RotationOracleBoundaryTests(unittest.TestCase):
    def test_unknown_library_rejected_before_optional_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'unknown.so';path.write_bytes(b'not official code')
            for factory in (from_to_oracle,multiply_oracle,endpoint_probe,traversal_probe,area_probe,bbtree_probe):
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
        for rects,centers in (([],[]),([(0,0,1,1)],[]), ([(0,0,1,1)],[(2,0,0)]),
                             ([(0,0,1,1)],[(True,0,0)]), ([(0,0,1,1)]*513,[(0,0,0)]*513)):
            with self.assertRaises(ValueError):validate_inputs(rects,centers)
        validate_inputs([(-1,-1,1,1)],[(0,0,0)])

    def test_tree_reference_and_bounds_failures(self):
        rects=[(0,0,1,1)]
        good=dict(boxes=[[0,0,1,1,0,-1,-1]],leaf_references=[0,None,None,None],root=0)
        validate_tree(good,rects)
        for bad in (dict(good,leaf_references=[0,0,None,None]),
                    dict(good,boxes=[[0,0,2,1,0,-1,-1]]),
                    dict(good,boxes=[[0,0,1,1,-1,0,0]]),
                    dict(good,boxes=good['boxes']*2)):
            with self.assertRaises(ValueError):validate_tree(bad,rects)
