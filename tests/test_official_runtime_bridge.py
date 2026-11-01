"""Official-only runtime bridge must never downgrade unknown revisions."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from wlre.services.world.catalog_source_policy import verified_runtime_for_official


class OfficialRuntimeBridgeTests(unittest.TestCase):
    def setUp(self):
        for name, value in (('_active', None), ('_attempted', False)):
            state = patch('wlre.services.world.dynamic_bundle_runtime.' + name, value)
            state.start()
            self.addCleanup(state.stop)
        self.remote = {
            'resource_path': '1.3.21', 'official_exe_version': '1.3.0',
            'newer_official_client': False,
            'packages': {'DataPackage': {'remote': '1286'},
                         'MainPackage': {'remote': '1284'}},
        }
        self.pinned = {'official_game_exe_version': '1.3.0', 'packages': {
            'DataPackage': {'manifest': '1275'},
            'MainPackage': {'manifest': '1275'}}}

    def test_new_official_versions_do_not_fallback_to_old_runtime(self):
        with patch('wlre.services.resource_compatibility.load_supported_resources',
                   return_value=self.pinned), patch(
            'wlre.services.world.dynamic_bundle_runtime.activate_for_official',
            side_effect=ValueError('unavailable')) as runtime:
            with self.assertRaises(ValueError):
                verified_runtime_for_official('npc', self.remote)
            runtime.assert_called_once_with(self.remote)

    def test_exact_pinned_pair_may_use_verified_runtime(self):
        self.remote['packages'] = {
            'DataPackage': {'remote': '1275'},
            'MainPackage': {'remote': '1275'}}
        expected = SimpleNamespace(revision=1275)
        with patch('wlre.services.resource_compatibility.load_supported_resources',
                   return_value=self.pinned), patch(
            'wlre.services.world.dynamic_bundle_runtime.activate_for_official',
            return_value=expected) as runtime:
            self.assertIs(verified_runtime_for_official('npc', self.remote), expected)
            runtime.assert_called_once_with(self.remote)

    def test_invalid_feature_and_client_rejected(self):
        with self.assertRaises(ValueError):
            verified_runtime_for_official('social', self.remote)
        from wlre.services.items.crafting import RECIPES
        saved = dict(RECIPES)
        self.addCleanup(lambda: (RECIPES.clear(), RECIPES.update(saved)))
        self.remote['newer_official_client'] = True
        expected=SimpleNamespace(revision=1286)
        self.remote['official_exe_version']='1.4.0'
        with patch('wlre.services.world.dynamic_bundle_runtime.activate_for_official',return_value=expected):
            self.assertIs(verified_runtime_for_official('npc',self.remote),expected)


if __name__ == '__main__':
    unittest.main()
