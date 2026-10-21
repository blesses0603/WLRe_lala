"""Complete 1262 NPC source archive must be identical across Windows/macOS/Linux."""
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from wlre.paths import RESOURCE_ROOT
from wlre.services.world.npc_asset_install import ASSETS
from wlre.services.world.npc_talk import load_catalog, dialogue_text
from wlre.services.world.npc_localization import load_text_data, load_battle_talk, battle_lines
from wlre.resource_manifest import REQUIRED_RESOURCES


class BundledNPCResourceTests(unittest.TestCase):
    def test_exact_source_sha256_and_sizes(self):
        for filename,(digest,size,source,source_hash,count) in ASSETS.items():
            with self.subTest(filename=filename):
                path=RESOURCE_ROOT/filename
                self.assertIn(filename,REQUIRED_RESOURCES)
                self.assertTrue(path.is_file(),filename)
                raw=path.read_bytes()
                self.assertEqual(len(raw),size)
                self.assertEqual(hashlib.sha256(raw).hexdigest(),digest)

    def test_real_talk_and_text_are_not_mixed(self):
        talks=load_catalog()
        texts=load_text_data()
        battle=load_battle_talk()
        self.assertEqual(len(talks),29873)
        self.assertEqual(len(texts),39901)
        self.assertEqual(len(battle),16)
        self.assertEqual(sum(len(v) for v in battle.values()),94)
        self.assertEqual(dialogue_text(talks,10001),'要。')
        self.assertEqual(texts[1],'確定')
        self.assertIsNone(dialogue_text(talks,True))
        for group in battle.values():
            for row in group:
                self.assertIn(row['text_id'],texts)

    def test_modified_default_text_is_blocked_before_display(self):
        with TemporaryDirectory() as temp:
            directory=Path(temp)
            (directory/'npc_talk_1262.json.gz').write_bytes(b'fake')
            (directory/'npc_text_1262.json.gz').write_bytes(b'fake')
            with patch('wlre.services.world.npc_talk.RESOURCE_ROOT',directory):
                with self.assertRaises(ValueError):load_catalog()
            with patch('wlre.services.world.npc_localization.RESOURCE_ROOT',directory):
                with self.assertRaises(ValueError):load_text_data()
