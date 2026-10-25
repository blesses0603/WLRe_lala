"""1275 portal recovery: show verified Eve positions, never authorize C20-8."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.features.portals.panel import PortalInteractionMixin
from wlre.services.world.portal_policy import allowed_rows, destination_problem
from wlre.services.world.portals import Portals
from wlre.ui.home_map import HomeMap


SCENE = 12170


def official_doors():
    runtime = SimpleNamespace(doors={SCENE: [
        {'index': 7, 'x': 5701, 'y': 3230, 'event_ids': [2]},
        {'index': 13, 'x': 6012, 'y': 3265, 'event_ids': [6]},
    ]})
    with patch('wlre.services.world.runtime_1275.baseline_revision',
               return_value='1275'), patch(
            'wlre.services.world.runtime_1275.active_runtime',
            return_value=runtime):
        return Portals()


class Portal1275RecoveryTests(unittest.TestCase):
    def test_verified_1275_eve_doors_are_visible_read_only(self):
        catalog = official_doors()
        self.assertTrue(catalog.data['source_ready'])
        self.assertEqual(catalog.data['door_count'], 2)
        rows = catalog.for_scene(SCENE)
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]['index'], rows[0]['x'], rows[0]['y']),
                         (7, 5701, 3230))
        self.assertTrue(rows[0]['coordinate_valid'])
        self.assertIn('1275 傳點', Portals.label(rows[0]))
        self.assertEqual(rows[0]['id'], '1275:12170:7')
        self.assertIsNone(rows[0]['destination'])
        self.assertFalse(rows[0]['direct_eligible'])
        self.assertIsNone(rows[0]['direct_door_index'])

    def test_unverified_1275_is_visible_even_when_destination_unknown(self):
        catalog = official_doors()
        maps = SimpleNamespace(has_image=Mock(return_value=False))
        rows = allowed_rows(catalog, SCENE, maps, recovery=True)
        self.assertEqual(len(rows), 2)
        maps.has_image.assert_not_called()
        self.assertIn('不會送出', destination_problem(rows[0], maps))
        with self.assertRaises(ValueError):
            catalog.direct_target(rows[0], SCENE)
        with self.assertRaises(ValueError):
            catalog.target(rows[0], SCENE)

    def test_missing_runtime_does_not_resurrect_1262(self):
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                side_effect=ValueError('missing 1275')):
            catalog = Portals()
        self.assertFalse(catalog.data['source_ready'])
        self.assertEqual(catalog.for_scene(SCENE), [])

    def test_malformed_records_do_not_turn_into_live_entries(self):
        runtime = SimpleNamespace(doors={SCENE: [
            {'index': 5}, {'index': '6', 'x': 3, 'y': 4},
            {'index': 7, 'x': -1, 'y': 3},
            {'index': 8, 'x': 70000, 'y': 3},
        ]})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            catalog = Portals()
        rows = catalog.for_scene(SCENE)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['coordinate_valid'])
        self.assertIsNone(rows[0]['x'])
        self.assertIsNone(rows[0]['y'])

    def test_legacy_1262_portal_policy_unchanged(self):
        catalog = SimpleNamespace(data={'source_revision': 1262},
            for_scene=lambda scene: [
                {'destination': 10000, 'direct_eligible': True},
                {'destination': None, 'direct_eligible': False}])
        maps = SimpleNamespace(has_image=lambda scene: scene == 10000)
        self.assertEqual(len(allowed_rows(catalog, SCENE, maps)), 1)
        self.assertEqual(len(allowed_rows(catalog, SCENE, maps, True)), 1)

    def test_select_verified_door_sets_coordinates_but_does_not_travel(self):
        p = official_doors().for_scene(SCENE)[0]
        page = PortalInteractionMixin()
        page.selected_id = SCENE
        page.npc_list = Mock()
        page.portal_list = Mock()
        page.portal_status = Mock()
        page.update_portal_button = Mock()
        page.draw = Mock()
        page.on_pick = Mock(return_value=True)
        page.on_portal = Mock()
        page.on_move = Mock()
        page.list_rows = [p]
        page.select_portal(p)
        page.on_pick.assert_called_once_with(SCENE, 5701, 3230)
        page.on_portal.assert_not_called()
        page.on_move.assert_not_called()
        page.draw.assert_called_once_with()

    def test_manual_transfer_attempt_still_rejected(self):
        row = official_doors().for_scene(SCENE)[0]
        page = PortalInteractionMixin()
        page.selected_portal = row
        page.maps = SimpleNamespace(has_image=lambda scene: True)
        page.state = {'player': {'scene': SCENE}}
        page.portals = official_doors()
        page.portal_status = Mock()
        page.on_portal = Mock()
        self.assertFalse(page.go_portal())
        page.on_portal.assert_not_called()
        self.assertIn('目的地', page.portal_status.set.call_args.args[0])

    def test_prelogin_empty_snapshot_is_refreshed_later(self):
        stale = SimpleNamespace(data={'source_revision': 1275,
            'source_ready': False, 'entities': {}}, for_scene=lambda scene: ())
        fresh = official_doors()
        page = SimpleNamespace(
            portals=stale, image=object(), selected_id=SCENE,
            maps=Mock(), npc_index_error=False, npc_index=None,
            portal_list=Mock(), npc_list=Mock(), monster_list=Mock(),
            npc_message=Mock(), portal_status=Mock(),
            update_portal_button=Mock())
        with patch('wlre.ui.home_map.Portals', return_value=fresh) as reload, patch(
                'wlre.ui.home_map.scene_npcs', return_value=[]):
            HomeMap.refresh_portals(page)
        reload.assert_called_once()
        self.assertEqual(len(page.portal_rows), 2)
        self.assertIn('◇ ', page.portal_list.insert.call_args_list[0].args[1])
        self.assertIn('1275 場景', page.portal_status.set.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
