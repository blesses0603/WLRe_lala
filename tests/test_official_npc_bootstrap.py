"""Migrated NPC readers must not consult historical bundled DB entries."""
from unittest.mock import patch
import unittest
from wlre.services.world.npc_catalog import NPCIndex
from wlre.services.world.npc_interact import NPCInteractIndex
from wlre.services.world.npc_talk import load_catalog
from wlre.services.world.npc_localization import load_text_data
from wlre.services.world.runtime_1275 import Runtime1275Unavailable
from npc_runtime_fixtures import runtime

class OfficialNPCBootstrapTests(unittest.TestCase):
    def test_missing_or_failed_runtime_never_reads_legacy_database(self):
        with patch('wlre.storage.bundled_database.load_legacy_resource',side_effect=AssertionError('legacy fallback')), patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=None), patch('wlre.services.world.runtime_1275.baseline_revision',return_value='1262'):
            for attempted in (False,True):
                with patch('wlre.services.world.dynamic_bundle_runtime.dynamic_attempted',return_value=attempted):
                    for reader in (NPCIndex,NPCInteractIndex,load_catalog,load_text_data):
                        with self.subTest(attempted=attempted,reader=reader.__name__):
                            with self.assertRaises(Runtime1275Unavailable):reader()

    def test_new_runtime_replaces_all_public_readers(self):
        first=runtime();second=runtime()
        second.npc_index.scenes['10000'][0]['npc_id']=999
        second.interact_index.scenes[10000][1]['link_number']=9
        second.talks[10001]='new dialogue';second.texts[1]='new localization'
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=first):
            self.assertEqual(NPCIndex().for_scene(10000)[0]['npc_id'],321)
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=second):
            self.assertEqual(NPCIndex().for_scene(10000)[0]['npc_id'],999)
            self.assertEqual(NPCInteractIndex().get(10000,1)['link_number'],9)
            self.assertEqual(load_catalog()[10001],'new dialogue')
            self.assertEqual(load_text_data()[1],'new localization')
