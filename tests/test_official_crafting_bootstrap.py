"""Cold start, failed refresh and user favorites without historical recipes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from wlre.services.items.crafting import RECIPES, activate_dynamic_recipes
from wlre.services.items.crafting_browser_model import Favorites
from types import SimpleNamespace

class OfficialCraftingBootstrapTests(unittest.TestCase):
    def test_cold_import_does_not_load_recipe_seed(self):
        code = "from wlre.services.items.crafting import RECIPES; assert RECIPES == {}"
        subprocess.run([sys.executable, '-c', code], check=True, timeout=30)

    def test_failed_publish_preserves_previous_recipe_dictionary(self):
        with patch.dict(RECIPES, {'1': {'item_id': 1}}, clear=True):
            runtime = SimpleNamespace(catalog_identity='verified-fixture', can_send_packets=False,
                                      recipes={2: {}}, items={})
            with self.assertRaises(ValueError): activate_dynamic_recipes(runtime)
            self.assertEqual(RECIPES, {'1': {'item_id': 1}})

    def test_cold_favorites_survive_later_write_with_partial_new_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'favorites.json'
            path.write_text(json.dumps({'version':1,'items':['100',200]}))
            with patch.dict(RECIPES, {}, clear=True):
                self.assertEqual(Favorites(path).ids,[100,200])
            with patch.dict(RECIPES, {'300':{}}, clear=True):
                Favorites(path).toggle(300)
            self.assertEqual(json.loads(path.read_text())['items'],[100,200,300])
