import unittest
from types import SimpleNamespace
from unittest.mock import patch
from wlre.services.world.obstacle_scope import house_scene,affects_navigation


class OfficialObstacleScopeTests(unittest.TestCase):
    def test_runtime_replaces_seed_and_does_not_cache_old_versions(self):
        runtime=SimpleNamespace(stages={15138:{}})
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=runtime), patch('wlre.services.world.obstacle_scope.known_scenes',side_effect=AssertionError('seed read')):
            self.assertFalse(house_scene(15138))
            self.assertFalse(affects_navigation(dict(geometry_scope='house'),15138))
            self.assertTrue(affects_navigation(dict(geometry_scope='scene'),15138))
            runtime.stages={15139:{}}
            self.assertIsNone(house_scene(15138))
            self.assertFalse(house_scene(15139))
            for scene in (10000,10298,10299,63501,65500):self.assertTrue(house_scene(scene))

    def test_failed_sync_and_unreviewed_instance_order_are_conservative(self):
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=None),patch('wlre.services.world.dynamic_bundle_runtime.dynamic_attempted',return_value=True),patch('wlre.services.world.obstacle_scope.known_scenes',side_effect=AssertionError('seed read')):
            self.assertIsNone(house_scene(12170))
            self.assertTrue(affects_navigation(dict(geometry_scope='house'),12170))
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=SimpleNamespace(stages={})):
            self.assertIsNone(house_scene(61501))
