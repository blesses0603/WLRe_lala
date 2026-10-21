"""Official Eve 1262 index is now bundled and checked during tests."""
import unittest
from wlre.paths import RESOURCE_ROOT
from wlre.services.world.npc_interact import NAME, NPCInteractIndex


class RealEveInteractRegression(unittest.TestCase):
    def test_original_eve_index_or_safe_absence(self):
        path=RESOURCE_ROOT / NAME
        index=NPCInteractIndex()
        self.assertTrue(path.is_file(), '官方 Eve 1262 NPC 選項索引應隨版本內建')
        self.assertEqual(len(index.scenes),505)
        self.assertEqual(sum(len(s) for s in index.scenes.values()),1622)
        from wlre.services.world.npc_talk import load_catalog
        talks=load_catalog()
        example=index.choices(10000,1,talks)
        self.assertEqual(example['title'],'是否要進入小遊戲呢？')
        self.assertEqual([x['text'] for x in example['options']],['要。','不要。'])
        eligible=sum(index.choices(scene,ind,talks) is not None
                     for scene,rows in index.scenes.items() for ind in rows)
        self.assertEqual(eligible,1554)
