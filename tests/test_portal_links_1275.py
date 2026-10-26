"""1275 source scene, StageMapData, EveDoorLinks and NewDoor cross-proof."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.services.world.portal_links_1275 import (
    PortalLinkSourceError, parse_stage_map_portals,
    parse_eve_door_links, verified_portal_destinations,
    read_only_portal_destinations)
from wlre.services.world.portals import Portals
from wlre.services.world.portal_policy import destination_problem
from wlre.features.portals.panel import PortalInteractionMixin
from wlre.services.world.portal_travel import PortalTravel
from wlre.core.state import State


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


def position_map():
    return {(12170, 1): {
        'scene': 12170, 'index': 1,
        'x': 5701, 'y': 3230,
        'position_verified': True,
        'source_kind': '1275_eve_door_links_grid_scaled',
    }}


class PortalLinks1275Test(unittest.TestCase):
    def test_official_binary_marker_and_utf16_map_link_layout(self):
        rows = parse_stage_map_portals(stage_rows(
            (12170, 2, 0, 1, 5701, 3230, 10000, 0)))
        self.assertEqual(rows[(12170, 1)]['name_id'], 10000)
        link = parse_eve_door_links(link_bytes())
        self.assertEqual(link[12170][0]['destination'], 12171)

    def test_unique_three_source_identity_produces_destination(self):
        mapping = verified_mapping()
        self.assertEqual(mapping[(12170, 1)]['destination'], 12171)
        self.assertTrue(mapping[(12170, 1)]['destination_verified'])
        self.assertFalse(mapping[(12170, 1)]['trigger_verified'])
        self.assertEqual(verified_mapping(marker_x=5702)[(12170, 1)]['destination'], 12171)
        self.assertEqual(verified_mapping(marker_index=2), {})
        self.assertEqual(verified_mapping(link_scene=12172), {})
        self.assertEqual(verified_mapping(link_destination=12000), {})

    def test_destination_label_never_requires_eve_grid_and_link_grid_to_match(self):
        # Official Lua uses (SceneID, EvtID) to resolve EveDoorLinks. Its
        # grid-space XY is NOT expected to equal Eve.NewDoor event XY.
        marker = stage_rows((12170, 2, 0, 1, 21, 31, 0, 0))
        link = link_bytes(12170, 12171, x=200, y=300)
        doors = {12170: [{'index': 1, 'x': 5701, 'y': 3230}]}
        display = read_only_portal_destinations(
            marker, link, doors, {12170, 12171})
        self.assertEqual(display, {(12170, 1): 12171})
        # Scene/EvtID provides the link. Event/marker/link coordinates need
        # not be equal; projected position remains a separate action guard.
        binding = verified_portal_destinations(marker, link, doors, {12170, 12171})
        self.assertEqual(binding[(12170, 1)]['destination'], 12171)
        self.assertEqual(binding[(12170, 1)]['event_x'], 5701)
        self.assertEqual(binding[(12170, 1)]['x'], 200)
        runtime = SimpleNamespace(
            doors=doors, portal_display_destinations=display,
            portal_destinations={},
            scene_names={12170: '瑪雅野豬叢林二',
                         12171: '瑪雅野豬叢林三'})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                   'wlre.services.world.runtime_1275.active_runtime',
                   return_value=runtime):
            row = Portals().for_scene(12170)[0]
        self.assertIn('瑪雅野豬叢林三(12171)', row['name'])
        self.assertIn('連線名稱參考', row['name'])
        self.assertFalse(row['destination_verified'])
        self.assertIsNone(row['destination'])
        self.assertFalse(row['direct_eligible'])

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
        self.assertEqual(verified_portal_destinations(
            stage_rows((12170, 2, 0, 1, 20, 30, 0, 0)), link_bytes(),
            {12170: [{'index': 1, 'x': 42, 'y': 64},
                     {'index': 1, 'x': 43, 'y': 64}]}, {12170, 12171}), {})

    def test_ui_uses_verified_destination_name_but_never_sends(self):
        mapping = verified_mapping()
        runtime = SimpleNamespace(
            doors={12170: [{'index': 1, 'x': 5701, 'y': 3230, 'event_ids': []}]},
            portal_destinations=mapping,
            portal_positions=position_map(),
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
        self.assertTrue(row['direct_eligible'])
        self.assertEqual(row['direct_door_index'], 1)
        self.assertIsNone(destination_problem(row, SimpleNamespace(
            has_image=lambda scene: scene == 12171)))
        self.assertIsNotNone(destination_problem(row, SimpleNamespace(
            has_image=lambda scene: False)))
        self.assertEqual(Portals.direct_target(row, 12170), 1)
        with self.assertRaises(ValueError):
            Portals.direct_target(row, 12171)

    def test_validated_route_click_sends_once_without_confirmation_popup(self):
        mapping = verified_mapping()
        runtime = SimpleNamespace(
            doors={12170: [{'index': 1, 'x': 5701, 'y': 3230}]},
            portal_destinations=mapping,
            portal_positions=position_map(),
            scene_names={12171: '瑪雅野豬叢林三'})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            catalog = Portals()
        row = catalog.for_scene(12170)[0]
        page = PortalInteractionMixin()
        page.selected_portal = row
        page.portals = catalog
        page.maps = SimpleNamespace(has_image=lambda scene: scene == 12171)
        page.state = {'player': {'scene': 12170}}
        page.portal_status = Mock()
        page.on_portal = Mock()
        with patch('wlre.features.portals.panel.messagebox.askyesno',
                   return_value=False) as confirm:
            self.assertTrue(page.go_portal())
            confirm.assert_not_called()
        page.on_portal.assert_called_once_with(row['id'])

        for key in ('battle', 'event_flow'):
            page.on_portal.reset_mock()
            page.state = {'player': {'scene': 12170}, key: {
                'active' if key == 'battle' else 'blocked': True}}
            with patch('wlre.features.portals.panel.messagebox.askyesno') as confirm:
                self.assertFalse(page.go_portal())
                confirm.assert_not_called()
            page.on_portal.assert_not_called()

    def test_confirmed_manual_try_sends_once_then_waits_for_server_scene(self):
        runtime = SimpleNamespace(
            doors={12170: [{'index': 1, 'x': 5701, 'y': 3230}]},
            portal_destinations=verified_mapping(),
            portal_positions=position_map(),
            scene_names={12171: '瑪雅野豬叢林三'})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            catalog = Portals()
        row = catalog.for_scene(12170)[0]
        state = State()
        state.player.update({'role_id': 42, 'scene': 12170,
                             'x': 5701, 'y': 3230})
        move = Mock()
        service = PortalTravel(catalog=catalog)
        # This unit fixture supplies an explicitly checked 1275 destination
        # map; it must not rely on implicit 1262 coordinate-table fallback.
        with patch('wlre.services.world.portal_policy.smallmaps',
                   return_value=SimpleNamespace(has_image=lambda sid: sid == 12171)):
            packets = service.start_direct(state, move, row['id'], now=10.0)
        self.assertEqual(len(packets), 1)
        self.assertEqual((packets[0].main, packets[0].sub), (20, 8))
        self.assertEqual(state.portal_travel['status'], 'awaiting_map')
        self.assertEqual(state.player['scene'], 12170)
        self.assertEqual(service.start_direct(state, move, row['id'], now=11.0), [])
        move.stop.assert_called_once()
        service.observe({'type': 'position_snapshot', 'role_id': 42,
                         'scene': 12171, 'x': 100, 'y': 200}, state, move)
        self.assertEqual(state.portal_travel['status'], 'completed')
        self.assertEqual(state.portal_travel['arrival']['scene'], 12171)
        self.assertEqual(state.player['scene'], 12170)
        self.assertIsNone(service.pending)


if __name__ == '__main__':
    unittest.main()
