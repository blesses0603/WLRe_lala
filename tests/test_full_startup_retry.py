"""Full retry repairs real verified source fixtures before independent loading.

Only official metadata/transport and Unity extraction are offline substitutes;
Bundle hashes, source sync, Runtime parsing, SQLite and gate checks are real.
"""
from copy import deepcopy
from dataclasses import replace
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

import test_dynamic_bundle_runtime as fixtures
from test_integrated_startup import StartupHarness
from test_official_bundle_download import FakeResponse
from wlre.services import game_version_gate
from wlre.services.official_bundle_download import spec_from_manifest
from wlre.services.official_incremental_sync import execute_update_plan
from wlre.services.world import dynamic_bundle_runtime as dynamic
from wlre.services.world import launcher_catalog


class FullStartupRetryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DynamicBundleRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        # Match the production prelogin database path without symlinks.
        self.home = self.fixture.root
        self.fixture.root = self.home / 'official_sync'
        self.fixture.root.mkdir()
        (self.home / 'bundles').rename(self.fixture.root / 'bundles')
        self.app = StartupHarness()
        self.offline = False
        self.requests = []
        self.bodies = {}
        for manifest in self.fixture.manifests.values():
            for row in manifest.index['bundles']:
                spec = spec_from_manifest(data_ver=manifest.spec.data_ver,
                    package=manifest.spec.package, index=manifest.index, name=row['name'])
                self.bodies[spec.url] = spec.cache_path(self.fixture.root / 'bundles').read_bytes()
        self.enterContext(patch('wlre.storage.paths.data_root', return_value=self.home))
        self.enterContext(patch.object(launcher_catalog, 'data_root', return_value=self.home))
        self.enterContext(patch('wlre.services.official_server_list.sync_server_list', return_value={'count': 0}))
        self.enterContext(patch('wlre.services.world.runtime_manifest_identity.discover_runtime_identity',
                                side_effect=OSError('offline optional discovery fixture')))
        self.enterContext(patch('wlre.services.world.official_combat_sources.load_inputs', return_value={}))
        self.enterContext(patch('wlre.services.world.resource_gap_diagnostics.diagnose_resources', return_value={}))
        self.enterContext(patch('wlre.services.world.resource_gap_diagnostics.save_report'))
        from wlre.services.world.auto_catalog import run_auto_catalog
        def collect(**kwargs):
            options = self.fixture.kwargs()
            return run_auto_catalog(observe=options['observe'], retrieve=options['retrieve'],
                previous_finder=lambda *args, **kw: None,
                manifest_root=self.fixture.root / 'manifests',
                bundle_root=self.fixture.root / 'bundles',
                candidate_root=self.fixture.root / 'derived_catalogs',
                opener=self.opener, **kwargs)
        self.enterContext(patch('wlre.services.world.auto_catalog.run_auto_catalog', side_effect=collect))
        def extract(binding, paths, loader=None):
            return self.fixture.raw[binding.asset_path.rsplit('/', 1)[-1].removesuffix('.bytes')]
        self.enterContext(patch('wlre.services.world.resource_rebuilder.extract_textasset', side_effect=extract))
        self.enterContext(patch('wlre.services.world.catalog_source_extractor.extract_textasset', side_effect=extract))
        self.enterContext(patch.dict(sys.modules, {'UnityPy': SimpleNamespace(load=lambda path: None)}))
        self.enterContext(patch('wlre.ui.version_gate_controller._launcher_status_text',
                                return_value='離線測試：來源收集紀錄不是登入授權'))
        original_sync = dynamic.sync_dynamic_runtime_sources
        original_activate = dynamic.activate_for_official
        self.sync = self.enterContext(patch.object(dynamic, 'sync_dynamic_runtime_sources',
            side_effect=lambda: original_sync(execute=self.execute, **self.fixture.kwargs())))
        self.activate = self.enterContext(patch.object(dynamic, 'activate_for_official',
            side_effect=lambda remote: original_activate(remote, **self.fixture.kwargs())))
        self.build = self.enterContext(patch.object(dynamic, 'prepare_dynamic_runtime',
                                                  wraps=dynamic.prepare_dynamic_runtime))
        self.boundary_switch = None
        def prepare(*, progress):
            before = self.build.call_count
            result = launcher_catalog.prepare_on_launch(environ={}, progress=progress)
            self.assertEqual(self.build.call_count, before, 'Source preparation built a Runtime')
            if self.boundary_switch:
                change, self.boundary_switch = self.boundary_switch, None
                change()
            return result
        self.prepare = self.enterContext(patch('wlre.ui.version_gate_controller.prepare_on_launch', side_effect=prepare))
        self.enterContext(patch.object(game_version_gate, 'check_official_game_resources', side_effect=self.remote))
        self.check = self.enterContext(patch('wlre.ui.version_gate_controller.run_prelogin_check',
                                             wraps=game_version_gate.run_prelogin_check))

    def remote(self):
        return {'status': 'resources_changed',
                'resource_path': self.fixture.snapshot['data_ver'],
                'official_exe_version': self.fixture.snapshot['exe_version'],
                'newer_official_client': False,
                'packages': {name: {'remote': version, 'comparison': 'different'}
                             for name, version in self.fixture.snapshot['packages'].items()}}

    def opener(self, request, timeout):
        self.requests.append(request.full_url)
        if self.offline:
            raise OSError('fixture disconnected')
        return FakeResponse(request.full_url, self.bodies[request.full_url])

    def execute(self, plan, **kwargs):
        return execute_update_plan(plan, opener=self.opener, **kwargs)

    def core_source(self):
        manifest = self.fixture.manifests['DataPackage']
        spec = spec_from_manifest(data_ver=manifest.spec.data_ver, package='DataPackage',
            index=manifest.index, name=manifest.index['bundles'][0]['name'])
        return spec, spec.cache_path(self.fixture.root / 'bundles')

    def change_data_version(self, new_version='1262_2026_10_14_15_00_34_84'):
        # Exercise a changed source identity using a reviewed legacy layout.
        # An invented newer revision must remain blocked by ItemData review.
        package = 'DataPackage'
        previous = self.fixture.manifests[package]
        index = deepcopy(previous.index)
        index['header']['package_version'] = new_version
        current = replace(previous, spec=replace(previous.spec, package_version=new_version), index=index)
        self.fixture.manifests[package] = current
        self.fixture.snapshot['packages'][package] = new_version
        for row in current.index['bundles']:
            old_spec = spec_from_manifest(data_ver=previous.spec.data_ver, package=package,
                                         index=previous.index, name=row['name'])
            new_spec = spec_from_manifest(data_ver=current.spec.data_ver, package=package,
                                         index=current.index, name=row['name'])
            self.bodies[new_spec.url] = self.bodies[old_spec.url]

    def attempt(self):
        with patch('wlre.ui.version_gate_controller.threading.Thread') as thread:
            self.app.start_version_check()
        self.assertEqual(self.app._startup_phase, 'preparing')
        thread.call_args.kwargs['target']()
        self.app.drain_version_checks()
        return self.app._version_gate_result

    def assert_success(self, result):
        self.assertEqual(result['status'], 'database_matches_official')
        self.assertTrue(result['database_verified'])
        self.assertFalse(result['blocked'])
        self.assertEqual(self.app.version_gate_state, 'ready')
        self.assertFalse(self.app._version_gate_entry_approved)
        self.assertEqual(result['runtime_identity'], dynamic.current_runtime().catalog_identity.as_dict())

    def test_offline_missing_bundle_is_downloaded_on_retry_then_full_gate_passes(self):
        spec, path = self.core_source()
        expected = path.read_bytes()
        path.unlink()
        self.offline = True
        failed = self.attempt()
        self.assertTrue(failed['blocked'])
        self.assertEqual(failed['status'], 'runtime_unavailable')
        self.assertFalse(path.exists())
        self.assertIsNone(dynamic.current_runtime())
        self.offline = False
        repaired = self.attempt()
        self.assert_success(repaired)
        self.assertEqual(path.read_bytes(), expected)
        self.assertIn(spec.url, self.requests)
        self.assertEqual(self.prepare.call_count, 2)
        self.assertEqual(self.sync.call_count, 2)
        self.assertEqual(self.check.call_count, 2)
        self.assertEqual(self.build.call_count, 2)  # One full attempt each, never source-side.

    def test_official_version_change_downloads_new_sources_after_previous_success(self):
        self.assert_success(self.attempt())
        previous_key = dynamic.current_runtime().catalog_identity.key
        self.change_data_version()
        spec, path = self.core_source()
        self.assertFalse(path.exists())
        updated = self.attempt()
        self.assert_success(updated)
        self.assertNotEqual(dynamic.current_runtime().catalog_identity.key, previous_key)
        self.assertEqual(path.read_bytes(), self.bodies[spec.url])
        self.assertIn(spec.url, self.requests)
        self.assertEqual(self.sync.call_count, 2)
        self.assertEqual(self.build.call_count, 2)

    def test_unreviewed_version_stays_blocked_after_sources_are_downloaded(self):
        self.assert_success(self.attempt())
        self.change_data_version('1287_2026_11_07_13_42_37_94')
        spec, path = self.core_source()
        self.assertFalse(path.exists())
        result = self.attempt()
        self.assertEqual(path.read_bytes(), self.bodies[spec.url])
        self.assertEqual(result['status'], 'runtime_unavailable')
        self.assertTrue(result['blocked'])
        self.assertFalse(result['database_verified'])
        self.assertIsNone(dynamic.current_runtime())
        self.assertEqual(self.prepare.call_count, 2)
        self.assertEqual(self.check.call_count, 2)

    def test_version_change_between_sync_and_gate_fails_closed_then_retry_repairs(self):
        self.boundary_switch = self.change_data_version
        failed = self.attempt()
        self.assertTrue(failed['blocked'])
        self.assertIsNone(dynamic.current_runtime())
        _, missing = self.core_source()
        self.assertFalse(missing.exists())
        recovered = self.attempt()
        self.assert_success(recovered)
        self.assertTrue(missing.exists())
        self.assertEqual(self.sync.call_count, 2)
        self.assertEqual(self.build.call_count, 2)


if __name__ == '__main__':
    unittest.main()
