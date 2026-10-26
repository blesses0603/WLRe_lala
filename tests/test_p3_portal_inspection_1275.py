"""P3 second batch: read-only 1275 source and arrival inspection."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.features.portals.panel import PortalInteractionMixin
from wlre.services.world.portal_inspection_1275 import (
    link_inspection_fields, portal_inspection_text)
from wlre.services.world.portals import Portals


def official_reference(target=11017, known=True):
    return {
        'source_kind': '1275_eve_door_links_reference',
        'scene': 11016, 'index': 1, 'destination': target,
        'destination_defined': known,
        'source_grid_x': 200, 'source_grid_y': 300,
        'arrival_grid_x': 5, 'arrival_grid_y': 6,
        'x': 600, 'y': 600,
        'arrival_x': 10 if known else None,
        'arrival_y': 18 if known else None,
        'position_verified': True, 'arrival_verified': known,
        'issues': ('missing_normal_stage_marker',),
        'projection_guard': {'rate': 100, 'offset_x': 0,
                             'offset_y': 0, 'height': 1000},
    }


def catalog(reference, *, event=True):
    runtime = SimpleNamespace(
        doors={11016: [{'index': 1, 'x': 42, 'y': 64}]} if event else {},
        portal_destinations={}, portal_positions={},
        portal_names={}, portal_display_destinations={},
        portal_link_evidence={(11016, 1): reference},
        scene_names={11016: '新手海灘', 11017: '目的地'})
    with patch('wlre.services.world.runtime_1275.baseline_revision',
               return_value='1275'), patch(
               'wlre.services.world.runtime_1275.active_runtime',
               return_value=runtime):
        return Portals()


class P3PortalInspectionTests(unittest.TestCase):
    def test_existing_event_keeps_both_locations_without_authorizing_packet(self):
        row, = catalog(official_reference()).for_scene(11016)
        self.assertEqual(row['reference_destination_scene_id'], 11017)
        self.assertEqual(row['reference_destination_label'], '目的地(11017)')
        self.assertEqual(row['reference_source_xy'], (600, 600))
        self.assertEqual(row['reference_source_grid'], (200, 300))
        self.assertEqual(row['reference_arrival_xy'], (10, 18))
        self.assertEqual(row['reference_arrival_grid'], (5, 6))
        self.assertIsNone(row['destination'])
        self.assertFalse(row['direct_eligible'])
        self.assertIn('落點座標 (10, 18)', portal_inspection_text(row))
        with self.assertRaises(ValueError):
            Portals.direct_target(row, 11016)

    def test_unmatched_eve_link_appears_without_false_event_index(self):
        row, = catalog(official_reference(), event=False).for_scene(11016)
        self.assertTrue(row['id'].startswith('1275-ref:'))
        self.assertEqual(row['reference_arrival_xy'], (10, 18))
        self.assertIsNone(row['door_index'])
        self.assertFalse(row['direct_eligible'])

    def test_undefined_scene_keeps_id_but_never_guesses_arrival(self):
        row, = catalog(official_reference(15139, known=False)).for_scene(11016)
        self.assertEqual(row['reference_destination_scene_id'], 15139)
        self.assertIn('場景表未定義', row['reference_destination_label'])
        self.assertEqual(row['reference_arrival_grid'], (5, 6))
        self.assertIsNone(row['reference_arrival_xy'])
        self.assertIn('倍率待核對', portal_inspection_text(row))
        self.assertIsNone(row['destination'])
        self.assertFalse(row['direct_eligible'])

    def test_ref_must_match_source_scene_and_ordinal(self):
        source = official_reference()
        self.assertIsNone(link_inspection_fields(
            source, 11017, 1, {})['reference_destination_scene_id'])
        self.assertIsNone(link_inspection_fields(
            source, 11016, 2, {})['reference_destination_scene_id'])
        self.assertIsNone(link_inspection_fields(
            {'source_kind': 'other', **{
                k: v for k, v in source.items() if k != 'source_kind'}},
            11016, 1, {})['reference_destination_scene_id'])

    def test_bad_grid_or_unverified_coordinates_stay_unset(self):
        source = official_reference()
        source.update(source_grid_x=-1, arrival_x=99999,
                      arrival_verified=False, position_verified=False)
        fields = link_inspection_fields(source, 11016, 1, {})
        self.assertIsNone(fields['reference_source_grid'])
        self.assertIsNone(fields['reference_source_xy'])
        self.assertIsNone(fields['reference_arrival_xy'])
        self.assertEqual(fields['reference_arrival_grid'], (5, 6))

    def test_portal_selection_displays_read_only_arrival_info(self):
        row, = catalog(official_reference()).for_scene(11016)
        page = PortalInteractionMixin()
        page.selected_id = 11016
        page.npc_list = Mock()
        page.portal_list = Mock()
        page.list_rows = [row]
        page.portal_status = Mock()
        page.update_portal_button = Mock()
        page.draw = Mock()
        page.on_pick = None
        page.select_portal(row)
        status = page.portal_status.set.call_args.args[0]
        self.assertIn('目的地(11017)', status)
        self.assertIn('來源座標 (600, 600)', status)
        self.assertIn('落點座標 (10, 18)', status)
        self.assertIn('未核准換圖', status)
        page.update_portal_button.assert_called_once_with()
        page.draw.assert_called_once_with()

    def test_hidden_links_use_scene_local_ordinal(self):
        runtime = SimpleNamespace(
            doors={}, portal_names={}, portal_destinations={},
            portal_positions={}, portal_link_evidence={},
            scene_names={11016: '新手海灘', 11017: '目的地'},
            texts={}, portal_stage_markers=[
                {'kind': 3, 'scene': 11016, 'destination': 11017,
                 'destination_defined': True, 'position_verified': False},
                {'kind': 3, 'scene': 11017, 'destination': None,
                 'destination_defined': False, 'position_verified': False},
                {'kind': 3, 'scene': 11016, 'destination': 11017,
                 'destination_defined': True, 'position_verified': False},
            ])
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                   'wlre.services.world.runtime_1275.active_runtime',
                   return_value=runtime):
            c = Portals()
        self.assertEqual([x['index'] for x in c.for_scene(11016)], ['H1', 'H2'])
        self.assertEqual([x['index'] for x in c.for_scene(11017)], ['H1'])
        self.assertTrue(all(not x['direct_eligible']
                            for key in (11016, 11017) for x in c.for_scene(key)))


if __name__ == '__main__':
    unittest.main()
