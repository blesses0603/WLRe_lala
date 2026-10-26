"""Official 1275 reference-only links must survive missing marker/event rows."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from wlre.services.world.portal_evidence_1275 import read_only_portal_evidence
from wlre.services.world.portals import Portals, portal_map_pixel


def stage(*rows):
    return struct.pack('<i', len(rows)) + b''.join(
        struct.pack('<HBHIHHIB', *row) for row in rows)


def links(source=11016, target=11017):
    return (f'事件ID={source}\n'
            f'原場景位置[X:200,Y:300][{target}][X:5,Y:6]\n').encode('utf-16-le')


def stages():
    return {
        11016: {'pos_x_ratio': 3, 'pos_y_ratio': 2,
                'map_width': 1000, 'map_height': 1000,
                'small_offset_x': 12, 'small_offset_y': 13},
        11017: {'pos_x_ratio': 2, 'pos_y_ratio': 3},
    }


def portal_runtime(evidence, doors=None):
    return SimpleNamespace(
        doors=doors or {}, portal_destinations={}, portal_positions={},
        portal_display_destinations={}, portal_names={},
        portal_link_evidence=evidence,
        scene_names={11016: '新手海灘', 11017: '目的地'})


def get_catalog(runtime):
    with patch('wlre.services.world.runtime_1275.baseline_revision',
               return_value='1275'), patch(
               'wlre.services.world.runtime_1275.active_runtime',
               return_value=runtime):
        return Portals()


class OfficialLinkEvidenceTests(unittest.TestCase):
    def test_unmarked_link_retains_both_scaled_endpoints_but_no_packet(self):
        evidence = read_only_portal_evidence(
            stage(), links(), {11016: [{'index': 1, 'x': 42, 'y': 64}]},
            stages())
        item = evidence[11016, 1]
        self.assertEqual((item['x'], item['y']), (600, 600))
        self.assertEqual((item['arrival_x'], item['arrival_y']), (10, 18))
        self.assertEqual(item['destination'], 11017)
        self.assertFalse(item['stage_marker_matched'])
        self.assertFalse(item['can_send_packets'])
        row = get_catalog(portal_runtime(
            evidence, {11016: [{'index': 1, 'x': 42, 'y': 64}]})).for_scene(11016)[0]
        self.assertEqual((row['x'], row['y']), (600, 600))
        self.assertIn('目的地', row['name'])
        self.assertFalse(row['destination_verified'])
        self.assertTrue(row['link_reference_only'])
        self.assertFalse(row['direct_eligible'])
        with self.assertRaises(ValueError):
            Portals.direct_target(row, 11016)

    def test_eve_missing_still_lists_official_link_without_unlocking_send(self):
        evidence = read_only_portal_evidence(stage(), links(), {}, stages())
        catalog = get_catalog(portal_runtime(evidence))
        row, = catalog.for_scene(11016)
        self.assertEqual(row['id'], '1275-ref:11016:1')
        self.assertEqual(row['coordinate_source'],
                         'official_link_reference_scaled')
        self.assertEqual(catalog.data['official_link_reference_count'], 1)
        self.assertFalse(row['direct_eligible'])
        self.assertIsNone(row['destination'])
        with self.assertRaises(ValueError):
            Portals.direct_target(row, 11016)

    def test_unverified_destination_stays_read_only_and_no_guessed_arrival(self):
        partial = {11016: stages()[11016]}
        evidence = read_only_portal_evidence(
            stage(), links(target=15139), {}, partial)
        item = evidence[11016, 1]
        self.assertEqual(item['destination'], 15139)
        self.assertFalse(item['destination_defined'])
        self.assertIsNone(item['arrival_x'])
        self.assertIn('destination_scene_undefined', item['issues'])
        row, = get_catalog(portal_runtime(evidence)).for_scene(11016)
        self.assertFalse(row['direct_eligible'])

    def test_marker_without_geometry_cannot_place_fake_map_dot(self):
        incomplete = {11016: {'pos_x_ratio': 3, 'pos_y_ratio': 2}}
        evidence = read_only_portal_evidence(stage(), links(), {}, incomplete)
        row, = get_catalog(portal_runtime(evidence)).for_scene(11016)
        self.assertFalse(row['coordinate_valid'])
        self.assertIsNone(row['x'])

    def test_reference_projection_requires_exact_current_geometry(self):
        evidence = read_only_portal_evidence(stage(), links(), {}, stages())
        row, = get_catalog(portal_runtime(evidence)).for_scene(11016)
        good = SimpleNamespace(rate=100.0, offset_x=12, offset_y=13,
                               height=1000,
                               packet_to_pixel=lambda x, y: (x, y))
        bad = SimpleNamespace(rate=100.0, offset_x=99, offset_y=13,
                              height=1000,
                              packet_to_pixel=lambda x, y: (x, y))
        self.assertEqual(portal_map_pixel(row, good), (600, 600))
        self.assertIsNone(portal_map_pixel(row, bad))

    def test_duplicate_eve_events_do_not_enable_reference_travel(self):
        events = {11016: [{'index': 1, 'x': 4, 'y': 6},
                          {'index': 1, 'x': 9, 'y': 6}]}
        evidence = read_only_portal_evidence(
            stage((11016, 2, 0, 1, 0, 0, 42, 0)), links(),
            events, stages())
        self.assertIn('duplicate_eve_door', evidence[11016, 1]['issues'])
        catalog = get_catalog(portal_runtime(evidence, events))
        self.assertEqual(len(catalog.for_scene(11016)), 2)
        self.assertTrue(all(not x['direct_eligible']
                            for x in catalog.for_scene(11016)))


    def test_missing_stage_map_still_preserves_authenticated_links(self):
        evidence = read_only_portal_evidence(
            None, links(),
            {11016: [{'index': 1, 'x': 42, 'y': 64}]}, stages())
        self.assertEqual(evidence[11016, 1]['destination'], 11017)
        self.assertFalse(evidence[11016, 1]['stage_marker_matched'])
        self.assertFalse(evidence[11016, 1]['can_send_packets'])

    def test_independent_door_link_data_has_no_event_index(self):
        from wlre.services.world.portal_evidence_1275 import (
            read_only_door_link_routes)
        raw = struct.pack('<iHHHHHH', 1, 11016, 200, 300,
                          11017, 5, 6)
        routes = read_only_door_link_routes(raw, stages())
        self.assertEqual(len(routes), 1)
        route = routes[0]
        self.assertEqual((route['x'], route['y']), (600, 600))
        self.assertEqual((route['arrival_x'], route['arrival_y']), (10, 18))
        self.assertEqual(route['destination'], 11017)
        self.assertIsNone(route['event_index'])
        self.assertFalse(route['can_send_packets'])

    def test_invalid_door_link_data_fails_closed(self):
        from wlre.services.world.portal_evidence_1275 import (
            read_only_door_link_routes)
        with self.assertRaises(ValueError):
            read_only_door_link_routes(b'\x01\x00\x00\x00', stages())


    def test_hidden_portal_uses_event_id_as_destination_not_door_index(self):
        from wlre.services.world.portal_evidence_1275 import (
            read_only_stage_portal_markers)
        raw = stage((11016, 3, 0, 11017, 200, 300, 63840, 1),
                    (11016, 4, 11017, 1, 30, 40, 0, 2))
        markers = read_only_stage_portal_markers(raw, stages())
        self.assertEqual(len(markers), 2)
        hidden, cross = markers
        self.assertEqual((hidden['x'], hidden['y']), (600, 600))
        self.assertEqual(hidden['destination'], 11017)
        self.assertEqual(cross['cross_scene_reference'], 11017)
        self.assertIsNone(cross['destination'])
        self.assertFalse(hidden['can_send_packets'])
        runtime = portal_runtime({})
        runtime.portal_stage_markers = markers
        runtime.texts = {63840: '隱藏海灘入口'}
        rows = get_catalog(runtime).for_scene(11016)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['official_name'], '隱藏海灘入口')
        self.assertEqual(rows[0]['hidden_destination_scene_id'], 11017)
        self.assertFalse(rows[0]['direct_eligible'])
        with self.assertRaises(ValueError):
            Portals.direct_target(rows[0], 11016)

    def test_unnamed_hidden_portal_keeps_unknown_destination(self):
        from wlre.services.world.portal_evidence_1275 import (
            read_only_stage_portal_markers)
        raw = stage((11016, 3, 0, 0, 200, 300, 0, 1))
        hidden, = read_only_stage_portal_markers(raw, stages())
        self.assertIsNone(hidden['destination'])
        self.assertEqual((hidden['x'], hidden['y']), (600, 600))
        self.assertFalse(hidden['can_send_packets'])


if __name__ == '__main__':
    unittest.main()
