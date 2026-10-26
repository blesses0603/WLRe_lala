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
                preview = menu_icon_image(label, 42)
                self.assertIsNotNone(preview)
                self.assertEqual(preview.mode, 'RGBA')
                self.assertLessEqual(max(preview.size), 42)

    def test_missing_optional_icon_does_not_break_tabs(self):
        self.assertIsNone(menu_icon_image('不存在的功能', 42))


if __name__ == '__main__':
    unittest.main()
