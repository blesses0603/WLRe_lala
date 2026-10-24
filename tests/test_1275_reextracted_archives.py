"""Regression checks for locally re-extracted official 1275 archives.

Game Bundle bytes are deliberately not committed to the public repository.
Set LALA_1275_DATA_CATALOG and LALA_1275_EVE_INDEX to run a full
source-backed integration check from an explicitly supplied local archive.
"""
import os
import unittest
from pathlib import Path

from wlre.services.world.game_data_1275 import (
    MANIFEST_SHA256, REEXTRACTED_MANIFEST_SHA256, verify_archive)
from wlre.services.world.npc_1275_eve import FILES, REEXTRACTED_FILES, read_verified_zip
from wlre.services.world.preview_1275 import load_preview


class Reextracted1275Pins(unittest.TestCase):
    def test_both_manifest_pins_are_independent_and_complete(self):
        self.assertEqual(MANIFEST_SHA256,
            'a069027a05aa332c57048164a61b839896c12926bfe93dfd2b52daf5c58d0dc4')
        self.assertEqual(REEXTRACTED_MANIFEST_SHA256,
            '1522aa78e158b7daba5593d44c5dcc44373bae1be950b65e93da1ac22584da1f')
        self.assertNotEqual(MANIFEST_SHA256, REEXTRACTED_MANIFEST_SHA256)

    def test_reextracted_eve_indexes_have_distinct_pinned_signatures(self):
        self.assertEqual(set(FILES), set(REEXTRACTED_FILES))
        self.assertEqual(REEXTRACTED_FILES['npc_event_index_1275.json.gz'],
            (111933, '3bdd3a70a31dce4624b4f5704f9b0df9e1b82d24343eb7aae83e1763826896b1'))
        self.assertEqual(REEXTRACTED_FILES['npc_interact_1275.json.gz'],
            (20061, 'ec76150325ce24b8d5247b040025b1a20678722245e98c720ec9a470c4b6122e'))
        for name, (size, digest) in REEXTRACTED_FILES.items():
            self.assertGreater(size, 0)
            self.assertEqual(len(digest), 64)
            self.assertNotEqual((size, digest), FILES[name][1:3])

    @unittest.skipUnless(os.environ.get('LALA_1275_DATA_CATALOG')
                         and os.environ.get('LALA_1275_EVE_INDEX'),
                         'Real official 1275 archive paths not provided')
    def test_full_original_1275_bundle_data_reaches_runtime(self):
        data = Path(os.environ['LALA_1275_DATA_CATALOG'])
        eve = Path(os.environ['LALA_1275_EVE_INDEX'])
        verification = verify_archive(data)
        self.assertEqual(verification['revision'], 1275)
        self.assertEqual(verification['verified_files'], 163)
        self.assertEqual(verification['manifest_sha256'],
                         REEXTRACTED_MANIFEST_SHA256)
        indexed = read_verified_zip(eve)
        self.assertEqual(indexed['npc_event_index_1275.json.gz']['npc_count'], 10975)
        self.assertEqual(indexed['npc_interact_1275.json.gz']['interact_count'], 1634)
        runtime = load_preview(data, eve)
        self.assertEqual(runtime.revision, 1275)
        self.assertEqual(len(runtime.items), 11304)
        # Actual 1275 ItemData_C must match all 11,304 index entries,
        # including gear, item restriction and alchemy metadata.
        self.assertEqual(runtime.item_catalog['source_revision'], 1275)
        self.assertEqual(len(runtime.item_catalog['items']), 11304)
        self.assertEqual(len(runtime.item_catalog['alchemy']), 11304)
        self.assertEqual(runtime.item_catalog['items']['32297']['name'],
                         '果粒蘋果汁')
        self.assertEqual(runtime.item_catalog['items']['32297']['attributes'][0]['value'], 500)
        self.assertEqual(runtime.item_catalog['items']['39852']['name'],
                         '藍莓優格壁紙')
        self.assertEqual(runtime.item_catalog['items']['39854']['name'],
                         '藍莓優格地磚')
        self.assertEqual(len(runtime.texts), 39947)
        self.assertEqual(len(runtime.talks), 29890)
        self.assertEqual(len(runtime.recipes), 1032)
        self.assertEqual(len(runtime.stages), 1337)
        # Real 1275 StageMapData, DoorLinkData and UTF-16 EveDoorLinks
        # source-backed topology. It is not permission to move or teleport.
        source = runtime.topology
        self.assertEqual(source['source_revision'], 1275)
        self.assertEqual(source['counts'], {
            'stages': 1337, 'markers': 4092,
            'binary_links': 85, 'eve_links': 2374})
        self.assertFalse(source['can_send_packets'])
        self.assertFalse(source['navmesh_verified'])
        self.assertEqual(runtime.stages[12910]['map_width'], 10080)
        self.assertEqual(runtime.stages[12910]['map_height'], 10080)
        self.assertEqual(runtime.stages[13216]['pos_x_ratio'], 2)
        self.assertEqual(runtime.stages[13216]['pos_y_ratio'], 4)
        self.assertEqual(runtime.world_position(10000, 1000, 1500),
                         (10.0, 19.0))
        plan = runtime.plan_stages(10000, 12050)
        self.assertEqual(plan['stages'], [10000, 12050])
        self.assertFalse(plan['can_send_packets'])
        self.assertEqual(len(runtime.skill_catalog['skills']), 1593)
        self.assertEqual(len(runtime.expedition_catalog['tasks']), 260)
        self.assertEqual(len(runtime.expedition_catalog['npcs']), 7561)
        self.assertEqual(runtime.expedition_catalog['npcs']['14230']['name'],
                         '艾琳')
        self.assertEqual(runtime.expedition_catalog['npcs']['14230']['skills'],
                         [25033, 11172, 0, 0, 0])
        self.assertEqual(len(runtime.dungeon_records), 30)
        # New scene models are present in the official 1275 scene bundles,
        # but marked unavailable in the static ScenesData_C table.
        # Never infer that assets alone authorize live navigation or portals.
        self.assertTrue(runtime.stages[12910]['is_open'])
        self.assertEqual(runtime.stages[12910]['model_id'], 12910)
        for model_id in range(13216, 13228):
            with self.subTest(model_id=model_id):
                row = runtime.stages[model_id]
                self.assertEqual(row['model_id'], model_id)
                self.assertFalse(row['is_open'])
                self.assertIn(row['name_id'], runtime.texts)
        self.assertFalse(runtime.can_send_packets)


if __name__ == '__main__':
    unittest.main()
