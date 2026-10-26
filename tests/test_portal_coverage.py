"""All scene audits include zero-door scenes and orphaned source references."""
import struct
import unittest
from wlre.services.world.portal_coverage import audit_portal_coverage


def markers(*rows):
    return struct.pack('<i', len(rows)) + b''.join(struct.pack('<HBHIHHIB', *row) for row in rows)


class PortalCoverage(unittest.TestCase):
    def test_every_scene_and_orphaned_reference_is_included(self):
        stages = {scene: {} for scene in range(1, 1263)}
        stage = markers((1, 2, 0, 1, 20, 30, 0, 0), (1, 2, 0, 2, 40, 50, 0, 0))
        links = ('事件ID=1\n原場景位置[X:2,Y:3][2][X:4,Y:5]\n'
                 '原場景位置[X:4,Y:5][2][X:4,Y:5]\n'
                 '原場景位置[X:6,Y:7][2][X:4,Y:5]\n').encode('utf-16-le')
        report = audit_portal_coverage({1: [{'index': 1}, {'index': 9}]}, stages,
                                      stage, links, {(1, 1): {}}, {(1, 1): {}})
        self.assertEqual(report['scene_count'], 1262)
        self.assertTrue(report['all_sources_available'])
        self.assertEqual(report['scenes'][-1]['scene'], 1262)
        rows = {row['index']: row for row in report['scenes'][0]['details']}
        self.assertEqual(rows[1]['issues'], [])
        self.assertIn('missing_eve_door', rows[2]['issues'])
        self.assertIn('missing_stage_marker', rows[3]['issues'])
        self.assertEqual(rows[9]['category'], 'event_container_only')
        self.assertEqual(report['unresolved_portals'], 2)
        self.assertFalse(report['can_send_packets'])

    def test_hidden_portals_are_separate_from_missing_normal_links(self):
        report = audit_portal_coverage({1: [{'index': 1}]}, {1},
            markers((1, 3, 0, 1, 20, 30, 0, 0)), '事件ID=1\n'.encode('utf-16-le'))
        self.assertEqual(report['scenes'][0]['details'][0]['category'], 'hidden_portal')
        self.assertEqual(report['unresolved_portals'], 0)

    def test_duplicate_marker_is_not_silently_dropped_by_display_parser(self):
        row = (1, 2, 0, 7, 20, 30, 0, 0)
        report = audit_portal_coverage({}, {1}, markers(row, row), '事件ID=1\n'.encode('utf-16-le'))
        details = report['scenes'][0]['details']
        self.assertEqual(details[0]['index'], 7)
        self.assertIn('duplicate_stage_marker', details[0]['issues'])

    def test_absent_or_invalid_sources_do_not_claim_complete_coverage(self):
        for raw in (None, b'invalid'):
            report = audit_portal_coverage({1: [{'index': 1}]}, {1, 2}, raw)
            self.assertFalse(report['all_sources_available'])
            self.assertEqual(report['scene_count'], 2)

    def test_unknown_destination_remains_visible_in_the_audit(self):
        raw = '事件ID=1\n原場景位置[X:2,Y:3][99][X:4,Y:5]\n'.encode('utf-16-le')
        report = audit_portal_coverage({1: [{'index': 1}]}, {1},
            markers((1, 2, 0, 1, 20, 30, 0, 0)), raw)
        self.assertEqual(report['scene_count'], 2)
        self.assertFalse(report['scenes'][1]['in_scene_table'])
        self.assertIn('unknown_destination_scene', report['scenes'][0]['details'][0]['issues'])
