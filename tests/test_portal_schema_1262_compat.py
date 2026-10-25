"""Reference-contract tests from 1262 Lua, applicable to future verified data."""
import struct
import unittest

from wlre.services.world.portal_schema import (
    PortalSchemaUnrecognized, recognize_portal_source, inspect_stage_map,
    inspect_eve_door_links, inspect_door_link_data, parse_door_link_data,
    STAGE_MAP_LAYOUT, EVE_LINKS_LAYOUT, DOOR_LINK_LAYOUT)
from wlre.services.world.portal_links_1275 import verified_portal_names


def stage_map(*rows):
    return struct.pack('<i', len(rows)) + b''.join(
        struct.pack('<HBHIHHIB', *row) for row in rows)


def door_links(*rows):
    return struct.pack('<i', len(rows)) + b''.join(
        struct.pack('<HHHHHH', *row) for row in rows)


def eve_links():
    return ('事件ID=11016\n'
            '原場景位置[X:200,Y:300][11017][X:100,Y:200]\n'
            '事件ID=11017\n'
            '原場景位置[X:3,Y:4][11016][X:200,Y:300]\n'
            ).encode('utf-16-le')


class Portal1262LayoutRecognition(unittest.TestCase):
    def test_stage_map_fields_match_1262_lua_without_hardcoding_revision(self):
        raw = stage_map(
            (11016, 2, 0, 1, 20, 30, 92000, 1),
            (11016, 3, 0, 2, 40, 60, 92001, 2),
            (11016, 4, 11017, 3, 70, 80, 92002, 3),
            (11017, 0, 0, 4, 90, 100, 92003, 4))
        shape = recognize_portal_source('StageMapData_C', raw)
        self.assertEqual(shape['schema'], STAGE_MAP_LAYOUT)
        self.assertEqual(shape['record_count'], 4)
        self.assertEqual(shape['portal_records'], 2)
        self.assertEqual(shape['kind_counts'][4], 1)
        self.assertFalse(shape['can_send_packets'])
        self.assertEqual(verified_portal_names(
            raw, {11016, 11017},
            {92000: '新手海灘出口', 92001: '隱藏通道'}),
            {(11016, 1): '新手海灘出口',
             (11016, 2): '隱藏通道'})

    def test_eve_door_links_is_utf16_text_not_binary_door_link_data(self):
        result = recognize_portal_source('EveDoorLinks', eve_links())
        self.assertEqual(result['schema'], EVE_LINKS_LAYOUT)
        self.assertEqual(result['scene_count'], 2)
        self.assertEqual(result['link_count'], 2)
        self.assertFalse(result['can_send_packets'])
        self.assertEqual(recognize_portal_source(
            'DoorLinkData_C', eve_links())['status'],
            'layout_unrecognized')

    def test_binary_door_link_data_is_twelve_bytes_per_record(self):
        raw = door_links(
            (11016, 200, 300, 11017, 100, 200),
            (11017, 3, 4, 11016, 200, 300))
        shape = inspect_door_link_data(raw)
        self.assertEqual(shape['schema'], DOOR_LINK_LAYOUT)
        self.assertEqual(shape['record_count'], 2)
        self.assertEqual(parse_door_link_data(raw)[0]['destination_scene'], 11017)
        self.assertFalse(shape['can_send_packets'])
        self.assertEqual(recognize_portal_source(
            'EveDoorLinks', raw)['status'], 'layout_unrecognized')

    def test_future_version_structurally_compatible_is_read_only(self):
        # This data has no known package revision; exact binary layout alone
        # permits read-only parsing but never a protocol/manifest promotion.
        raw = stage_map((12170, 2, 0, 1, 12, 45, 85000, 0))
        verdict = recognize_portal_source('StageMapData_C', raw)
        self.assertEqual(verdict['status'], 'recognized')
        self.assertFalse(verdict['can_send_packets'])
        self.assertEqual(verdict['schema'], STAGE_MAP_LAYOUT)

    def test_unknown_or_shifted_future_layout_rejected_without_guessing(self):
        valid = stage_map((11016, 2, 0, 1, 1, 2, 10000, 0))
        bad_cases = [
            valid + b'\x00',
            valid[:-1],
            stage_map((11016, 9, 0, 1, 1, 2, 10000, 0)),
            stage_map((0, 2, 0, 1, 1, 2, 10000, 0)),
            struct.pack('>i', 1) + valid[4:],
        ]
        for raw in bad_cases:
            with self.subTest(size=len(raw), suffix=raw[-4:]):
                self.assertEqual(recognize_portal_source(
                    'StageMapData_C', raw)['status'], 'layout_unrecognized')
        self.assertEqual(recognize_portal_source(
            'OtherTable', valid)['status'], 'unsupported_table')

    def test_bad_binary_routes_never_infer_event_index(self):
        data = door_links((11016, 1, 2, 0, 3, 4))
        with self.assertRaises(PortalSchemaUnrecognized):
            parse_door_link_data(data)
        self.assertEqual(recognize_portal_source(
            'DoorLinkData_C', data)['status'], 'layout_unrecognized')

    def test_completely_unknown_sources_never_promote(self):
        for source, raw in [('StageMapData_C', b'\0' * 19),
                            ('EveDoorLinks', b'garbled'),
                            ('DoorLinkData_C', b'\0' * 5)]:
            with self.subTest(source=source):
                report = recognize_portal_source(source, raw)
                self.assertEqual(report['status'], 'layout_unrecognized')
                self.assertIsNone(report['schema'])
                self.assertFalse(report['can_send_packets'])


if __name__ == '__main__':
    unittest.main()
