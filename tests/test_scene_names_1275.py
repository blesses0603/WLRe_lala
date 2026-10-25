"""1275 portal names must match verified source scenes, never inferred exits."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.services.world.scene_names_1275 import bind_scene_names, source_scene_label
from wlre.services.world.portals import Portals
from wlre.ui.home_map import HomeMap


class SceneNames1275Tests(unittest.TestCase):
    def test_bind_names_from_exact_scene_name_id_and_text_id(self):
        stages = {
            12170: {'name_id': 301},
            12171: {'name_id': 302},
            12172: {'name_id': 400},
            12173: {'name_id': 0},
            12174: {'name_id': 401},
        }
        texts = {301: '瑪雅野豬叢林二', 302: '瑪雅野豬叢林三',
                 400: ' ', 401: chr(0) + 'broken'}
        expected = {12170: '瑪雅野豬叢林二', 12171: '瑪雅野豬叢林三'}
        self.assertEqual(bind_scene_names(stages, texts), expected)
        self.assertEqual(source_scene_label(12170, expected),
                         '瑪雅野豬叢林二(12170)')
        self.assertEqual(source_scene_label(12174, expected), '場景 12174')

    def test_official_1275_scene_label_matches_door_source_not_destination(self):
        runtime = SimpleNamespace(
            scene_names={12170: '瑪雅野豬叢林二', 12171: '瑪雅野豬叢林三'},
            doors={
                12170: [{'index': 7, 'x': 5701, 'y': 3230, 'event_ids': [5]}],
                12171: [{'index': 7, 'x': 100, 'y': 200, 'event_ids': []}],
            },
        )
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            catalog = Portals()
        source_a = catalog.for_scene(12170)[0]
        source_b = catalog.for_scene(12171)[0]
        self.assertEqual(source_a['name'], '傳點 #7（目的地待確認）')
        self.assertEqual(source_b['name'], '傳點 #7（目的地待確認）')
        self.assertNotEqual(source_a['id'], source_b['id'])
        self.assertEqual(source_a['source_scene_label'], '瑪雅野豬叢林二(12170)')
        self.assertTrue(source_a['source_scene_name_known'])
        self.assertEqual(source_a['destination_label'], '目的地未確認')
        self.assertIsNone(source_a['destination'])
        self.assertFalse(source_a['direct_eligible'])

    def test_missing_1275_scene_text_never_uses_1262_guess(self):
        runtime = SimpleNamespace(doors={12170: [
            {'index': 7, 'x': 5701, 'y': 3230, 'event_ids': []}]})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            catalog = Portals()
        row = catalog.for_scene(12170)[0]
        self.assertEqual(row['name'], '傳點 #7（目的地待確認）')
        self.assertFalse(row['source_scene_name_known'])
        self.assertNotIn('瑪雅野豬叢林二', row['name'])

    def test_map_title_and_portal_list_use_identical_verified_1275_name(self):
        runtime = SimpleNamespace(
            scene_names={12170: '瑪雅野豬叢林二'},
            doors={12170: [{'index': 7, 'x': 5701, 'y': 3230, 'event_ids': []}]})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            catalog = Portals()
        page = SimpleNamespace(
            portals=catalog, selected_id=12170, image=object(), maps=Mock(),
            npc_index_error=False, npc_index=None, map_title=Mock(),
            portal_list=Mock(), npc_list=Mock(), monster_list=Mock(),
            npc_message=Mock(), portal_status=Mock(), update_portal_button=Mock())
        with patch('wlre.ui.home_map.scene_npcs', return_value=[]):
            HomeMap.refresh_portals(page)
        page.map_title.set.assert_called_once_with('小地圖｜瑪雅野豬叢林二(12170)')
        listed = page.portal_list.insert.call_args_list[0].args[1]
        self.assertNotIn('瑪雅野豬叢林二(12170)', listed)
        self.assertIn('傳點 #7', listed)
        self.assertIn('所在場景 瑪雅野豬叢林二(12170)',
                      page.portal_status.set.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
