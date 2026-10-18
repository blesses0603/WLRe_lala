"""Homepage action pictograms must remain faithful to bundled game sprites."""
import unittest
from unittest.mock import patch

from PIL import Image, ImageOps

from wlre.paths import RESOURCE_ROOT
from wlre.resource_manifest import REQUIRED_RESOURCES
from wlre.ui.function_icons import ICONS, action_icon_image, action_icon_photo


class OriginalHomeActionIcons(unittest.TestCase):
    ACTIONS = {
        '組隊': 'MainIcon_005',
        '煉金': 'MainIcon_007',
        '製作': 'MainIcon_011',
        '經驗效率': 'MainIcon_020',
    }

    def test_each_action_uses_its_original_bundled_png(self):
        for title, sprite in self.ACTIONS.items():
            with self.subTest(title=title):
                self.assertEqual(ICONS[title], sprite)
                filename = 'assets/function-icons/' + sprite + '.png'
                self.assertIn(filename, REQUIRED_RESOURCES)
                with Image.open(RESOURCE_ROOT / filename) as source:
                    expected = ImageOps.contain(
                        source.convert('RGBA'), (24, 24), Image.Resampling.LANCZOS)
                actual = action_icon_image(title)
                self.assertEqual(actual.mode, 'RGBA')
                self.assertEqual(actual.size, expected.size)
                # No synthetic circles or other altered pixels: resize only.
                self.assertEqual(actual.tobytes(), expected.tobytes())
                self.assertIs(actual, action_icon_image(title))

    def test_tk_photo_keeps_the_parent_as_master(self):
        with patch('wlre.ui.function_icons.ImageTk.PhotoImage') as factory:
            action_icon_photo('fixture-parent', '煉金')
        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs['master'], 'fixture-parent')
        self.assertEqual(factory.call_args.args[0].tobytes(), action_icon_image('煉金').tobytes())


if __name__ == '__main__':
    unittest.main()
