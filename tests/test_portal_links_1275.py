"""1275 source scene, StageMapData, EveDoorLinks and NewDoor cross-proof."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.services.world.portal_links_1275 import (
    PortalLinkSourceError, parse_stage_map_portals,
    parse_eve_door_links, verified_portal_destinations)
from wlre.services.world.portals import Portals
from wlre.services.world.portal_policy import destination_problem


def stage_rows(*rows):
    return struct.pack('<i', len(rows)) + b''.join(
        struct.pack('<HBHIHHIB', *row) for row in rows)


def link_bytes(source=12170, destination=12171, x=5701, y=3230):
    text = (f'事件ID={source}\n'
            f'原場景位置[X:{x},Y:{y}][{destination}][X:100,Y:200]\n')
    return text.encode('utf-16-le')


def verified_mapping(*, marker_scene=12170, marker_index=1,
                     marker_x=5701, link_scene=12170,
                     link_destination=12171):
    raw = stage_rows((marker_scene, 2, 0, marker_index,
                      marker_x, 3230, 0, 0))
    links = link_bytes(link_scene, link_destination)
    doors = {12170: [{'index': 1, 'x': 5701, 'y': 3230}]}
    return verified_portal_destinations(
        raw, links, doors, {12170, 12171})


class PortalLinks1275Test(unittest.TestCase):
    def test_official_binary_marker_and_utf16_map_link_layout(self):
        rows = parse_stage_map_portals(stage_rows(
            (12170, 2, 0, 1, 5701, 3230, 10000, 0)))
        self.assertEqual(rows[(12170, 1)]['name_id'], 10000)
        link = parse_eve_door_links(link_bytes())
        self.assertEqual(link[12170][0]['destination'], 12171)

    def test_only_exact_three_source_match_produces_destination(self):
        mapping = verified_mapping()
        self.assertEqual(mapping[(12170, 1)]['destination'], 12171)
        self.assertTrue(mapping[(12170, 1)]['destination_verified'])
        self.assertFalse(mapping[(12170, 1)]['trigger_verified'])
        self.assertEqual(verified_mapping(marker_x=5702), {})
        self.assertEqual(verified_mapping(marker_index=2), {})
        self.assertEqual(verified_mapping(link_scene=12172), {})
        self.assertEqual(verified_mapping(link_destination=12000), {})

    def test_malformed_or_ambiguous_tables_never_authorize(self):
        with self.assertRaises(PortalLinkSourceError):
            parse_stage_map_portals(b'\x01\x00\x00\x00')
        with self.assertRaises(PortalLinkSourceError):
            parse_eve_door_links('invalid'.encode('utf-16-le'))
        duplicated = stage_rows(
            (12170, 2, 0, 1, 5701, 3230, 10000, 0),
            (12170, 2, 0, 1, 5701, 3230, 10000, 0))
        self.assertEqual(verified_portal_destinations(
            duplicated, link_bytes(), {12170: [
                {'index': 1, 'x': 5701, 'y': 3230}]},
            {12170, 12171}), {})

    def test_ui_uses_verified_destination_name_but_never_sends(self):
        mapping = verified_mapping()
        runtime = SimpleNamespace(
            doors={12170: [{'index': 1, 'x': 5701, 'y': 3230, 'event_ids': []}]},
            portal_destinations=mapping,
            scene_names={12170: '瑪雅野豬叢林二', 12171: '瑪雅野豬叢林三'})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
            'wlre.services.world.runtime_1275.active_runtime',
            return_value=runtime):
            row = Portals().for_scene(12170)[0]
        self.assertIn('前往 瑪雅野豬叢林三(12171)', row['name'])
        self.assertNotIn('瑪雅野豬叢林二', row['name'])
        self.assertEqual(row['destination'], 12171)
        self.assertTrue(row['destination_verified'])
        self.assertFalse(row['direct_eligible'])
        self.assertIsNone(row['direct_door_index'])
        self.assertIsNotNone(destination_problem(row))
        with self.assertRaises(ValueError):
            Portals.direct_target(row, 12170)


if __name__ == '__main__':
    unittest.main()
