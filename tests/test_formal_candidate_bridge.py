"""Regression tests for removal of legacy candidate ZIP promotion."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tools.reviewed_1275_handoff import main
from wlre.services.world import runtime_1275

class LegacyPromotionRetirementTests(unittest.TestCase):
    def test_legacy_install_entrypoint_is_disabled(self):
        self.assertEqual(main(['--install']), 2)

    def test_formal_runtime_uses_pinned_source_without_candidate_bridge(self):
        source = SimpleNamespace(revision=1275)
        with patch.object(runtime_1275, 'active_runtime', return_value=source), \
             patch('wlre.services.items.crafting.activate_1275_recipes') as activate:
            ok, reason = runtime_1275.ready()
        self.assertTrue(ok)
        self.assertIn('協定仍須獨立驗收', reason)
        activate.assert_called_once_with(source)

    def test_unavailable_formal_runtime_does_not_activate_recipes(self):
        with patch.object(runtime_1275, 'active_runtime',
                          side_effect=runtime_1275.Runtime1275Unavailable('not ready')), \
             patch('wlre.services.items.crafting.activate_1275_recipes') as activate:
            ok, _ = runtime_1275.ready()
        self.assertFalse(ok)
        activate.assert_not_called()
