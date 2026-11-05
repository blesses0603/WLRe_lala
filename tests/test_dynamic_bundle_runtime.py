"""Full runtime integration from synthetic verified manifests and TextAssets."""
from contextlib import ExitStack, closing
from copy import deepcopy
import hashlib
import sqlite3
import struct
import unittest
from unittest.mock import patch

from test_eve_v115 import fixture as eve_fixture
from test_itemdata_v1 import sample as item_record
from test_npc_talk_v058 import sample_record as talk_record
import test_official_catalog_pipeline as pipeline_fixtures
from wlre.network.wire import Writer
from wlre.services.world import dynamic_bundle_runtime as dynamic
from wlre.services.world.bundle_runtime_1275 import _REQUIRED_TABLES, _ASSET_ROOT
from wlre.services.world.official_catalog_store import store_official_catalog, active_official_catalog
from wlre.services.world.catalog_adapters import FEATURES, ParsedCatalog


class DynamicBundleRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = pipeline_fixtures.OfficialPipelineTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.snapshot = deepcopy(self.fixture.snapshot)
        # Different package revisions are deliberately supported.
        self.snapshot['packages']['DataPackage'] = '1286_2026_10_29_13_42_37_94'
        self.snapshot['packages']['MainPackage'] = '1284_2026_10_28_19_50_04_11'
        from dataclasses import replace
        self.manifests = {}
        for name, old in self.fixture.manifests.items():
            index = deepcopy(old.index)
            index['header']['package_version'] = self.snapshot['packages'][name]
            if name == 'DataPackage':
                index['assets'] = [{'path': _ASSET_ROOT + t + '.bytes',
                                    'bundle_name': index['bundles'][0]['name']}
                                   for t in _REQUIRED_TABLES]
            self.manifests[name] = replace(old,
                spec=replace(old.spec, package_version=self.snapshot['packages'][name]), index=index)
        from wlre.services.official_bundle_download import spec_from_manifest
        for name, manifest in self.manifests.items():
            old = self.fixture.manifests[name]
            for row in manifest.index['bundles']:
                original = spec_from_manifest(data_ver=old.spec.data_ver, package=name,
                    index=old.index, name=row['name']).cache_path(self.fixture.bundle_root)
                new = spec_from_manifest(data_ver=manifest.spec.data_ver, package=name,
                    index=manifest.index, name=row['name']).cache_path(self.fixture.bundle_root)
                new.parent.mkdir(parents=True, exist_ok=True)
                new.write_bytes(original.read_bytes())
        recipe = bytearray(33)
        struct.pack_into('<H', recipe, 0, 3874)
        recipe[7] = 1
        struct.pack_into('<H', recipe, 24, 5)
        stage = bytearray(76)
        struct.pack_into('<H', stage, 0, 500)
        struct.pack_into('<I', stage, 4, 10)
        struct.pack_into('<H', stage, 8, 123)
        struct.pack_into('<HH', stage, 52, 1000, 1000)
        npc = bytearray(203)
        struct.pack_into('<H', npc, 1, 9001)
        task = (Writer().u16(1).u8(1).u32(20).u8(1).u32(10).u32(10)
                .u16(300).u8(10).u16(80))
        for _ in range(3): task.u16(0)
        for _ in range(4): task.u16(0).u16(0).u16(0).u16(0)
        task.u32(100)
        for _ in range(3): task.u8(0).u32(0).u32(0)
        task.u16(0).u8(0).u32(0).u32(0).u32(50)
        def text(key, value):
            raw = value.encode('utf-16-le')
            return struct.pack('<IH', key, len(raw)) + raw
        self.raw = {
            'Eve': eve_fixture(),
            'ItemData_C': struct.pack('<i', 1) + item_record(iid=3874),
            'SmithData_C': struct.pack('<iH', 1, 99) + recipe,
            'ScenesData_C': struct.pack('<i', 1) + stage,
            'TalkData_C': struct.pack('<i', 1) + talk_record(),
            'TextData_C': struct.pack('<i', 2) + text(10, '新版任務') + text(20, '新版地區'),
            'AdventureData_C': struct.pack('<i', 1) + task.build(),
            'AdventureLvData_C': struct.pack('<i', 1) + struct.pack('<BIIBBHBB', 1, 0, 0, 2, 1, 0, 0, 0),
            'NpcData_C': struct.pack('<iHH', 1, 0, 0) + npc,
            'NpcCareerData_C': struct.pack('<i', 0),
        }
        self.remote = {'resource_path': self.snapshot['data_ver'],
                       'official_exe_version': self.snapshot['exe_version'],
                       'newer_official_client': False,
                       'packages': {k: {'remote': v} for k, v in self.snapshot['packages'].items()}}
        self.stack = self.enterContext(ExitStack())
        self.stack.enter_context(patch('wlre.services.world.unity_textasset.extract_textasset',
            side_effect=lambda binding, paths, loader=None: self.raw[binding.contract.source_name]))
        self.stack.enter_context(patch.object(dynamic, '_active', None))
        self.stack.enter_context(patch.object(dynamic, '_attempted', False))
        from wlre.services.items.crafting import RECIPES
        saved = deepcopy(RECIPES)
        self.addCleanup(lambda: (RECIPES.clear(), RECIPES.update(saved)))

    def kwargs(self):
        return dict(sync_root=self.root, observe=lambda: deepcopy(self.snapshot),
                    retrieve=lambda spec, cache_root: self.manifests[spec.package])

    def test_full_parsing_activation_and_all_consumers_use_current_data(self):
        runtime = dynamic.activate_for_official(self.remote, **self.kwargs())
        self.assertEqual(runtime.revision, 1286)
        self.assertEqual(runtime.record_counts,
                         dict(npc=1, shops=1, items=1, crafting=1, scenes=1, expedition=1))
        self.assertEqual(runtime.recipe_catalog[0]['recipe_id'], 99)
        self.assertEqual(set(runtime.source_sha256), set(_REQUIRED_TABLES))
        from wlre.services.world.runtime_1275 import active_runtime, baseline_revision
        from wlre.services.world.catalog_source_policy import official_runtime, source_for
        from wlre.services.world.npc_catalog import NPCIndex
        from wlre.services.world.npc_interact import NPCInteractIndex
        from wlre.services.world.npc_talk import load_catalog
        from wlre.services.world.npc_item_data import item_catalog
        from wlre.services.items.catalog import item_name, verified_item_metadata
        from wlre.services.expedition.data import load_active_catalog
        from wlre.services.items.crafting import RECIPES, confirmed_unlocked, recipe_plan
        from wlre.core.state import State
        self.assertIs(active_runtime(), runtime)
        self.assertEqual(baseline_revision(), '1286')
        for feature in ('npc', 'items', 'maps', 'crafting', 'expedition'):
            self.assertIs(official_runtime(feature), runtime)
            self.assertFalse(source_for(feature).gameplay_allowed)
        self.assertEqual(NPCIndex().for_scene(500)[0]['npc_id'], 9001)
        self.assertEqual(NPCInteractIndex().get(500, 8)['form_kind'], 3)
        self.assertIn(411, load_catalog())
        self.assertEqual(item_catalog(), runtime.items)
        self.assertEqual(item_name(3874), '蘋果')
        self.assertEqual(verified_item_metadata(3874)['source_revision'], 1286)
        self.assertEqual(load_active_catalog()['tasks']['1']['name'], '新版任務')
        self.assertTrue(confirmed_unlocked(RECIPES['3874']))
        with self.assertRaisesRegex(ValueError, '帳篷'):
            recipe_plan(State(), 3874, 1)
        self.assertFalse(runtime.can_send_packets)

    def test_daily_tables_use_verified_bundle_then_sqlite_and_real_claim(self):
        from test_daily_task_1275 import sample_daily
        from wlre.services.world.daily_task_catalog import TABLES
        from wlre.core.state import State
        from wlre.network.protocol import decode
        from wlre.network.wire import Packet
        from wlre.services import daily_tasks
        from test_daily_task_runtime import snapshot
        daily=bytearray(sample_daily());struct.pack_into('<I',daily,15,10)
        self.raw.update(DailyTaskData_C=bytes(daily),
                        DailyTaskRewardData_C=struct.pack('<iHBII',1,7,1,20,1)+
                        struct.pack('<BII',10,3874,1)+b'\0'*27)
        manifest=self.manifests['DataPackage']
        manifest.index['assets'].extend(dict(path=_ASSET_ROOT+t+'.bytes',
                        bundle_name=manifest.index['bundles'][0]['name']) for t in TABLES)
        runtime=dynamic.activate_for_official(self.remote,**self.kwargs())
        self.assertIsNotNone(runtime.daily_tasks)
        self.assertEqual(runtime.daily_tasks['tasks'][0]['name'],'新版任務')
        from wlre.services.world.resource_database import read_catalog_tables
        parsed=read_catalog_tables(self.root/'derived_catalogs'/'resource_inventory.sqlite3',runtime.catalog_identity.key,
                                   ('daily_tasks','daily_rewards'))
        self.assertEqual(parsed['daily_tasks']['task_count'],1)
        state=State(phase='world_ready',initial_data_complete=True)
        state.player.update(role_id=1);state.daily_tasks['role_id']=1
        state.inventory.update(ready=True,reliable=True,capacity=10,revision=1,items={})
        state.apply(decode(snapshot()));state.apply(decode(Packet(124,2,b'\x01\x02')))
        self.assertEqual(daily_tasks.tick(state,True,1),[Packet(124,1,b'\x01\x00')])
        # One changed optional schema disables only daily tasks, never the core runtime.
        self.raw['DailyTaskRewardData_C']+=b'!'
        runtime=dynamic.activate_for_official(self.remote,**self.kwargs())
        self.assertIsNone(runtime.daily_tasks)
        self.assertEqual(len(runtime.items),1)

    def test_guild_catalog_uses_verified_sqlite_and_rejects_changed_price_layout(self):
        from test_guild_actions import raw_catalogs
        from wlre.services.world.guild_catalog import TABLES,quote
        self.raw.update(raw_catalogs())
        manifest=self.manifests['DataPackage']
        manifest.index['assets'].extend(dict(path=_ASSET_ROOT+t+'.bytes',
                        bundle_name=manifest.index['bundles'][0]['name']) for t in TABLES)
        runtime=dynamic.activate_for_official(self.remote,**self.kwargs())
        self.assertIsNotNone(runtime.guild_catalog)
        self.assertEqual(quote(runtime.guild_catalog,8,{},False)['price'],150)
        self.raw['FormulaData_C']+=b'!'
        runtime=dynamic.activate_for_official(self.remote,**self.kwargs())
        self.assertIsNone(runtime.guild_catalog)
        self.assertEqual(len(runtime.items),1)

    def test_unknown_smith_layout_and_corrupt_item_table_refuse_activation(self):
        for name in ('SmithData_C', 'ItemData_C'):
            with self.subTest(name=name):
                original = self.raw[name]
                self.raw[name] += b'\xff'
                with self.assertRaises(ValueError):
                    dynamic.activate_for_official(self.remote, **self.kwargs())
                self.assertIsNone(dynamic.current_runtime())
                self.raw[name] = original

    def test_ark_tables_use_verified_sqlite_and_only_ark_stops_on_bad_layout(self):
        from test_star_ark import raw_catalogs
        from wlre.services.world.ark_catalog import TABLES
        from wlre.services.world.resource_database import read_catalog_tables
        self.raw.update(raw_catalogs())
        manifest=self.manifests['DataPackage']
        manifest.index['assets'].extend(dict(path=_ASSET_ROOT+t+'.bytes',
            bundle_name=manifest.index['bundles'][0]['name']) for t in TABLES)
        runtime=dynamic.activate_for_official(self.remote,**self.kwargs())
        self.assertEqual(runtime.ark_catalog['stars'][1]['prices'][0],120)
        self.assertEqual(runtime.ark_catalog['agents'][1]['name'],'新版任務')
        parsed=read_catalog_tables(self.root/'derived_catalogs'/'resource_inventory.sqlite3',
            runtime.catalog_identity.key,('ark_stars','ark_agents','ark_fights'))
        self.assertEqual(parsed['ark_fights'][1]['awards'][0]['value'],28)
        self.raw['ArkStarData_C']+=b'!'
        runtime=dynamic.activate_for_official(self.remote,**self.kwargs())
        self.assertIsNone(runtime.ark_catalog)
        self.assertEqual(len(runtime.items),1)

    def test_missing_item_id_in_shop_refuses_runtime(self):
        self.raw['ItemData_C'] = struct.pack('<i', 1) + item_record(iid=999)
        with self.assertRaisesRegex(ValueError, '商店商品'):
            dynamic.prepare_dynamic_runtime(**self.kwargs())

    def test_changed_live_pair_and_mismatched_prelogin_identity_refuse(self):
        changed = deepcopy(self.snapshot)
        changed['packages']['MainPackage'] = '1285_2026_10_29_19_50_04_11'
        observations = iter((self.snapshot, changed))
        with self.assertRaisesRegex(ValueError, 'changed'):
            dynamic.prepare_dynamic_runtime(**dict(self.kwargs(), observe=lambda: next(observations)))
        self.remote['packages']['MainPackage']['remote'] = changed['packages']['MainPackage']
        with self.assertRaisesRegex(ValueError, 'pre-login'):
            dynamic.activate_for_official(self.remote, **self.kwargs())
        self.assertIsNone(dynamic.current_runtime())

    def test_tampered_cached_manifest_and_bundle_rejected(self):
        manifest = self.manifests['DataPackage']
        original = manifest.cache_path.read_bytes()
        manifest.cache_path.write_bytes(original + b'!')
        with self.assertRaisesRegex(ValueError, 'CRC'):
            dynamic.prepare_dynamic_runtime(**self.kwargs())
        manifest.cache_path.write_bytes(original)
        for path in self.fixture.bundle_root.rglob('*.bundle'):
            path.write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            dynamic.prepare_dynamic_runtime(**self.kwargs())

    def test_failure_invalidates_previous_runtime_and_never_uses_legacy(self):
        dynamic.activate_for_official(self.remote, **self.kwargs())
        self.raw['Eve'] = b'changed schema'
        with self.assertRaises(ValueError):
            dynamic.activate_for_official(self.remote, **self.kwargs())
        from wlre.services.world.runtime_1275 import active_runtime
        from wlre.services.items.crafting import RECIPES
        from wlre.services.expedition.data import load_active_catalog
        with self.assertRaisesRegex(ValueError, '禁止退回'):
            active_runtime()
        with self.assertRaises(ValueError):
            load_active_catalog()
        self.assertEqual(RECIPES, {})

    def test_duplicate_product_recipes_remain_in_complete_catalog(self):
        raw = self.raw['SmithData_C']
        raw = struct.pack('<i', 2) + raw[4:] + struct.pack('<H', 100) + raw[6:]
        from wlre.services.world.itemdata_v1 import parse_itemdata
        unique, rows = dynamic.parse_runtime_recipes(raw, parse_itemdata(self.raw['ItemData_C']))
        self.assertEqual(unique, {})
        self.assertEqual([r['recipe_id'] for r in rows], [99, 100])

    def test_superseded_background_load_cannot_publish_stale_data(self):
        runtime = dynamic.prepare_dynamic_runtime(**self.kwargs())
        def newer_check(**kwargs):
            dynamic.invalidate_runtime()
            return runtime
        with patch.object(dynamic, 'prepare_dynamic_runtime', side_effect=newer_check):
            with self.assertRaisesRegex(ValueError, 'superseded'):
                dynamic.activate_for_official(self.remote)
        self.assertIsNone(dynamic.current_runtime())

    def test_sync_rechecks_versions_before_writing_bundles(self):
        changed = deepcopy(self.snapshot)
        changed['packages']['MainPackage'] = '1285_2026_10_29_19_50_04_11'
        observed = iter((self.snapshot, changed))
        from unittest.mock import Mock
        execute = Mock()
        with self.assertRaisesRegex(ValueError, 'before Bundle'):
            dynamic.prepare_dynamic_runtime(sync=True, execute=execute,
                **dict(self.kwargs(), observe=lambda: next(observed)))
        execute.assert_not_called()


class OfficialCatalogMigrationTests(unittest.TestCase):
    def test_four_source_database_upgrades_without_losing_history(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE official_catalog_versions '
                           '(catalog_key TEXT PRIMARY KEY, verified_count INTEGER NOT NULL CHECK(verified_count=4))')
                db.execute('INSERT INTO official_catalog_versions VALUES (?,4)', ('a'*64,))
            parsed = {f: ParsedCatalog('b'*64, f, f+'.bytes', 'schema-v1', 'c'*64, 1, {}) for f in FEATURES}
            store_official_catalog(path, parsed)
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('SELECT verified_count FROM official_catalog_versions ORDER BY catalog_key').fetchall(), [(4,), (5,)])
            self.assertEqual(set(active_official_catalog(path)['sources']), set(FEATURES))
