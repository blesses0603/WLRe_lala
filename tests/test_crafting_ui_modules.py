"""Preserve public crafting UI references after extracting helper modules."""
import unittest

from wlre.ui.crafting_browser import CraftingBrowser, ItemIcons, ICON_MAP
from wlre.ui.crafting.item_icons import ItemIcons as CachedItemIcons, ICON_MAP as CACHED_MAP
from wlre.ui.crafting.queue_view import CraftingQueueMixin


class CraftingModulesTests(unittest.TestCase):
    def test_legacy_item_icons_import_is_stable(self):
        self.assertIs(ItemIcons, CachedItemIcons)
        self.assertIs(ICON_MAP, CACHED_MAP)

    def test_queue_methods_continue_on_crafting_browser(self):
        self.assertTrue(issubclass(CraftingBrowser, CraftingQueueMixin))
        for name in ('show_queue', 'queue_command', 'update_queue'):
            self.assertIs(getattr(CraftingBrowser, name),
                          getattr(CraftingQueueMixin, name))
        self.assertTrue(callable(CraftingBrowser.tick))
        self.assertTrue(callable(CraftingBrowser.refresh_detail))
        self.assertTrue(callable(CraftingBrowser.refresh_grid))


if __name__ == '__main__':
    unittest.main()
