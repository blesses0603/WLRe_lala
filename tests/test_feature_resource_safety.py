"""P5 fail-closed resource contracts when only 1275 runtime evidence exists.

Retired navigation is excluded from runtime and packaged data.
Official runtime authorization remains independent from bundled storage.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from wlre.resource_manifest import REQUIRED_RESOURCES,data_files
from wlre.paths import RESOURCE_ROOT
from wlre.services.world.npc_catalog import NPCIndex
from wlre.services.world.portals import Portals


class ResourceSafetyContract(unittest.TestCase):
    def test_retired_navigation_is_not_required_or_shipped(self):
        from wlre.storage.resource_seed_manifest import RETIRED_NAVIGATION
        self.assertFalse(set(REQUIRED_RESOURCES) & RETIRED_NAVIGATION)
        self.assertFalse({p.name for p in data_files(RESOURCE_ROOT.parent,compact=True)} & RETIRED_NAVIGATION)

    def test_1275_npc_index_uses_verified_runtime_not_1262_fallback(self):
        scenes = {'10000': [{'index': 3, 'npc_id': 321,
                             'event_count': 0, 'x': 10, 'y': 11}]}
        runtime = SimpleNamespace(revision=1275, npc_index=SimpleNamespace(scenes=scenes))
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            index = NPCIndex()
        self.assertIsNone(index.path)
        self.assertEqual(index.for_scene(10000), scenes['10000'])
        self.assertIsNot(index.for_scene(10000)[0], scenes['10000'][0])

    def test_1275_portal_list_stays_closed_without_audited_triggers(self):
        runtime = SimpleNamespace(revision=1275, doors={'10000': [{'id': 1}, {'id': 2}]})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            portals = Portals()
        self.assertEqual(portals.data['source_revision'], 1275)
        self.assertEqual(portals.data['door_count'], 2)
        self.assertEqual(portals.for_scene(10000), [])
        self.assertEqual(portals.audit, {})
        with self.assertRaises(ValueError):
            portals.direct_target(
                {'scene': 10000, 'direct_eligible': False,
                 'direct_door_index': 1}, 10000)

    def test_1275_portal_runtime_unavailable_is_not_1262_fallback(self):
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                side_effect=ValueError('no verified bundle')):
            portals = Portals()
        self.assertEqual(portals.data['source_revision'], 1275)
        self.assertEqual(portals.data['door_count'], 0)
        self.assertEqual(portals.for_scene(10000), [])


if __name__ == '__main__':
    unittest.main()
