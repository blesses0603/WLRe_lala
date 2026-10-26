"""P3: do not revive retired 1262 exits while using official 1275.

These tests deliberately leave the legacy portals.json untouched. Removing
historical navigation from the live UI must not corrupt audit fixtures.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.core.state import State
from wlre.network.wire import ProtocolError
from wlre.services.world.portals import Portals
from wlre.services.world.portal_travel import PortalTravel
from wlre.ui.home_map import HomeMap


SCENE = 60001


def new_catalog():
    return SimpleNamespace(
        data={'portals': {'60001': [{
            'id': '1275:60001:7', 'name': '新版出口', 'scene': SCENE,
            'kind': 'door', 'source_revision': 1275,
            'coordinate_valid': False, 'destination_verified': False,
            'direct_eligible': False, 'direct_door_index': None,
            'x': None, 'y': None,
        }]}, 'entities': {}, 'source_revision': 1275,
            'source_ready': True, 'portal_metadata_status': 'missing_stage_map'},
        for_scene=lambda scene: [{
            'id': '1275:60001:7', 'name': '新版出口',
            'source_revision': 1275, 'direct_eligible': False,
        }] if scene == SCENE else [])


def old_catalog():
    return SimpleNamespace(
        data={'portals': {'60001': [
            {'id': '1262:60001:7', 'name': '舊版出口',
             'source_revision': 1262, 'direct_eligible': True}]},
              'source_revision': 1262, 'entities': {}},
        for_scene=lambda scene: [{
            'id': '1262:60001:7', 'name': '舊版出口',
            'source_revision': 1262, 'direct_eligible': True,
        }] if scene == SCENE else [])


class RemoveOldPortalsTests(unittest.TestCase):
    def test_default_catalog_never_reads_legacy_when_revision_old(self):
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1262'), patch.object(
                   Path, 'read_text', side_effect=AssertionError('read old!')):
            result = Portals()
        self.assertEqual(result.data['source_revision'], 1275)
        self.assertFalse(result.data['source_ready'])
        self.assertEqual(result.for_scene(SCENE), [])
        self.assertEqual(result.data['portal_metadata_status'],
                         'legacy_portals_disabled')

    def test_unversioned_legacy_snapshot_also_gets_replaced(self):
        stale = old_catalog()
        stale.data.pop('source_revision')
        page = SimpleNamespace(
            portals=stale, image=object(), selected_id=SCENE,
            maps=Mock(), projection=None, npc_index_error=False, npc_index=None,
            portal_list=Mock(), npc_list=Mock(), monster_list=Mock(),
            npc_message=Mock(), portal_status=Mock(),
            update_portal_button=Mock())
        with patch('wlre.ui.home_map.Portals', return_value=new_catalog()) as reload, \
                patch('wlre.ui.home_map.scene_npcs', return_value=[]):
            HomeMap.refresh_portals(page)
        reload.assert_called_once_with()
        self.assertEqual(page.portal_rows, [])
        self.assertEqual(page.portals.data['source_revision'], 1275)

    def test_mixed_legacy_row_under_1275_catalog_cannot_send_packets(self):
        current = new_catalog()
        current.for_scene = lambda scene: [{
            'id': '1262:60001:7', 'scene': SCENE, 'source_revision': 1262,
            'direct_door_index': 7, 'destination': SCENE,
            'direct_eligible': True, 'destination_verified': True,
        }] if scene == SCENE else []
        travel = PortalTravel(catalog=current)
        state = State()
        state.player = {'scene': SCENE, 'role_id': 17}
        move = Mock()
        with self.assertRaises(ProtocolError):
            travel.start_direct(state, move, '1262:60001:7', 10.0)
        move.stop.assert_not_called()
        self.assertIsNone(travel.pending)

    def test_explicit_archived_fixture_is_still_readable(self):
        # Retain historical evidence without admitting it to the live list.
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / 'archived.json'
            filename.write_text(json.dumps({
                'portals': {'60001': [{'id': '1262:60001:7'}]},
                'audit': []}), encoding='utf8')
            result = Portals(path=filename)
        self.assertEqual(len(result.for_scene(SCENE)), 1)

    def test_reloading_map_replaces_old_catalog_instead_of_merging(self):
        page = SimpleNamespace(
            portals=old_catalog(), image=object(), selected_id=SCENE,
            maps=Mock(), projection=None, npc_index_error=False, npc_index=None,
            portal_list=Mock(), npc_list=Mock(), monster_list=Mock(),
            npc_message=Mock(), portal_status=Mock(),
            update_portal_button=Mock())
        current = new_catalog()
        with patch('wlre.ui.home_map.Portals', return_value=current) as reload, \
                patch('wlre.ui.home_map.scene_npcs', return_value=[]):
            HomeMap.refresh_portals(page)
        reload.assert_called_once_with()
        self.assertIs(page.portals, current)
        self.assertNotIn('舊版出口', str(page.portal_list.insert.call_args_list))
        self.assertEqual(page.list_rows, [])
        self.assertIn('1275 場景', page.portal_status.set.call_args.args[0])

    def test_cached_legacy_cannot_trigger_direct_teleport(self):
        state = State()
        state.player = {'scene': SCENE, 'role_id': 17}
        travel = PortalTravel(catalog=old_catalog())
        new = new_catalog()
        with patch('wlre.services.world.portal_travel.Portals',
                   return_value=new) as reload:
            with self.assertRaises(ProtocolError):
                travel.start_direct(state, Mock(), '1262:60001:7', 10.0)
        reload.assert_called_once_with()
        self.assertIs(travel.catalog, new)
        self.assertIsNone(travel.pending)
        self.assertEqual(state.portal_travel, {})

    def test_cached_legacy_cannot_start_automatic_walk(self):
        state = State()
        state.player = {'scene': SCENE, 'role_id': 17}
        travel = PortalTravel(catalog=old_catalog())
        move = Mock()
        with patch('wlre.services.world.portal_travel.Portals',
                   return_value=new_catalog()):
            with self.assertRaises(ProtocolError):
                travel.start(state, move, '1262:60001:7', 10.0)
        move.start.assert_not_called()
        self.assertIsNone(travel.pending)


if __name__ == '__main__':
    unittest.main()
