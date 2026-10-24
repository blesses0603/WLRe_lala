"""1275 login must never retain partially migrated 1262/1275 dictionaries."""
import unittest
from unittest.mock import patch

from wlre.services.world import runtime_1275
from wlre.services.items.catalog import CAT
from wlre.services.items.alchemy import META
from wlre.services.items.crafting import RECIPES
from wlre.core.inventory_updates import STACKABLE


class Runtime1275AtomicSwapTests(unittest.TestCase):
    def test_error_after_two_catalog_swaps_restores_all_shared_refs(self):
        shared = (RECIPES, CAT['skills'], CAT['keys'], CAT['items'],
                  CAT['npcs'], META, STACKABLE)
        original = [dict(value) for value in shared]
        refs = [id(value) for value in shared]

        def overwrite_recipes(_runtime):
            RECIPES.clear()
            RECIPES['99777'] = {'item_id': 99777}
            return 1

        def overwrite_skills(_runtime):
            CAT['skills'].clear()
            CAT['skills']['99777'] = {'ID': 99777}
            CAT['keys'].clear()
            CAT['keys']['99777'] = 99777
            return 1

        with patch.object(runtime_1275, 'active_runtime',
                          return_value=object()), \
             patch('wlre.services.items.crafting.activate_1275_recipes',
                   side_effect=overwrite_recipes), \
             patch('wlre.services.items.skills_1275.activate_1275_skills',
                   side_effect=overwrite_skills), \
             patch('wlre.services.items.itemdata_1275.activate_1275_items',
                   side_effect=ValueError('來源不完整')):
            ready, explanation = runtime_1275.ready()
        self.assertFalse(ready)
        self.assertIn('來源不完整', explanation)
        self.assertEqual([id(value) for value in shared], refs)
        self.assertEqual(list(shared), original)


if __name__ == '__main__':
    unittest.main()
