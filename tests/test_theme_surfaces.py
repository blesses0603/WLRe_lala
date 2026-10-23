"""Shared image coordinates, parent clipping and popup geometry regressions."""
import unittest
from unittest.mock import Mock
from PIL import Image, ImageDraw

from wlre.ui.theme_surfaces import (
    artwork_canvas, window_background, visible_bounds, widget_crop, draw_section,
)
from wlre.ui.window_layout import configure_dialog, dialog_geometry


class WindowSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canvas = Image.new('RGB', (1280, 800))
        draw = ImageDraw.Draw(cls.canvas)
        for x in range(1280):
            draw.line((x, 0, x, 799), fill=(x % 256, (x // 2) % 256, 100))

    def test_wallpaper_center_is_stable_between_windows(self):
        full = window_background(self.canvas, 1280, 800, main=True, outline=False)
        small = window_background(self.canvas, 600, 420, main=True, outline=False)
        self.assertEqual(small.getpixel((300, 210)), full.getpixel((640, 400)))

    def test_version_dialog_can_be_darkened_without_changing_global_theme(self):
        original = window_background(self.canvas, 600, 420, outline=False)
        stronger = window_background(self.canvas, 600, 420, outline=False,
                                     dim_amount=0.79)
        self.assertEqual(
            original.tobytes(),
            window_background(self.canvas, 600, 420,
                              outline=False).tobytes())
        self.assertLess(stronger.getpixel((300, 210))[0],
                        original.getpixel((300, 210))[0])
        self.assertLess(stronger.getpixel((300, 210))[1],
                        original.getpixel((300, 210))[1])
        with self.assertRaises(ValueError):
            window_background(self.canvas, 600, 420, dim_amount=1.1)

    def test_dialog_border_is_optional_without_changing_interior(self):
        bordered = window_background(self.canvas, 600, 420, outline=True)
        clean = window_background(self.canvas, 600, 420, outline=False)
        self.assertNotEqual(bordered.getpixel((100, 1)), clean.getpixel((100, 1)))
        self.assertEqual(bordered.getpixel((300, 210)), clean.getpixel((300, 210)))

    def test_parent_clipping_prevents_sampling_outside_surface(self):
        bounds = visible_bounds(-5, 10, 50, 30, (100, 80), ((0, 0, 40, 80),))
        self.assertEqual(bounds, (0, 10, 40, 40))
        tile = widget_crop(Image.new('RGBA', (100, 80), (7, 8, 9, 255)),
                           -5, 10, 50, 30, bounds)
        self.assertEqual(tile.getpixel((0, 3)), (16, 28, 43, 255))
        self.assertEqual(tile.getpixel((5, 3)), (7, 8, 9, 255))
        self.assertEqual(tile.getpixel((46, 3)), (16, 28, 43, 255))

    def test_intersects_nested_parent_boundaries(self):
        self.assertEqual(visible_bounds(4, 4, 90, 90, (100, 100),
                                        ((10, 12, 80, 60), (20, 20, 35, 30))),
                         (20, 20, 55, 50))
        self.assertIsNone(visible_bounds(0, 0, 20, 20, (100, 100), ((35, 0, 20, 20),)))

    def test_rounded_section_does_not_leak_past_parent(self):
        layer = Image.new('RGBA', (100, 70))
        draw_section(layer, -10, 5, 50, 40, (5, 10, 30, 30), (10, 20, 30, 170))
        self.assertEqual(layer.getpixel((4, 15))[3], 0)
        self.assertEqual(layer.getpixel((20, 15)), (10, 20, 30, 170))
        self.assertEqual(layer.getpixel((30, 15))[3], 0)

    def test_design_canvas_and_narrow_screen_dialog(self):
        self.assertEqual(artwork_canvas(Image.new('RGB', (100, 100))).size, (1280, 800))
        self.assertEqual(dialog_geometry(1040, 700, 800, 600), (776, 576, 12, 12))
        self.assertEqual(dialog_geometry(570, 505, 1280, 800), (570, 505, 355, 147))

    def test_configure_popup_with_single_border_and_preserve_override(self):
        window = Mock()
        window.winfo_screenwidth.return_value = 800
        window.winfo_screenheight.return_value = 600
        configure_dialog(window, 1040, 700)
        self.assertTrue(window._no_glass_border)
        window.geometry.assert_called_once_with('776x576+12+12')
        window.minsize.assert_called_once_with(776, 576)
        window.maxsize.assert_called_once_with(776, 576)
        window.resizable.assert_called_once_with(False, False)
        window._no_glass_border = False
        configure_dialog(window, 570, 505)
        self.assertFalse(window._no_glass_border)


if __name__ == '__main__':
    unittest.main()
