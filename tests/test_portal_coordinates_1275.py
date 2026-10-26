"""1275 map marker coordinates must use scaled EveDoorLinks, NOT Eve.NewDoor."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.services.world.portal_links_1275 import verified_portal_positions
from wlre.services.world.portals import Portals, portal_map_pixel, nearest_marker, marked_portals
from wlre.features.portals.panel import PortalInteractionMixin


def stage_marker(scene=11016, idx=1, x=20, y=30):
    return struct.pack('<iHBHIHHIB', 1, scene, 2, 0, idx, x, y, 345, 0)


def door_links(scene=11016, x=200, y=300):
    return (f'事件ID={scene}\n'
            f'原場景位置[X:{x},Y:{y}][11017][X:100,Y:200]\n'
            ).encode('utf-16-le')


def position_fixture():
    return verified_portal_positions(
        stage_marker(), door_links(),
        {11016: [{'index': 1, 'x': 42, 'y': 64}]},
        {11016: {'pos_x_ratio': 3, 'pos_y_ratio': 2}})


class IdentityProjection:
    def packet_to_pixel(self, x, y):
        return x, y


class OffscreenProjection:
    def packet_to_pixel(self, x, y):
        return x + 1000, y + 1000


class PortalPosition1275Tests(unittest.TestCase):
    def test_list_contains_only_named_visible_markers_without_changing_catalog(self):
        ready = {'source_revision': 1275, 'coordinate_valid': True,
                 'official_name': '海灘出口', 'x': 200, 'y': 300}
        reference = dict(ready, official_name=None, display_destination_label='北島-北(60000)')
        unnamed = dict(ready, official_name=None)
        offscreen = dict(ready, x=2000)
        missing = dict(ready, coordinate_valid=False)
        rows = [ready, reference, unnamed, offscreen, missing]
        self.assertEqual(marked_portals(rows, IdentityProjection()), [ready, reference])
        self.assertEqual(len(rows), 5)
        self.assertEqual(marked_portals(rows, None), [])

    def test_destination_uses_event_identity_and_separately_scaled_marker(self):
        from wlre.services.world.portal_links_1275 import verified_portal_destinations
        doors = {11016: [{'index': 1, 'x': 42, 'y': 64}]}
        bindings = verified_portal_destinations(
            stage_marker(), door_links(), doors, {11016, 11017})
        runtime = SimpleNamespace(
            doors=doors, portal_positions=position_fixture(), portal_destinations=bindings,
            scene_names={11016: '新手海灘', 11017: '目的場景'})
        with patch('wlre.services.world.runtime_1275.baseline_revision', return_value='1275'), \
             patch('wlre.services.world.runtime_1275.active_runtime', return_value=runtime):
            catalog = Portals()
        row = catalog.for_scene(11016)[0]
        self.assertTrue(row['destination_verified'])
        self.assertTrue(row['direct_eligible'])
        self.assertEqual(row['destination'], 11017)
        self.assertEqual((row['x'], row['y']), (600, 600))
        self.assertEqual(marked_portals([row], IdentityProjection()), [row])
        page = PortalInteractionMixin()
        page.selected_portal = row
        page.maps = SimpleNamespace(has_image=lambda scene: True)
        page.state = {'player': {'scene': 11016}}
        page.selected_id = 11016
        page.projection = IdentityProjection()
        page.portal_go = Mock()
        page.update_portal_button()
        self.assertEqual(page.portal_go.configure.call_args.kwargs,
                         {'state': 'normal', 'text': '手動確認換圖'})
        page.maps = SimpleNamespace(has_image=lambda scene: False)
        page.update_portal_button()
        self.assertEqual(page.portal_go.configure.call_args.kwargs['text'], '目的地無地圖')
    def test_official_uimain_ratio_not_eve_common_grid_xy(self):
        points = position_fixture()
        self.assertEqual(points[(11016, 1)]['x'], 600)
        self.assertEqual(points[(11016, 1)]['y'], 600)
        self.assertEqual(points[(11016, 1)]['raw_link_x'], 200)
        self.assertEqual(points[(11016, 1)]['raw_link_y'], 300)
        self.assertEqual(points[(11016, 1)]['source_kind'],
                         '1275_eve_door_links_grid_scaled')
        self.assertNotEqual((600, 600), (42, 64))

    def test_missing_or_invalid_calibration_never_guesses_position(self):
        for stage in ({}, {'pos_x_ratio': 0, 'pos_y_ratio': 2},
                      {'pos_x_ratio': 3, 'pos_y_ratio': None}):
            with self.subTest(stage=stage):
                self.assertEqual(verified_portal_positions(
                    stage_marker(), door_links(),
                    {11016: [{'index': 1, 'x': 42, 'y': 64}]},
                    {11016: stage}), {})
        self.assertEqual(verified_portal_positions(
            stage_marker(idx=2), door_links(),
            {11016: [{'index': 1, 'x': 42, 'y': 64}]},
            {11016: {'pos_x_ratio': 3, 'pos_y_ratio': 2}}), {})

    def test_unverified_eve_event_grid_is_not_displayed_or_clickable(self):
        runtime = SimpleNamespace(
            scene_names={11016: '新手海灘'},
            doors={11016: [{'index': 1, 'x': 42, 'y': 64}]},
            portal_positions={}, portal_destinations={})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            row = Portals().for_scene(11016)[0]
        self.assertEqual((row['event_grid_x'], row['event_grid_y']), (42, 64))
        self.assertIsNone(row['x'])
        self.assertIsNone(row['y'])
        self.assertFalse(row['coordinate_valid'])
        self.assertIsNone(portal_map_pixel(row, IdentityProjection()))
        self.assertIsNone(nearest_marker(
            [row], IdentityProjection(), lambda x, y: (x, y),
            42, 64))
        self.assertFalse(row['direct_eligible'])

    def test_verified_projection_is_in_bounds_and_can_set_target_once(self):
        runtime = SimpleNamespace(
            scene_names={11016: '新手海灘'},
            doors={11016: [{'index': 1, 'x': 42, 'y': 64}]},
            portal_positions=position_fixture(), portal_destinations={})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            row = Portals().for_scene(11016)[0]
        self.assertTrue(row['coordinate_valid'])
        self.assertEqual((row['x'], row['y']), (600, 600))
        self.assertEqual(portal_map_pixel(row, IdentityProjection()), (600, 600))
        self.assertIs(nearest_marker(
            [row], IdentityProjection(), lambda x, y: (x, y),
            600, 600), row)
        self.assertIsNone(portal_map_pixel(row, OffscreenProjection()))
        self.assertIsNone(nearest_marker(
            [row], OffscreenProjection(), lambda x, y: (x, y),
            1600, 1600))
        page = PortalInteractionMixin()
        page.selected_id = 11016
        page.list_rows = [row]
        page.portal_list, page.npc_list = Mock(), Mock()
        page.portal_status, page.update_portal_button = Mock(), Mock()
        page.draw, page.on_pick = Mock(), Mock()
        page.projection = IdentityProjection()
        page.select_portal(row)
        page.on_pick.assert_called_once_with(11016, 600, 600)

    def test_verified_but_offscreen_portal_does_not_set_navigation_target(self):
        p = {'source_revision': 1275, 'coordinate_valid': True,
             'name': '地圖出口', 'x': 600, 'y': 600}
        page = PortalInteractionMixin()
        page.selected_id = 11016
        page.list_rows = [p]
        page.portal_list, page.npc_list = Mock(), Mock()
        page.portal_status, page.update_portal_button = Mock(), Mock()
        page.draw, page.on_pick = Mock(), Mock()
        page.projection = OffscreenProjection()
        page.select_portal(p)
        page.on_pick.assert_not_called()
        self.assertIn('超出', page.portal_status.set.call_args.args[0])

    def test_verified_1275_scene_geometry_prevents_1262_image_misalignment(self):
        stage = {'pos_x_ratio': 3, 'pos_y_ratio': 2,
                 'map_width': 1000, 'map_height': 1000,
                 'small_offset_x': 25, 'small_offset_y': 30}
        calibrated = verified_portal_positions(
            stage_marker(), door_links(),
            {11016: [{'index': 1, 'x': 42, 'y': 64}]},
            {11016: stage})[(11016, 1)]
        expected = {'rate': 100.0, 'offset_x': 25,
                    'offset_y': 30, 'height': 1000}
        self.assertEqual(calibrated['projection_guard'], expected)
        p = {'coordinate_valid': True, 'x': 600, 'y': 600,
             'projection_guard': expected}
        good = SimpleNamespace(
            rate=100.0, offset_x=25, offset_y=30, height=1000,
            packet_to_pixel=lambda x, y: (x, y))
        bad = SimpleNamespace(
            rate=100.0, offset_x=40, offset_y=30, height=1000,
            packet_to_pixel=lambda x, y: (x, y))
        self.assertEqual(portal_map_pixel(p, good), (600, 600))
        self.assertIsNone(portal_map_pixel(p, bad))
        self.assertIsNone(nearest_marker(
            [p], bad, lambda x, y: (x, y), 600, 600))


if __name__ == '__main__':
    unittest.main()
