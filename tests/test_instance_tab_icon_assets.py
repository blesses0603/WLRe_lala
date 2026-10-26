"""Instance tab icon paths and image integrity, without requiring Tk/display."""
import unittest
from pathlib import Path

from PIL import Image

from wlre.paths import RESOURCE_ROOT
from wlre.ui.instance_menu_icons import menu_icon_image, MENU_ASSETS


class InstanceIconAssetsTests(unittest.TestCase):
    def test_main_and_subtabs_use_same_user_provided_bitmaps(self):
        self.assertEqual(MENU_ASSETS['副本'], MENU_ASSETS['主要'])
        self.assertEqual(MENU_ASSETS['協力'], 'Menu_Cooperate.png')
        for label in ('副本', '主要', '協力'):
            with self.subTest(label=label):
                path = RESOURCE_ROOT / 'assets' / 'instance-menu' / MENU_ASSETS[label]
                self.assertTrue(path.is_file(), str(path))
                with Image.open(path) as image:
                    image.verify()
                preview = menu_icon_image(label, 34)
                self.assertIsNotNone(preview)
                self.assertEqual(preview.mode, 'RGBA')
                # Exactly the same dimensions and transparent round corners
                # as every icon_image() dashboard tab, no blue square tile.
                self.assertEqual(preview.size, (34, 34))
                self.assertEqual(preview.getpixel((0, 0))[3], 0)
                self.assertGreater(preview.getpixel((17, 17))[3], 100)

    def test_dungeon_and_coop_are_visually_different_new_glyphs(self):
        dungeon = menu_icon_image('副本', 34)
        coop = menu_icon_image('協力', 34)
        self.assertEqual(dungeon.size, coop.size)
        self.assertNotEqual(dungeon.tobytes(), coop.tobytes())
        self.assertEqual(menu_icon_image('主要', 34).tobytes(),
                         dungeon.tobytes())

    def test_missing_optional_icon_does_not_break_tabs(self):
        self.assertIsNone(menu_icon_image('不存在的功能', 42))


if __name__ == '__main__':
    unittest.main()
