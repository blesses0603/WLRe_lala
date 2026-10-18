"""Crafting grid and recipe detail split: public API and patch compatibility."""
import unittest
from unittest.mock import Mock, patch

from wlre.ui import crafting_browser as browser
from wlre.ui.crafting.catalog_grid import build_catalog_grid, render_catalog_grid
from wlre.ui.crafting.recipe_detail import build_recipe_detail, render_recipe_detail


class CraftingUiModuleBoundaryTests(unittest.TestCase):
    def test_original_crafting_browser_methods_still_exist(self):
        for name in ('refresh', 'refresh_grid', 'refresh_detail', 'change_page',
                     'pick_card', 'toggle_favorite', 'add', 'show_queue'):
            self.assertTrue(callable(getattr(browser.CraftingBrowser, name)))

    def test_grid_forwarder_uses_patchable_browser_collaborators(self):
        fake = object.__new__(browser.CraftingBrowser)
        with patch.object(browser, 'availability', new=Mock()) as availability:
            with patch.object(browser, 'confirmed_unlocked', new=Mock()) as unlocked:
                with patch.object(browser, 'render_catalog_grid') as render:
                    browser.CraftingBrowser.refresh_grid(fake, force=True)
        render.assert_called_once()
        args, kwargs = render.call_args
        self.assertIs(args[0], fake)
        self.assertTrue(args[1])
        self.assertIs(kwargs['availability'], availability)
        self.assertIs(kwargs['confirmed_unlocked'], unlocked)
        self.assertIs(kwargs['recipes'], browser.RECIPES)

    def test_detail_forwarder_uses_patchable_browser_collaborators(self):
        fake = object.__new__(browser.CraftingBrowser)
        with patch.object(browser, 'availability', new=Mock()) as availability:
            with patch.object(browser, 'recipe_plan', new=Mock()) as plan:
                with patch.object(browser, 'render_recipe_detail') as render:
                    browser.CraftingBrowser.refresh_detail(fake, force=True)
        render.assert_called_once()
        args, kwargs = render.call_args
        self.assertIs(args[0], fake)
        self.assertTrue(args[1])
        self.assertIs(kwargs['availability'], availability)
        self.assertIs(kwargs['recipe_plan'], plan)
        self.assertIs(kwargs['recipes'], browser.RECIPES)

    def test_separated_ui_builders_are_available(self):
        self.assertTrue(callable(build_catalog_grid))
        self.assertTrue(callable(render_catalog_grid))
        self.assertTrue(callable(build_recipe_detail))
        self.assertTrue(callable(render_recipe_detail))


if __name__ == '__main__':
    unittest.main()
