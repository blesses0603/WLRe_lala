"""Retired candidate modules must not be importable."""
import importlib.util
import unittest


class RetiredCandidateTests(unittest.TestCase):
    def test_legacy_candidate_module_is_absent(self):
        self.assertIsNone(importlib.util.find_spec(
            "wlre.services.world.catalog_compatibility"))
