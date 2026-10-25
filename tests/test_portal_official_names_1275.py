"""1275 official portal NameID is independent of EveDoorLinks availability."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.services.world.portal_links_1275 import verified_portal_names
from wlre.services.world.portals import Portals
from wlre.ui.home_map import HomeMap


def markers(*entries):
    return struct.pack('<i', len(entries)) + b''.join(
        struct.pack('<HBHIHHIB', *item) for item in entries)


class OfficialPortalNames1275(unittest.TestCase):
    def test_official_name_id_is_available_without_eve_door_links(self):
        raw = markers(
            (11016, 2, 0, 1, 2137, 2081, 4030, 0),
            (11016, 2, 0, 2, 2200, 2030, 4031, 0),
            (11016, 2, 0, 3, 2200, 2030, 0, 0),
            (11016, 3, 0, 4, 2200, 2030, 4032, 0),
            (11016, 1, 0, 5, 2200, 2030, 4033, 0))
        names = verified_portal_names(raw, {11016, 12170}, {
            4030: '通往威靈村的入口', 4031: '海灘出口',
            4032: '隱藏傳點', 4033: '怪物名稱'})
        self.assertEqual(names, {
            (11016, 1): '通往威靈村的入口',
            (11016, 2): '海灘出口',
            (11016, 4): '隱藏傳點'})

    def test_official_name_does_not_unlock_transfer(self):
        runtime = SimpleNamespace(
            doors={11016: [
                {'index': 1, 'x': 2137, 'y': 2081},
                {'index': 2, 'x': 2200, 'y': 2030}]},
            scene_names={11016: '新手海灘'},
            portal_names={
                (11016, 1): '通往威靈村的入口',
                (11016, 2): '海灘出口'},
            portal_destinations={},
            portal_metadata_status='destination_links_missing_or_invalid')
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            catalog = Portals()
        rows = catalog.for_scene(11016)
        self.assertEqual([row['name'] for row in rows],
                         ['通往威靈村的入口', '海灘出口'])
        self.assertEqual(catalog.data['portal_name_count'], 2)
        self.assertEqual(catalog.data['destination_count'], 0)
        self.assertEqual(catalog.data['portal_metadata_status'],
                         'destination_links_missing_or_invalid')
        self.assertTrue(all(not row['direct_eligible'] for row in rows))
        self.assertTrue(all(row['destination'] is None for row in rows))

    def test_map_title_uses_scene_name_and_portals_use_official_names(self):
        runtime = SimpleNamespace(
            doors={11016: [{'index': 1, 'x': 2137, 'y': 2081}]},
            scene_names={11016: '新手海灘'},
            portal_names={(11016, 1): '海灘出口'},
            portal_destinations={},
            portal_metadata_status='stage_map_ready')
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            catalog = Portals()
        page = SimpleNamespace(
            portals=catalog, selected_id=11016, image=object(),
            maps=Mock(), npc_index_error=False, npc_index=None,
            map_title=Mock(), portal_list=Mock(), npc_list=Mock(),
            monster_list=Mock(), npc_message=Mock(), portal_status=Mock(),
            update_portal_button=Mock())
        with patch('wlre.ui.home_map.scene_npcs', return_value=[]):
            HomeMap.refresh_portals(page)
        page.map_title.set.assert_called_once_with('小地圖｜新手海灘(11016)')
        self.assertIn('海灘出口', page.portal_list.insert.call_args_list[0].args[1])
        self.assertIn('1 個傳點有正式文字名稱',
                      page.portal_status.set.call_args.args[0])

    def test_missing_stage_map_is_explained_not_silently_treated_as_no_name_id(self):
        runtime = SimpleNamespace(
            doors={11016: [{'index': 1, 'x': 2137, 'y': 2081}]},
            scene_names={11016: '新手海灘'}, portal_names={},
            portal_metadata_status='missing_stage_map')
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            catalog = Portals()
        self.assertEqual(catalog.for_scene(11016)[0]['name'],
                         '傳點 #1（官方名稱未取得）')
        self.assertEqual(catalog.data['portal_metadata_status'],
                         'missing_stage_map')


if __name__ == '__main__':
    unittest.main()
