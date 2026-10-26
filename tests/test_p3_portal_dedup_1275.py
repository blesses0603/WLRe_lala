"""P3: repeated names/XY must not destroy distinct 1275 portal routes."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from wlre.services.world.portal_dedup_1275 import deduplicate_1275_portals
from wlre.services.world.portals import Portals


def door(index, *, name='相同名稱', x=200, y=300, target=11017):
    return {
        'source_revision': 1275, 'scene': 11016, 'index': index,
        'id': f'1275:11016:{index}', 'kind': 'door',
        'name': name, 'official_name': name,
        'x': x, 'y': y, 'coordinate_valid': True,
        'destination': target, 'destination_verified': True,
        'direct_eligible': True, 'direct_door_index': index,
        'door_index': index, 'navigation_status': 'endpoint_valid',
    }


def hidden(index, *, x=5, y=6, target=11017, name_id=404):
    return {
        'source_revision': 1275, 'scene': 11016,
        'index': f'H{index}', 'id': f'1275-hidden:11016:{index}',
        'kind': 'link', 'name': '隱藏入口', 'official_name': '隱藏入口',
        'source_grid_x': x, 'source_grid_y': y,
        'hidden_destination_scene_id': target, 'name_id': name_id,
        'x': x * 2, 'y': y * 2, 'coordinate_valid': True,
        'destination': None, 'destination_verified': False,
        'direct_eligible': False,
    }


class DuplicatePortalsTest(unittest.TestCase):
    def test_same_name_and_same_xy_different_ids_stay(self):
        rows, info = deduplicate_1275_portals({'11016': [
            door(1), door(2), door(3, target=11018),
        ]})
        self.assertEqual([p['index'] for p in rows['11016']], [1, 2, 3])
        self.assertEqual(info['duplicate_event_id_removed'], 0)
        self.assertEqual(info['repeated_name_groups'], 1)
        self.assertEqual(info['repeated_coordinate_groups'], 1)
        self.assertTrue(all(row['direct_eligible'] for row in rows['11016']))

    def test_same_event_id_collapses_and_revokes_packet_and_navigation(self):
        rows, info = deduplicate_1275_portals({'11016': [
            door(1, target=11017), door(1, target=11018),
            door(2, target=11019)]})
        self.assertEqual(len(rows['11016']), 2)
        duplicate, distinct = rows['11016']
        self.assertEqual(info['duplicate_event_id_removed'], 1)
        self.assertEqual(info['ambiguous_event_ids'], [(11016, 1)])
        self.assertFalse(duplicate['direct_eligible'])
        self.assertFalse(duplicate['coordinate_valid'])
        self.assertIsNone(duplicate['direct_door_index'])
        self.assertIsNone(duplicate['destination'])
        self.assertIn('duplicate_eve_door', duplicate['reference_issues'])
        with self.assertRaises(ValueError):
            Portals.direct_target(duplicate, 11016)
        self.assertTrue(distinct['direct_eligible'])
        self.assertEqual(Portals.direct_target(distinct, 11016), 2)

    def test_even_identical_id_records_revoke_ambiguous_trigger(self):
        rows, report = deduplicate_1275_portals({
            '11016': [door(1), door(1)]})
        self.assertEqual(len(rows['11016']), 1)
        self.assertFalse(rows['11016'][0]['direct_eligible'])
        self.assertEqual(report['duplicate_event_id_removed'], 1)

    def test_hidden_exact_identity_deduped_and_renumbered_per_scene(self):
        same = hidden(1)
        next_one = hidden(2, target=11019)
        copy = hidden(3)
        other_scene = {**hidden(1), 'scene': 11017,
                       'id': '1275-hidden:11017:1'}
        rows, info = deduplicate_1275_portals({
            '11016': [same, copy, next_one],
            '11017': [other_scene]})
        self.assertEqual(info['duplicate_hidden_removed'], 1)
        self.assertEqual([x['index'] for x in rows['11016']], ['H1', 'H2'])
        self.assertEqual(rows['11016'][1]['id'], '1275-hidden:11016:2')
        self.assertEqual(rows['11017'][0]['index'], 'H1')
        self.assertTrue(all(not x['direct_eligible']
                            for r in rows.values() for x in r))

    def test_same_xy_but_different_hidden_target_or_name_id_stays(self):
        rows, info = deduplicate_1275_portals({'11016': [
            hidden(1), hidden(2, target=11018),
            hidden(3, name_id=405)]})
        self.assertEqual(len(rows['11016']), 3)
        self.assertEqual(info['duplicate_hidden_removed'], 0)

    def test_hidden_without_source_grid_stays_visible_instead_of_guessed(self):
        data = hidden(1)
        data.pop('source_grid_x')
        rows, info = deduplicate_1275_portals({'11016': [data, hidden(2)]})
        self.assertEqual(len(rows['11016']), 2)
        self.assertEqual(info['duplicate_hidden_removed'], 0)

    def test_normal_and_hidden_never_share_identity(self):
        rows, info = deduplicate_1275_portals({'11016': [
            door(1), hidden(1), door(2, name='相同名稱')]})
        self.assertEqual(len(rows['11016']), 3)
        self.assertEqual(info['duplicate_event_id_removed'], 0)

    def test_current_runtime_duplicate_eve_index_does_not_unlock_transfer(self):
        runtime = SimpleNamespace(
            doors={11016: [
                {'index': 1, 'x': 200, 'y': 300},
                {'index': 1, 'x': 400, 'y': 500},
            ]},
            portal_destinations={(11016, 1): {
                'matched_stage_map': True, 'destination_verified': True,
                'trigger_verified': False, 'destination': 11017,
                'event_x': 200, 'event_y': 300,
            }},
            portal_positions={(11016, 1): {
                'scene': 11016, 'index': 1, 'x': 200, 'y': 300,
                'source_kind': '1275_eve_door_links_grid_scaled',
                'position_verified': True}},
            scene_names={11016: '新手海灘', 11017: '另一場景'})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                   'wlre.services.world.runtime_1275.active_runtime',
                   return_value=runtime):
            catalog = Portals()
        row, = catalog.for_scene(11016)
        self.assertFalse(row['direct_eligible'])
        self.assertIsNone(row['destination'])
        self.assertEqual(
            catalog.data['portal_duplicate_report']['duplicate_event_id_removed'],
            1)


if __name__ == '__main__':
    unittest.main()
