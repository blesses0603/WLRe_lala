"""Default NPC choices follow the independently verified runtime, not the seed."""
import unittest
from unittest.mock import patch
from npc_runtime_fixtures import runtime
from wlre.services.world.npc_interact import NPCInteractIndex
from wlre.services.world.npc_talk import load_catalog

class OfficialInteractRuntimeTests(unittest.TestCase):
    def test_current_choices_keep_order_and_unknown_text_disables_choice(self):
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=runtime()):
            index=NPCInteractIndex();talks=load_catalog()
            choice=index.choices(10000,1,talks)
            self.assertEqual(choice['title'],'fixture question')
            self.assertEqual([x['text'] for x in choice['options']],['fixture yes','fixture no'])
            self.assertIsNone(index.choices(10000,1,{}))
            row=index.get(10000,1);row['items'].clear()
            self.assertTrue(index.get(10000,1)['items'])
