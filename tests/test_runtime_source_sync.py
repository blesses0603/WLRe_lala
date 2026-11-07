"""Source-only startup sync retains verification; pre-login loads runtime once."""
from contextlib import closing
from copy import deepcopy
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_dynamic_bundle_runtime as runtime_fixtures
from test_official_bundle_download import FakeResponse
from wlre.services.world import dynamic_bundle_runtime as dynamic
from wlre.services.world import bundle_runtime_1275 as bundles
from wlre.services.official_bundle_download import spec_from_manifest
from wlre.services.official_incremental_sync import execute_update_plan


class RuntimeSourceSyncTests(unittest.TestCase):
    def setUp(self):
        self.fixture=runtime_fixtures.DynamicBundleRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.combat_inputs=self.enterContext(patch(
            'wlre.services.world.official_combat_sources.load_inputs',return_value={}))

    def source(self):
        manifest=self.fixture.manifests['DataPackage']
        spec=spec_from_manifest(data_ver=manifest.spec.data_ver, package='DataPackage',
                               index=manifest.index, name=manifest.index['bundles'][0]['name'])
        return spec, spec.cache_path(self.fixture.root/'bundles')

    def test_source_sync_never_builds_runtime_and_prelogin_loads_it_once(self):
        with patch.object(bundles,'load_verified_bundle_runtime',
                          wraps=bundles.load_verified_bundle_runtime) as load:
            report=dynamic.sync_dynamic_runtime_sources(**self.fixture.kwargs())
            load.assert_not_called()
            self.assertIsNone(dynamic.current_runtime())
            self.assertFalse(report['assets_ready'])
            self.assertFalse(report['can_send_packets'])
            runtime=dynamic.activate_for_official(self.fixture.remote,**self.fixture.kwargs())
            load.assert_called_once()
        self.assertEqual(runtime.catalog_identity.key,report['catalog_key'])
        self.assertIs(dynamic.current_runtime(),runtime)

    def test_auto_catalog_and_complete_inventory_do_not_need_early_runtime(self):
        from wlre.services.world.auto_catalog import run_auto_catalog
        from wlre.services.world.resource_database import database_matches_runtime
        def extract(binding,paths,loader=None):
            return self.fixture.raw[binding.asset_path.rsplit('/',1)[-1].removesuffix('.bytes')]
        with patch.object(bundles,'load_verified_bundle_runtime',
                          wraps=bundles.load_verified_bundle_runtime) as load, \
             patch('wlre.services.world.resource_rebuilder.extract_textasset',side_effect=extract), \
             patch('wlre.services.world.catalog_source_extractor.extract_textasset',side_effect=extract), \
             patch.dict(sys.modules,{'UnityPy':SimpleNamespace(load=lambda path:None)}):
            dynamic.sync_dynamic_runtime_sources(**self.fixture.kwargs())
            options=self.fixture.kwargs()
            result=run_auto_catalog(observe=options['observe'],retrieve=options['retrieve'],
                previous_finder=lambda *args,**kwargs:None,
                manifest_root=self.fixture.root/'manifests',bundle_root=self.fixture.root/'bundles',
                candidate_root=self.fixture.root/'derived_catalogs')
            self.assertEqual(result['status'],'verified_official')
            self.assertTrue(result['resource_rebuild']['complete_raw_assets'])
            load.assert_not_called()
            runtime=dynamic.activate_for_official(self.fixture.remote,**options)
            load.assert_called_once()
        self.assertTrue(database_matches_runtime(
            self.fixture.root/'derived_catalogs'/'resource_inventory.sqlite3',runtime))

    def test_missing_core_bundle_is_downloaded_and_verified_before_single_load(self):
        spec,path=self.source()
        body=path.read_bytes()
        path.unlink()
        requested=[]
        def opener(request,timeout):
            requested.append(request.full_url)
            return FakeResponse(request.full_url,body)
        def execute(plan,**kwargs):
            return execute_update_plan(plan,opener=opener,**kwargs)
        with patch.object(bundles,'load_verified_bundle_runtime',
                          wraps=bundles.load_verified_bundle_runtime) as load:
            dynamic.sync_dynamic_runtime_sources(execute=execute,**self.fixture.kwargs())
            load.assert_not_called()
            self.assertEqual(path.read_bytes(),body)
            self.assertEqual(requested,[spec.url])
            dynamic.activate_for_official(self.fixture.remote,**self.fixture.kwargs())
            load.assert_called_once()

    def test_source_only_sync_keeps_optional_tables_images_emoji_and_combat_budgets(self):
        from wlre.services.world.smallmap_database import PREFIX as MAP_PREFIX
        from wlre.services.world.item_image_database import PREFIX as ITEM_PREFIX
        from wlre.services.world.emoji_database import ASSET as EMOJI_ASSET
        main=self.fixture.manifests['MainPackage']
        data=self.fixture.manifests['DataPackage']
        main_paths=(MAP_PREFIX+'SmallMap2D_123.png',ITEM_PREFIX+'s1000.png',EMOJI_ASSET)
        data_paths=tuple(bundles._ASSET_ROOT+name+'.bytes' for name in
                         ('SkillData_C','StageMapData_C','EmojiData_C'))
        for manifest,paths in ((main,main_paths),(data,data_paths)):
            manifest.index['assets'].extend({'path':path,
                'bundle_name':manifest.index['bundles'][0]['name']} for path in paths)
        execute=Mock(side_effect=execute_update_plan)
        with patch.object(bundles,'load_verified_bundle_runtime') as load:
            dynamic.sync_dynamic_runtime_sources(execute=execute,
                max_image_download_bytes=4096,max_image_downloads=2,
                max_emoji_download_bytes=2048,max_emoji_downloads=3,**self.fixture.kwargs())
            load.assert_not_called()
        plans={call.args[0].requested_assets:call.kwargs for call in execute.call_args_list}
        core=tuple(sorted(bundles._ASSET_ROOT+name+'.bytes' for name in bundles._REQUIRED_TABLES))
        self.assertIn(core,plans)
        self.assertEqual(plans[core]['max_download_bytes'],32*1024*1024)
        self.assertEqual(plans[core]['max_downloads'],24)
        for path in data_paths:self.assertIn((path,),plans)
        self.assertEqual(plans[(main_paths[0],)]['max_download_bytes'],4096)
        self.assertEqual(plans[(main_paths[0],)]['max_downloads'],2)
        self.assertEqual(plans[(EMOJI_ASSET,)]['max_download_bytes'],2048)
        self.assertEqual(plans[(EMOJI_ASSET,)]['max_downloads'],3)
        self.assertEqual(plans[(main_paths[1],)]['max_download_bytes'],32*1024*1024)
        self.assertEqual(plans[(main_paths[1],)]['max_downloads'],4)
        self.assertTrue(all(options['download'] for options in plans.values()))
        self.combat_inputs.assert_called_once_with(self.fixture.root,
            self.fixture.snapshot['data_ver'],download=True)

    def test_prelogin_fetches_fresh_official_hash_even_after_warm_source_sync(self):
        from wlre.services.official_manifest_sync import fetch_official_manifest
        requests=[]
        bodies={}
        for manifest in self.fixture.manifests.values():
            bodies[manifest.spec.url('hash')]=manifest.hash_text.encode('ascii')
            bodies[manifest.spec.url('bytes')]=manifest.cache_path.read_bytes()
        def opener(request,timeout):
            requests.append(request.full_url)
            return FakeResponse(request.full_url,bodies[request.full_url])
        def retrieve(spec,cache_root):
            return fetch_official_manifest(spec,cache_root=cache_root,opener=opener,
                parser=lambda raw:self.fixture.manifests[spec.package].index)
        options=dict(self.fixture.kwargs(),retrieve=retrieve)
        dynamic.sync_dynamic_runtime_sources(**options)
        runtime=dynamic.activate_for_official(self.fixture.remote,**options)
        self.assertEqual(runtime.record_counts['npc'],1)
        for manifest in self.fixture.manifests.values():
            self.assertEqual(requests.count(manifest.spec.url('hash')),2)
            self.assertEqual(requests.count(manifest.spec.url('bytes')),1)

    def test_corrupt_download_cannot_become_a_prepared_runtime(self):
        _,path=self.source()
        path.unlink()
        def execute(plan,**kwargs):
            return execute_update_plan(plan,opener=lambda request,timeout:
                                       FakeResponse(request.full_url,b'bad'),**kwargs)
        with patch.object(bundles,'load_verified_bundle_runtime') as load:
            with self.assertRaises(ValueError):
                dynamic.sync_dynamic_runtime_sources(execute=execute,**self.fixture.kwargs())
            load.assert_not_called()
        self.assertFalse(path.exists())
        with self.assertRaises(ValueError):
            dynamic.activate_for_official(self.fixture.remote,**self.fixture.kwargs())
        self.assertIsNone(dynamic.current_runtime())

    def test_warm_database_does_not_hide_changed_bundle_or_raw_database_bytes(self):
        dynamic.sync_dynamic_runtime_sources(**self.fixture.kwargs())
        dynamic.activate_for_official(self.fixture.remote,**self.fixture.kwargs())
        _,path=self.source()
        original=path.read_bytes()
        path.write_bytes(bytes([original[0]^1])+original[1:])
        with self.assertRaises(ValueError):
            dynamic.activate_for_official(self.fixture.remote,**self.fixture.kwargs())
        self.assertIsNone(dynamic.current_runtime())
        path.write_bytes(original)
        database=self.fixture.root/'derived_catalogs'/'resource_inventory.sqlite3'
        with closing(sqlite3.connect(database)) as db,db:
            db.execute('UPDATE normalized_raw SET data=?',(b'changed raw source',))
        with self.assertRaises(ValueError):
            dynamic.activate_for_official(self.fixture.remote,**self.fixture.kwargs())
        self.assertIsNone(dynamic.current_runtime())

    def test_sync_keeps_before_and_after_version_checks(self):
        changed=deepcopy(self.fixture.snapshot)
        changed['packages']['MainPackage']='1285_2026_10_29_19_50_04_11'
        for sequence,expected_calls in (([self.fixture.snapshot,changed],0),
                ([self.fixture.snapshot,self.fixture.snapshot,changed],1)):
            with self.subTest(observations=len(sequence)):
                observations=Mock(side_effect=sequence)
                execute=Mock()
                with self.assertRaisesRegex(ValueError,'changed'):
                    dynamic.sync_dynamic_runtime_sources(execute=execute,**dict(
                        self.fixture.kwargs(),observe=observations))
                self.assertEqual(execute.call_count,expected_calls)
                self.assertIsNone(dynamic.current_runtime())

    def test_sync_rechecks_manifest_bytes_after_downloads(self):
        manifest=self.fixture.manifests['DataPackage']
        def execute(plan,**kwargs):
            manifest.cache_path.write_bytes(manifest.cache_path.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'CRC'):
            dynamic.sync_dynamic_runtime_sources(execute=execute,**self.fixture.kwargs())
        self.assertIsNone(dynamic.current_runtime())

    def test_offline_or_download_budget_failure_cannot_reuse_previous_runtime(self):
        with patch.object(bundles,'load_verified_bundle_runtime') as load:
            with self.assertRaises(OSError):
                dynamic.sync_dynamic_runtime_sources(**dict(
                    self.fixture.kwargs(),observe=Mock(side_effect=OSError('offline'))))
            load.assert_not_called()
        _,path=self.source()
        path.unlink()
        with self.assertRaisesRegex(ValueError,'quota'):
            dynamic.sync_dynamic_runtime_sources(max_downloads=0,**self.fixture.kwargs())
        self.assertIsNone(dynamic.current_runtime())

