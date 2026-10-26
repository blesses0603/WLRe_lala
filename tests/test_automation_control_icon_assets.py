"""Play and pause images remain valid when loaded headlessly."""
import unittest
from PIL import Image

from wlre.ui.automation_control_icons import (
    ASSET_DIR, ASSETS, control_icon_image)


class AutomationIconAssetTests(unittest.TestCase):
    def test_supplied_icons_are_valid_transparent_png(self):
        for action, filename in ASSETS.items():
            with self.subTest(action=action):
                path = ASSET_DIR / filename
                self.assertTrue(path.is_file(), str(path))
                with Image.open(path) as image:
                    image.verify()
                icon = control_icon_image(action)
                self.assertIsNotNone(icon)
                self.assertEqual(icon.mode, 'RGBA')
                self.assertEqual(icon.size, (28, 28))
                self.assertEqual(icon.getpixel((0, 0))[3], 0)
                self.assertGreater(icon.getchannel('A').getbbox()[2], 16)

    def test_play_and_pause_images_are_distinct(self):
        self.assertNotEqual(
            control_icon_image('play').tobytes(),
            control_icon_image('pause').tobytes())

    def test_invalid_action_or_size_fails_closed(self):
        self.assertIsNone(control_icon_image('unknown'))
        self.assertIsNone(control_icon_image('play', 0))
        self.assertIsNone(control_icon_image('pause', 1000))


if __name__ == '__main__':
    unittest.main()
