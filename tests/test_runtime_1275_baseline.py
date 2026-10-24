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

    def test_formal_install_rechecks_staged_copies_before_any_commit(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'source'
            dest = Path(td) / 'formal'
            source.mkdir()
            raw_data = source / 'data.zip'
            raw_eve = source / 'eve.zip'
            raw_data.write_bytes(b'staged-data')
            raw_eve.write_bytes(b'staged-eve')
            fake = SimpleNamespace(revision=1275, items={}, recipes={}, scene_ids=set())
            with patch('wlre.services.world.preview_1275.load_preview',
                       side_effect=[fake, ValueError('staged copy corrupted')]) as check:
                with self.assertRaisesRegex(ValueError, 'staged copy'):
                    runtime_1275.install(
                        raw_data, raw_eve, base=dest, check_only=False)
            self.assertEqual(check.call_count, 2)
            self.assertFalse((dest / runtime_1275.DATA_FILE).exists())
            self.assertFalse((dest / runtime_1275.EVE_FILE).exists())
            self.assertFalse(list(dest.glob('*.tmp')))

    def test_formal_install_never_overwrites_existing_archive(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'source'
            dest = Path(td) / 'formal'
            source.mkdir()
            dest.mkdir()
            raw_data = source / 'data.zip'
            raw_eve = source / 'eve.zip'
            raw_data.write_bytes(b'new data')
            raw_eve.write_bytes(b'new eve')
            (dest / runtime_1275.DATA_FILE).write_bytes(b'existing')
            fake = SimpleNamespace(revision=1275, items={}, recipes={}, scene_ids=set())
            with patch('wlre.services.world.preview_1275.load_preview',
                       return_value=fake):
                with self.assertRaises(FileExistsError):
                    runtime_1275.install(
                        raw_data, raw_eve, base=dest, check_only=False)
            self.assertEqual((dest / runtime_1275.DATA_FILE).read_bytes(), b'existing')
            self.assertFalse((dest / runtime_1275.EVE_FILE).exists())

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

    def test_bad_recipe_source_does_not_modify_previous_catalog(self):
        original = dict(RECIPES)
        with self.assertRaises(ValueError):
            activate_1275_recipes(SimpleNamespace(
                revision=1275, recipes={1: {'item_id': 1}}, items={}))
        self.assertEqual(RECIPES, original)


if __name__ == '__main__':
    unittest.main()
