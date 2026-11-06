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


if __name__=='__main__':unittest.main()
