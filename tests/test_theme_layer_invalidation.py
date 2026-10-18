"""Background tint signatures: ordinary widgets never invalidate all image skins."""
import unittest
from unittest.mock import Mock

from wlre.ui.theme_surfaces import section_layers


class Ordinary:
    def __init__(self, widget_class='TLabel', *, fill=None, outline=False):
        self.widget_class = widget_class
        if fill is not None:
            self._surface_fill = fill
        self._section_outline = outline

    def winfo_class(self):
        return self.widget_class


class GlassGroup(Ordinary):
    pass


def box(widget, *, x=0, y=0, width=100, height=70, bounds=None):
    return (widget, x, y, width, height, bounds or (x, y, x+width, y+height))


class ThemeLayerInvalidationTests(unittest.TestCase):
    def test_moving_normal_labels_and_buttons_does_not_change_tinted_layers(self):
        pane = GlassGroup()
        a = [box(pane), box(Ordinary(), x=10, y=10),
             box(Ordinary('TButton'), x=20, y=30)]
        b = [box(pane), box(Ordinary(), x=40, y=10),
             box(Ordinary('TButton'), x=60, y=30),
             box(Ordinary(), x=3, y=3)]
        self.assertEqual(section_layers(a), section_layers(b))
        self.assertEqual(len(section_layers(a)), 1)
        self.assertEqual(section_layers(a)[0][-1], (9, 24, 39, 170))

    def test_tinted_panel_reposition_or_clip_changes_background(self):
        pane = GlassGroup()
        base = section_layers([box(pane)])
        self.assertNotEqual(base, section_layers([box(pane, x=5)]))
        clipped = box(pane, bounds=(0, 0, 70, 50))
        self.assertNotEqual(base, section_layers([clipped]))

    def test_explicit_surface_fill_and_tlabelframe_count_as_tinted(self):
        self.assertEqual(len(section_layers([box(Ordinary('TLabelframe'))])), 1)
        fill = (50, 90, 100, 120)
        self.assertEqual(section_layers([box(Ordinary(fill=fill))])[0][-1], fill)
        self.assertEqual(section_layers([box(Ordinary(fill=(50, 90, 100, 130)))]),
                             ((0, 0, 100, 70, (0, 0, 100, 70), (50, 90, 100, 130)),))
        self.assertEqual(section_layers([box(Ordinary())]), ())

    def test_too_small_invisible_panels_are_skipped(self):
        self.assertEqual(section_layers([box(GlassGroup(), width=4)]), ())
        self.assertEqual(section_layers([box(GlassGroup(), height=4)]), ())


if __name__ == '__main__':
    unittest.main()
