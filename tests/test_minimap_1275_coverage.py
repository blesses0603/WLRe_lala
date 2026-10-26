"""1275 official scene geometry fills omissions without copying 1262 mappings."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.features.minimap.buttons import MinimapPickMixin
from wlre.features.minimap.navigation_ui import MinimapNavigationMixin
from wlre.services.world.portals import portal_map_pixel
from wlre.services.world.smallmaps import SmallMaps


def stage(model, *, width, height, offset_x=3, offset_y=28):
    return {'model_id': model, 'map_width': width, 'map_height': height,
            'small_offset_x': offset_x, 'small_offset_y': offset_y}


class Official1275MinimapTests(unittest.TestCase):
    def setUp(self):
        self.stages = {
            # Newly present in official 1275; absent from 1262 stage_coordinates.
            15138: stage(11139, width=7200, height=7200),
            # Its 1262 geometry was 65535/65535, the 1275 dimensions differ.
            13216: stage(13216, width=3960, height=3960, offset_x=12, offset_y=12),
        }
        self.runtime = SimpleNamespace(revision=1275, stages=self.stages)
        self.patch_runtime = patch('wlre.services.world.runtime_1275.active_runtime',
                                   return_value=self.runtime)
        self.patch_runtime.start()
        self.addCleanup(self.patch_runtime.stop)

    def test_missing_official_scene_15138_now_maps_to_existing_model_11139(self):
        maps = SmallMaps(source_revision='1275')
        self.assertTrue(maps.has_image(15138))
        projection, model = maps.projection(15138)
        self.assertEqual(model, 'M11139')
        self.assertEqual(projection.height, 7200)
        self.assertEqual(maps.image(model).size, (1024, 1024))
        self.assertFalse(maps.supports_navigation)
        with self.assertRaises(ValueError):
            maps.for_model(model, 15138)

    def test_changed_1275_geometry_replaces_stale_1262_size_and_offsets(self):
        maps = SmallMaps(source_revision='1275')
        # Official 13216 has changed geometry, but no SmallMap2D_13216
        # exists in either package: never substitute a different model image.
        self.assertFalse(maps.has_image(13216))
        with self.assertRaises(ValueError):
            maps.projection(13216)
        # If current runtime geometry changes for a scene with an actual
        # image, the versioned rows take precedence over the legacy JSON.
        self.stages[10001] = stage(10001, width=3960, height=3960,
                                   offset_x=64, offset_y=8)
        projection, model = maps.projection(10001)
        self.assertEqual(model, 'M10001')
        self.assertAlmostEqual(projection.rate, 100000 / 3960)
        self.assertEqual((projection.offset_x, projection.offset_y, projection.height),
                         (64, 8, 3960))
        row = {'coordinate_valid': True, 'x': 200, 'y': 400,
               'projection_guard': {'rate': 100000 / 3960,
                                    'offset_x': 64, 'offset_y': 8,
                                    'height': 3960}}
        self.assertIsNotNone(portal_map_pixel(row, projection))

    def test_unknown_1275_scene_does_not_fall_back_to_1262_catalog(self):
        maps = SmallMaps(source_revision='1275')
        self.assertFalse(maps.has_image(10002))
        with self.assertRaises(ValueError):
            maps.projection(10002)

    def test_1275_image_stays_readonly_in_existing_minimap_page(self):
        page = MinimapNavigationMixin()
        page.maps = SmallMaps(source_revision='1275')
        page.repository = Mock()
        page.map_title, page.note = Mock(), Mock()
        page.portals = SimpleNamespace(data={
            'source_revision': 1275, 'scene_names': {15138: '噴氣孔洞穴一'}})
        page.refresh_portals, page.draw = Mock(), Mock()
        page.show_map(15138)
        self.assertIsNotNone(page.image)
        self.assertIsNone(page.mesh)
        page.repository.load.assert_not_called()

        click = MinimapPickMixin()
        click.maps = page.maps
        click.projection = page.projection
        click.portal_rows = []
        click.npc_rows = []
        click.screen_pixel = lambda x, y: (x, y)
        click.selected_portal = None
        click.note, click.update_portal_button = Mock(), Mock()
        click.on_pick, click.on_move = Mock(), Mock()
        click.view = lambda: (0, 0, 1)
        click.double_pick(SimpleNamespace(x=300, y=300))
        click.on_pick.assert_not_called()
        click.on_move.assert_not_called()


if __name__ == '__main__':
    unittest.main()
