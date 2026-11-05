"""P5 fail-closed resource contracts when only 1275 runtime evidence exists.

Logical resource names remain required database entries after source removal.
Official runtime authorization remains independent from bundled storage.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from wlre.resource_manifest import REQUIRED_RESOURCES
from wlre.services.world.npc_catalog import NPCIndex
from wlre.services.world.portals import Portals


class ResourceSafetyContract(unittest.TestCase):
    def test_legacy_logical_entries_remain_required_in_database(self):
        names = set(REQUIRED_RESOURCES)
        self.assertEqual(len(names), len(REQUIRED_RESOURCES))
        for name in (
            'instance_catalog_1262.json', 'smallmaps.zip',
            'navigation_data.zip', 'portals.json',
            'npc_battle_talk_1262.json.gz',
        ):
            with self.subTest(resource=name):
                self.assertIn(name, names)

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
