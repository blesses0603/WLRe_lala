"""Complete 1262 NPC source archive must be identical across Windows/macOS/Linux."""
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from wlre.paths import RESOURCE_ROOT
from wlre.storage.full_resource_seed import read_config
from wlre.services.world.npc_asset_install import ASSETS
from wlre.services.world.npc_talk import load_catalog, dialogue_text
from wlre.services.world.npc_localization import load_text_data, load_battle_talk, battle_lines
from wlre.resource_manifest import REQUIRED_RESOURCES


class BundledNPCResourceTests(unittest.TestCase):
    def test_exact_source_sha256_and_sizes(self):
        from wlre.storage.resource_seed_manifest import RETIRED_RESOURCES
        for filename,(digest,size,source,source_hash,count) in ASSETS.items():
            if filename in RETIRED_RESOURCES:
                self.assertNotIn(filename,REQUIRED_RESOURCES)
                continue
            with self.subTest(filename=filename):
                path=RESOURCE_ROOT/filename
                self.assertIn(filename,REQUIRED_RESOURCES)
                self.assertFalse(path.is_file(),filename)
                raw=read_config(filename, root=RESOURCE_ROOT)
                self.assertEqual(len(raw),size)
                self.assertEqual(hashlib.sha256(raw).hexdigest(),digest)

    def test_talk_and_text_use_separate_runtime_namespaces(self):
        from npc_runtime_fixtures import runtime
        value=runtime();value.talks={1:'dialogue'};value.texts={1:'localization'}
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=value):
            talks=load_catalog();texts=load_text_data()
            self.assertEqual(dialogue_text(talks,1),'dialogue')
            self.assertEqual(texts[1],'localization')
            talks[1]='changed';texts[1]='changed'
            self.assertEqual(load_catalog()[1],'dialogue')
            self.assertEqual(load_text_data()[1],'localization')
        self.assertIsNone(dialogue_text(talks,True))
        battle=load_battle_talk()
        self.assertEqual(len(battle),16)
        self.assertEqual(sum(len(v) for v in battle.values()),94)

    def test_modified_default_text_is_blocked_before_display(self):
        with TemporaryDirectory() as temp:
            directory=Path(temp)
            (directory/'npc_talk_1262.json.gz').write_bytes(b'fake')
            (directory/'npc_text_1262.json.gz').write_bytes(b'fake')
            with patch('wlre.services.world.npc_talk.RESOURCE_ROOT',directory), patch(
                    'wlre.services.world.runtime_1275.baseline_revision',
                    return_value='1262'), patch(
                    'wlre.storage.bundled_database.load_legacy_resource',
                    return_value=b'fake'):
                with self.assertRaises(ValueError):load_catalog()
            with patch('wlre.services.world.npc_localization.RESOURCE_ROOT',directory), patch(
                    'wlre.storage.bundled_database.load_legacy_resource',
                    return_value=b'fake'):
                with self.assertRaises(ValueError):load_text_data()


# These historical tests verify bundled 1262 fixtures explicitly. Production
# LaLa now defaults to 1275, with no implicit source fallback.
from unittest.mock import patch as _legacy_patch
_legacy_context = None


def setUpModule():
    global _legacy_context
    _legacy_context = _legacy_patch(
        'wlre.services.world.runtime_1275.baseline_revision', return_value='1262')
    _legacy_context.start()
    from wlre.services.world.npc_item_data import item_catalog
    item_catalog.cache_clear()


def tearDownModule():
    from wlre.services.world.npc_item_data import item_catalog
    item_catalog.cache_clear()
    _legacy_context.stop()

