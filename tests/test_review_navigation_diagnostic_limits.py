"""Research budget gates must reject unsupported configurations before VM load."""
import unittest
from tools.review_navigation_nearest import oracle


class DiagnosticBudgetTests(unittest.TestCase):
    def test_unsupported_caps_fail_before_loading_binary(self):
        for value in (True,0,-1,200001,400001,1000000,400000.0,None):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'Unreviewed diagnostic instruction budget'):
                oracle('/nonexistent/official-library',_outer_instruction_limit=value)

    def test_extended_budget_cannot_enter_path_pipeline(self):
        with self.assertRaisesRegex(ValueError,'not for path pipelines'):
            oracle('/nonexistent/official-library',_search_state=True,_outer_instruction_limit=400000)


class ExtendedSearchCapacityTests(unittest.TestCase):
    def test_844_requires_explicit_isolated_capacity(self):
        from tools.review_navigation_search import validate_graph,oracle
        n=844;positions=[[i,0,0] for i in range(n)]
        args=(positions,[[] for _ in range(n)],[1]*n,[0]*n,0,n-1,9,[0]*32,[positions[0],positions[-1]])
        with self.assertRaises(ValueError):validate_graph(*args)
        validate_graph(*args,capacity=1024)
        with self.assertRaises(ValueError):validate_graph(*args,capacity=2048)
        with self.assertRaises(ValueError):oracle('must-not-open',capacity=1024,_existing_state={})

    def test_1025_rejected_even_with_extended_capacity(self):
        from tools.review_navigation_search import validate_graph
        n=1025;p=[[i,0,0] for i in range(n)]
        with self.assertRaises(ValueError):validate_graph(p,[[] for _ in p],[1]*n,[0]*n,0,n-1,9,[0]*32,[p[0],p[-1]],capacity=1024)


class ExtendedNearestInitializationTests(unittest.TestCase):
    def test_limits_fail_before_binary_loading(self):
        from tools.review_navigation_nearest import oracle as nearest,validate_query
        from tools.review_navigation_bbtree import oracle as tree,validate_inputs
        from tools.review_navigation_groups import oracle as groups,validate_graph
        with self.assertRaises(ValueError):nearest('must-not-open',capacity=1024,_search_state=True)
        for factory in (nearest,tree):
            with self.assertRaises(ValueError):factory('must-not-open',capacity=2048)
        with self.assertRaises(ValueError):groups('must-not-open',capacity=1024)
        vertices=[[0,0,0],[1000,0,0],[0,0,1000]];faces=[[0,1,2]]*844
        with self.assertRaises(ValueError):validate_query(vertices,faces,[0,0,0],[0,0,0])
        validate_query(vertices,faces,[0,0,0],[0,0,0],capacity=1024)
        validate_inputs([[0,0,1,1]]*1024,[[0,0,0]]*1024,capacity=1024)
        with self.assertRaises(ValueError):validate_inputs([[0,0,1,1]]*1025,[[0,0,0]]*1025,capacity=1024)
        validate_graph([[] for _ in range(1024)],[True]*1024,multiple=True,capacity=1024)


if __name__=='__main__':unittest.main()
