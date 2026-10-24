"""1275 official revision baseline and no-1262-fallback runtime tests."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wlre.services.resource_compatibility import load_supported_resources
from wlre.services.world import runtime_1275
from wlre.services.world.npc_catalog import NPCIndex
from wlre.services.world.npc_interact import NPCInteractIndex
from wlre.services.world.npc_talk import load_catalog as load_talks
from wlre.services.world.npc_item_data import item_catalog
from wlre.services.world.portals import Portals
from wlre.services.items.crafting import RECIPES, activate_1275_recipes
from wlre.services.items.catalog import item_name
from wlre.services.world.npc_localization import load_text_data, load_battle_talk
from wlre.services.world.map_names import data as map_data, map_label, model_label
from wlre.services.instance_browser import official_catalog as instance_catalog
from wlre.services.expedition.data import load_catalog as expedition_catalog
from wlre.services.world.preview_1275 import parse_npc_battle_talk_1275, PreviewError
from wlre.services.world.coordinates import Coordinates
from wlre.services.world.navigation import NavigationError


class Default1275Tests(unittest.TestCase):
    def test_new_official_revision_is_pinned_in_main(self):
        record = load_supported_resources()
        self.assertEqual(record['packages']['DataPackage']['revision'], '1275')
        self.assertEqual(record['packages']['MainPackage']['revision'], '1275')
        self.assertEqual(record['packages']['DataPackage']['manifest'],
                         '1275_2026_10_21_18_27_33_84')
        self.assertEqual(record['packages']['MainPackage']['manifest'],
                         '1275_2026_10_21_18_29_38_49')

    def test_uninstalled_data_never_falls_back_to_1262_npc(self):
        runtime_1275._default_runtime.cache_clear()
        with tempfile.TemporaryDirectory() as td:
            with patch.object(runtime_1275, 'resource_dir', return_value=Path(td)):
                for fn in (NPCIndex, NPCInteractIndex, load_talks, item_catalog):
                    with self.subTest(fn=fn.__name__), self.assertRaises(
                            runtime_1275.Runtime1275Unavailable):
                        fn()
        runtime_1275._default_runtime.cache_clear()

    def test_npc_and_shop_take_pinned_1275_index(self):
        row = {'index': 12, 'npc_id': 888, 'x': 11, 'y': 12, 'event_count': 1}
        runtime = SimpleNamespace(
            npc_index=SimpleNamespace(scenes={'10000': [row]}),
            interact_index=SimpleNamespace(scenes={10000: {3: {
                'index': 3, 'form_kind': 3, 'items': [], 'link_number': 0}}}),
            talks={1: '新資料'}, items={888: {'name': '新版道具'}})
        with patch.object(runtime_1275, 'active_runtime', return_value=runtime):
            self.assertEqual(NPCIndex().for_scene(10000)[0]['npc_id'], 888)
            self.assertEqual(NPCInteractIndex().get(10000, 3)['form_kind'], 3)
            self.assertEqual(load_talks()[1], '新資料')
            item_catalog.cache_clear()
            self.assertEqual(item_catalog()[888]['name'], '新版道具')
        item_catalog.cache_clear()

    def test_legacy_portals_not_reused_when_1275_selected(self):
        runtime = SimpleNamespace(doors={10000: [{'index': 1}]})
        with patch.object(runtime_1275, 'active_runtime', return_value=runtime):
            catalog = Portals()
            self.assertEqual(catalog.for_scene(10000), [])
            self.assertEqual(catalog.data['door_count'], 1)
            self.assertEqual(catalog.data['source_revision'], 1275)

    def test_recipe_catalog_swaps_in_place_with_validated_itemdata(self):
        original = dict(RECIPES)
        runtime = SimpleNamespace(
            revision=1275,
            recipes={i: {'item_id': i, 'design_id': 0, 'time_id': 0,
                         'limit_kind': 0} for i in range(1, 1033)},
            items={i: {'open_used': 0} for i in range(1, 1033)})
        try:
            ref = RECIPES
            self.assertEqual(activate_1275_recipes(runtime), 1032)
            self.assertIs(ref, RECIPES)
            self.assertEqual(RECIPES['1']['open_used'], 0)
        finally:
            RECIPES.clear()
            RECIPES.update(original)

    def test_general_item_names_use_1275_and_never_1262(self):
        runtime = SimpleNamespace(items={39053: {'name': '新版來源藥水'}})
        with patch.object(runtime_1275, 'active_runtime', return_value=runtime):
            self.assertEqual(item_name(39053), '新版來源藥水')
            self.assertEqual(item_name(12345), '物品12345')
        with patch.object(runtime_1275, 'active_runtime',
                          side_effect=runtime_1275.Runtime1275Unavailable('missing')):
            self.assertEqual(item_name(39053), '物品39053')

    def test_localized_text_and_battle_talk_are_verified_1275(self):
        runtime = SimpleNamespace(
            texts={1: '1275 確認'},
            battle_talk={1: [{'text_id': 1, 'kind': 2,
                              'parameter': 3, 'duration': 4}]})
        with patch.object(runtime_1275, 'active_runtime', return_value=runtime):
            self.assertEqual(load_text_data(), {1: '1275 確認'})
            battle = load_battle_talk()
            self.assertEqual(battle[1][0]['text_id'], 1)
            battle[1][0]['text_id'] = 5
            self.assertEqual(load_battle_talk()[1][0]['text_id'], 1)
        with patch.object(runtime_1275, 'active_runtime',
                          side_effect=runtime_1275.Runtime1275Unavailable('missing')):
            with self.assertRaises(runtime_1275.Runtime1275Unavailable):
                load_battle_talk()

    def test_map_names_resolve_from_verified_1275_stages_and_text(self):
        source = SimpleNamespace(
            stages={10000: {'name_id': 901, 'model_id': 123},
                    10001: {'name_id': 902, 'model_id': 124}},
            texts={901: '新版地圖', 902: '1275 新增場景'})
        map_data.cache_clear()
        try:
            with patch.object(runtime_1275, 'active_runtime', return_value=source):
                self.assertEqual(map_label(10000), '新版地圖(10000)')
                self.assertEqual(map_label(10001), '1275 新增場景(10001)')
                self.assertEqual(model_label(123), '新版地圖(123)')
                self.assertNotIn('10002', map_data()['maps'])
        finally:
            map_data.cache_clear()

    def test_map_names_without_1275_data_never_load_old_map_labels(self):
        map_data.cache_clear()
        try:
            with patch.object(runtime_1275, 'active_runtime',
                              side_effect=runtime_1275.Runtime1275Unavailable('missing')):
                self.assertEqual(map_data(), {'maps': {}, 'models': {}})
                self.assertEqual(map_label(10000), '未知地圖(10000)')
        finally:
            map_data.cache_clear()

    def test_expedition_uses_1275_verified_tasks_and_npcs(self):
        source = SimpleNamespace(expedition_catalog={
            'source_revision': 1275,
            'tasks': {'1': {'name': '1275 任務'}},
            'levels': {'1': {'teams': 2}},
            'npcs': {'1': {'original': 1}}})
        with patch.object(runtime_1275, 'active_runtime', return_value=source):
            c = expedition_catalog()
            self.assertEqual(c['source_revision'], 1275)
            c['tasks']['1']['name'] = '外部汙染'
            self.assertEqual(expedition_catalog()['tasks']['1']['name'], '1275 任務')

    def test_instances_use_new_1275_stages_and_text(self):
        dungeon = {'id': 1, 'kind': 1, 'para_kind': 0, 'map_id': 30012,
                   'npc_id': 41000, 'awards': [{'kind': 10, 'id': 63002, 'value': 5}]}
        source = SimpleNamespace(
            dungeon_records=[dungeon] * 30, cooperative_records=[],
            stages={30012: {'name_id': 901, 'min_level': 10,
                            'min_members': 2, 'max_members': 6,
                            'time_minutes': 15, 'room_capacity': 10,
                            'is_open': True}},
            texts={901: '1275 副本'})
        # All rows duplicate intentionally: the validator must not certify them.
        instance_catalog.cache_clear()
        try:
            with patch.object(runtime_1275, 'active_runtime', return_value=source):
                with self.assertRaises(ValueError):
                    instance_catalog()
        finally:
            instance_catalog.cache_clear()

    def test_1275_does_not_build_routes_using_old_1262_navigation(self):
        with self.assertRaisesRegex(NavigationError, '1275'):
            Coordinates().mapping(10000)

    def test_bad_npc_battle_talk_1275_sha_is_rejected(self):
        with self.assertRaises(PreviewError):
            parse_npc_battle_talk_1275(b'\\x00' * 944)

    def test_bad_recipe_source_does_not_modify_previous_catalog(self):
        original = dict(RECIPES)
        with self.assertRaises(ValueError):
            activate_1275_recipes(SimpleNamespace(
                revision=1275, recipes={1: {'item_id': 1}}, items={}))
        self.assertEqual(RECIPES, original)


if __name__ == '__main__':
    unittest.main()
