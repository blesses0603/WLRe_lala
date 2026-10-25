"""Zero-config LaLa candidate pipeline: offline official-manifest fixtures only."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib
import zipfile

from wlre.services.official_manifest_sync import ManifestSpec, VerifiedManifest
from wlre.services.official_bundle_download import spec_from_manifest
from wlre.services.world.auto_catalog import (
    AutoCatalogError, _SOURCE_MAP, _ASSET_ROOT, _candidate_path,
    run_auto_catalog,
)
from wlre.services.official_incremental_sync import IncrementalSyncError
from wlre.services.world.official_catalog_pipeline import OfficialCatalogPipelineError

VERSIONS = {
    'DataPackage': '1275_2026_10_21_18_27_33_84',
    'MainPackage': '1275_2026_10_21_19_27_33_84',
}


def crc(raw):
    return (zlib.crc32(raw) & 0xffffffff).to_bytes(4, 'little').hex()


class AutoCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.candidates = self.root / 'candidates'
        self.bundles = self.root / 'bundles'
        self.snapshot = {
            'schema_version': 1, 'origin': 'official_pc_version_endpoint',
            'data_ver': '1.3.21', 'exe_version': '1.3.21',
            'packages': dict(VERSIONS),
            'checked_at_utc': '2026-10-24T00:00:00+00:00',
            'assets_ready': False,
        }
        self.bytes = {
            'npc': json.dumps({'schema_version': 1, 'source': 'EventData.NewNpc',
                               'scenes': {}, 'record_count': 0}).encode(),
            'shops': json.dumps({'schema_version': 1, 'source': 'EventData.NewInteract',
                                 'scenes': {}, 'record_count': 0}).encode(),
            'crafting': struct.pack('<i', 0),
            'scenes': struct.pack('<i', 0),
        }
        self.manifests = {}
        for package in VERSIONS:
            records = []
            for name in (('Eve.bytes', 'ItemData_C.bytes', 'SmithData_C.bytes',
                          'ScenesData_C.bytes') if package == 'DataPackage' else ()):
                records.append({'path': _ASSET_ROOT + name,
                                'bundle_name': package + '.bundle'})
            binary = b'official-fixture-' + package.encode()
            index = {
                'header': {'file_version': '2.2.5', 'package_name': package,
                           'package_version': VERSIONS[package],
                           'output_name_style': 1},
                'assets': records,
                'bundles': [{'name': package + '.bundle', 'dependencies': [],
                             'file_size': len(binary),
                             'file_hash': hashlib.md5(binary).hexdigest(),
                             'file_crc': crc(binary)}],
            }
            source = b'manifest-' + package.encode()
            path = self.root / (package + '.bytes')
            path.write_bytes(source)
            spec = ManifestSpec('1.3.21', package, VERSIONS[package])
            self.manifests[package] = VerifiedManifest(
                spec, index, crc(source), path, False)
            bundle = spec_from_manifest(data_ver='1.3.21', package=package,
                                        index=index, name=package + '.bundle')
            target = bundle.cache_path(self.bundles)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(binary)

    def kwargs(self, **overrides):
        params = dict(
            observe=lambda: self.snapshot,
            retrieve=lambda spec, cache_root=None: self.manifests[spec.package],
            previous_finder=lambda current, cache_root=None: None,
            bundle_root=self.bundles, candidate_root=self.candidates,
            extractor=lambda binding, paths: self.bytes[binding.contract.feature],
        )
        params.update(overrides)
        return params

    def test_no_bindings_needed_and_cache_is_private_unapproved(self):
        result = run_auto_catalog(**self.kwargs())
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual(result['cache'], 'new_private_candidate')
        self.assertEqual(set(result['record_counts']), set(_SOURCE_MAP))
        self.assertEqual(result['data_compatibility'], 'compatible')
        self.assertEqual(result['protocol_compatibility'], 'unverified')
        receipt = self.candidates / result['catalog_key'] / 'compatibility_report.json'
        self.assertTrue(receipt.is_file())
        compatibility = json.loads(receipt.read_text(encoding='utf-8'))
        self.assertEqual(set(compatibility['features']), set(_SOURCE_MAP))
        self.assertFalse(compatibility['assets_ready'])
        self.assertFalse(compatibility['can_send_packets'])
        self.assertFalse(result['approved'])
        self.assertFalse(result['assets_ready'])
        location = self.candidates / result['catalog_key'] / 'candidate.zip'
        self.assertTrue(location.is_file())
        with zipfile.ZipFile(location) as z:
            self.assertEqual(set(z.namelist()),
                             {'candidate.json', 'npc.source', 'shops.source',
                              'crafting.source', 'scenes.source'})
            meta = json.loads(z.read('candidate.json'))
            self.assertFalse(meta['approved'])
            self.assertEqual(meta['catalog_key'], result['catalog_key'])
            self.assertEqual(meta['features']['npc']['sha256'],
                             hashlib.sha256(self.bytes['npc']).hexdigest())

    def test_real_launcher_records_version_change_after_verified_manifests(self):
        # All network, Manifest and disk state are injected, while the public
        # Launcher entry path (observe=None/retrieve=None) is exercised.
        previous = dict(self.snapshot, packages=dict(self.snapshot['packages']))
        previous['packages']['DataPackage'] = '1274_2026_10_20_18_27_33_84'
        params = self.kwargs(observe=None, retrieve=None)
        with patch('wlre.services.world.auto_catalog.observe_official_versions',
                   return_value=self.snapshot), patch(
                       'wlre.services.world.auto_catalog.fetch_official_manifest',
                       side_effect=lambda spec, cache_root=None:
                       self.manifests[spec.package]), patch(
                       'wlre.services.official_resource_sync.read_snapshot',
                       return_value=previous), patch(
                       'wlre.services.official_resource_sync.save_snapshot') as save:
            stages = []
            result = run_auto_catalog(**dict(
                params, progress=lambda phase, details:
                stages.append((phase, details))))
        self.assertEqual(result['official_revision_status'], 'changed')
        self.assertEqual(result['status'], 'review_required')
        self.assertFalse(result['approved'])
        self.assertFalse(result['assets_ready'])
        self.assertFalse(result['can_send_packets'])
        save.assert_called_once_with(self.snapshot)
        changed = [value for phase, value in stages if phase == 'official_revision']
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]['state'], 'changed')
        self.assertEqual(changed[0]['data'], '1275')

    def test_version_change_mid_manifest_sync_never_records_observation(self):
        updated = dict(self.snapshot, packages=dict(self.snapshot['packages']))
        updated['packages']['MainPackage'] = '1276_2026_10_25_01_00_00_01'
        observations = iter((self.snapshot, updated))
        params = self.kwargs(observe=None, retrieve=None)
        with patch('wlre.services.world.auto_catalog.observe_official_versions',
                   side_effect=lambda: next(observations)), patch(
                       'wlre.services.world.auto_catalog.fetch_official_manifest',
                       side_effect=lambda spec, cache_root=None:
                       self.manifests[spec.package]), patch(
                       'wlre.services.official_resource_sync.save_snapshot') as save:
            with self.assertRaisesRegex(AutoCatalogError, 'version changed'):
                run_auto_catalog(**params)
        save.assert_not_called()

    def test_injected_fixture_never_updates_real_observed_version(self):
        with patch('wlre.services.official_resource_sync.read_snapshot') as read, patch(
                'wlre.services.official_resource_sync.save_snapshot') as save:
            result = run_auto_catalog(**self.kwargs())
        self.assertEqual(result['official_revision_status'], 'unrecorded')
        read.assert_not_called()
        save.assert_not_called()

    def test_progress_stages_are_emitted_only_for_work_attempted(self):
        events = []
        result = run_auto_catalog(**self.kwargs(
            progress=lambda phase, details: events.append((phase, details))))
        self.assertEqual(result['status'], 'review_required')
        phases = [stage for stage, _ in events]
        self.assertEqual(phases[:5], [
            'official_version', 'manifest', 'manifest',
            'bundle_plan', 'bundle_sync'])
        self.assertEqual(events[1][1]['package'], 'DataPackage')
        self.assertEqual(events[2][1]['package'], 'MainPackage')
        self.assertEqual(phases.count('extract'), 4)
        completed = [info for stage, info in events if stage == 'bundle_item']
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]['completed'], 1)
        self.assertEqual(completed[0]['total'], 1)
        self.assertEqual(completed[0]['action'], 'cached')
        self.assertEqual(phases[-3:], [
            'compatibility_check', 'candidate_ready', 'compatibility_ready'])
        cached = []
        run_auto_catalog(**self.kwargs(
            progress=lambda phase, details: cached.append(phase),
            extractor=lambda *_: self.fail('must use verified cache')))
        self.assertEqual(cached[-2:], ['cached_candidate', 'compatibility_ready'])
        self.assertIn('compatibility_check', cached)
        self.assertNotIn('extract', cached)

    def test_version_switch_during_two_manifest_downloads_aborts_before_bundles(self):
        # A newly published official .version must not combine old and new
        # DataPackage/MainPackage in one candidate or start Bundle fetching.
        updated = {**self.snapshot, 'packages': {
            **self.snapshot['packages'],
            'MainPackage': '1276_2026_10_24_21_00_00_01'}}
        observed = iter((self.snapshot, updated))
        events = []
        with self.assertRaisesRegex(AutoCatalogError, 'version changed'):
            run_auto_catalog(**self.kwargs(
                observe=lambda: next(observed),
                progress=lambda phase, details: events.append(phase)))
        self.assertNotIn('bundle_plan', events)
        self.assertNotIn('bundle_sync', events)
        self.assertNotIn('candidate_ready', events)
        self.assertFalse(self.candidates.exists())

    def test_version_recheck_failure_never_starts_bundle_work(self):
        observed = iter((self.snapshot, {
            **self.snapshot, 'packages': {'DataPackage': 'invalid'}}))
        events = []
        with self.assertRaisesRegex(AutoCatalogError, 'version recheck failed'):
            run_auto_catalog(**self.kwargs(
                observe=lambda: next(observed),
                progress=lambda phase, details: events.append(phase)))
        self.assertNotIn('bundle_sync', events)
        self.assertFalse(self.candidates.exists())

    def test_version_recheck_ignores_observation_timestamp(self):
        observed = iter((self.snapshot, {
            **self.snapshot, 'checked_at_utc': '2026-10-24T12:00:00+00:00'}))
        result = run_auto_catalog(**self.kwargs(observe=lambda: next(observed)))
        self.assertEqual(result['status'], 'review_required')
        self.assertFalse(result['can_send_packets'])

    def test_readonly_preview_does_not_repeat_version_requests(self):
        calls = []
        result = run_auto_catalog(**self.kwargs(
            download=False, parse=False,
            observe=lambda: calls.append('observed') or self.snapshot))
        self.assertEqual(result['status'], 'preview')
        self.assertEqual(calls, ['observed'])

    def test_failing_manifest_never_reports_bundle_completed(self):
        self.manifests['DataPackage'].index['assets'].pop()
        events = []
        with self.assertRaisesRegex(Exception, 'AssetPath missing'):
            run_auto_catalog(**self.kwargs(
                progress=lambda phase, details: events.append(phase)))
        self.assertNotIn('bundle_sync', events)
        self.assertNotIn('candidate_ready', events)

    def test_cached_candidate_reuses_without_extraction(self):
        first = run_auto_catalog(**self.kwargs())
        cached = run_auto_catalog(**self.kwargs(
            extractor=lambda *_: self.fail('extractor should not be called on cache hit')))
        self.assertEqual(first['catalog_key'], cached['catalog_key'])
        self.assertEqual(cached['cache'], 'verified_private_candidate')

    def test_tamper_rebuilds_from_verified_sources_not_accepted(self):
        first = run_auto_catalog(**self.kwargs())
        path = self.candidates / first['catalog_key'] / 'candidate.zip'
        with path.open('ab') as stream:
            stream.write(b'invalid trailing bytes')
        # Python ZIP readers may permit trailing bytes, so ensure a definite
        # invalid private ZIP rather than relying on appended garbage alone.
        path.write_bytes(b'not-a-ZIP')
        second = run_auto_catalog(**self.kwargs())
        self.assertEqual(second['cache'], 'new_private_candidate')

    def test_self_consistent_but_invalid_cached_schema_is_rebuilt(self):
        """Recomputed local SHA cannot promote a malformed source to compatible."""
        result = run_auto_catalog(**self.kwargs())
        target = self.candidates / result['catalog_key'] / 'candidate.zip'
        with zipfile.ZipFile(target, 'r') as source:
            contents = {name: source.read(name) for name in source.namelist()}
        altered = b'not valid schema'
        meta = json.loads(contents['candidate.json'])
        meta['features']['npc']['sha256'] = hashlib.sha256(altered).hexdigest()
        meta['features']['npc']['bytes'] = len(altered)
        contents['candidate.json'] = json.dumps(meta, ensure_ascii=False).encode()
        contents['npc.source'] = altered
        with zipfile.ZipFile(target, 'w') as source:
            for name, body in contents.items():
                source.writestr(name, body)
        refreshed = run_auto_catalog(**self.kwargs())
        self.assertEqual(refreshed['cache'], 'new_private_candidate')
        self.assertEqual(refreshed['data_compatibility'], 'compatible')

    def test_removed_official_bundle_disallows_false_cache_hit(self):
        result = run_auto_catalog(**self.kwargs())
        bundle = spec_from_manifest(
            data_ver='1.3.21', package='DataPackage',
            index=self.manifests['DataPackage'].index,
            name='DataPackage.bundle')
        bundle.cache_path(self.bundles).unlink()
        with self.assertRaises(OfficialCatalogPipelineError):
            run_auto_catalog(**self.kwargs(
                max_download_bytes=0, opener=lambda *_: self.fail('no CDN')))
        self.assertTrue((self.candidates / result['catalog_key'] /
                         'candidate.zip').exists())

    def test_cached_receipt_tampering_does_not_enable_game(self):
        result = run_auto_catalog(**self.kwargs())
        report = self.candidates / result['catalog_key'] / 'compatibility_report.json'
        content = json.loads(report.read_text(encoding='utf-8'))
        content['approved'] = True
        report.write_text(json.dumps(content), encoding='utf-8')
        # Cached source is reverified; its display-only receipt gets refreshed.
        reused = run_auto_catalog(**self.kwargs())
        self.assertEqual(reused['cache'], 'verified_private_candidate')
        self.assertFalse(json.loads(report.read_text())['approved'])
        self.assertFalse(reused['can_send_packets'])

    def test_absent_asset_fails_closed_before_any_cache_output(self):
        self.manifests['DataPackage'].index['assets'].pop()
        with self.assertRaisesRegex(Exception, 'AssetPath missing'):
            run_auto_catalog(**self.kwargs())
        self.assertFalse(self.candidates.exists())

    def test_invalid_output_does_not_publish_partial_catalog(self):
        self.bytes['shops'] = b'invalid-shop-index'
        with self.assertRaisesRegex(AutoCatalogError, 'shops'):
            run_auto_catalog(**self.kwargs())
        self.assertFalse(any(self.candidates.rglob('candidate.zip'))
                         if self.candidates.exists() else False)

    def test_decoder_failure_reports_real_stage_without_activating_catalog(self):
        from wlre.services.world.unity_textasset import UnityTextAssetError
        from wlre.services.world.eve_v115 import EveDecodeError
        from wlre.services.world.itemdata_v1 import ItemDataDecodeError
        cases = (
            (UnityTextAssetError('Exact AssetPath is missing from verified UnityFS Bundles'),
             'UnityFS／TextAsset', 'Exact AssetPath'),
            (EveDecodeError('Unsupported Eve scene format, expected 115'),
             'Eve 二進位事件', 'expected 115'),
            (ItemDataDecodeError('ItemData record layout changed or trailing bytes'),
             'ItemData 二進位表', 'trailing bytes'),
        )
        for original, stage, detail in cases:
            with self.subTest(stage=stage):
                events = []
                def fail(*args):
                    raise original
                with self.assertRaises(AutoCatalogError) as thrown:
                    run_auto_catalog(**self.kwargs(
                        extractor=fail,
                        progress=lambda phase, info: events.append((phase, info))))
                self.assertIn(stage, str(thrown.exception))
                self.assertIn(detail, str(thrown.exception))
                self.assertIs(thrown.exception.__cause__, original)
                self.assertEqual(events[-1][0], 'extract_failed')
                self.assertEqual(events[-1][1]['feature'], 'npc')
                self.assertEqual(events[-1][1]['stage'], stage)
                self.assertFalse(self.candidates.exists())

    def test_schema_failure_is_not_misreported_as_unityfs(self):
        events = []
        def invalid(binding, paths):
            return b'not valid JSON' if binding.contract.feature == 'npc' else (
                self.bytes[binding.contract.feature])
        with self.assertRaisesRegex(AutoCatalogError, 'npc 資料 Schema 校驗失敗'):
            run_auto_catalog(**self.kwargs(
                extractor=invalid,
                progress=lambda phase, info: events.append((phase, info))))
        self.assertEqual(events[-1], ('extract_failed',
                                       {'feature': 'npc', 'stage': '資料 Schema'}))
        self.assertFalse(self.candidates.exists())

    def test_unexpected_exceptions_do_not_expose_private_paths(self):
        def fail(*args):
            raise RuntimeError('secret C:\\Users\\test\\private.bundle')
        with self.assertRaises(AutoCatalogError) as thrown:
            run_auto_catalog(**self.kwargs(extractor=fail))
        self.assertIn('RuntimeError', str(thrown.exception))
        self.assertNotIn('private.bundle', str(thrown.exception))
        self.assertFalse(self.candidates.exists())

    def test_optional_raw_rebuild_respects_remaining_launcher_quota(self):
        from wlre.services.world.auto_catalog import _rebuild_known_resources
        events = []
        example = {'asset_total': 190, 'asset_collected': 10,
                   'complete_raw_assets': False,
                   'formal_approved': False, 'can_send_packets': False,
                   'assets_ready': False}
        with patch('wlre.services.world.resource_rebuilder.rebuild_raw_resources',
                   return_value=example) as rebuild:
            result = _rebuild_known_resources(
                {'download_bytes': 8 * 1024 * 1024, 'downloads_required': 2},
                identity=object(), manifests={'DataPackage': object()},
                bundle_root=None, candidate_root=None,
                max_download_bytes=12 * 1024 * 1024, max_downloads=3,
                opener=None,
                progress=lambda phase, info: events.append((phase, info)))
        self.assertEqual(result['status'], 'partial_raw')
        self.assertEqual(rebuild.call_args.kwargs['max_downloads'], 1)
        self.assertEqual(rebuild.call_args.kwargs['max_download_bytes'],
                         4 * 1024 * 1024)
        self.assertEqual([phase for phase, _ in events],
                         ['raw_rebuild', 'raw_rebuild_ready'])
        self.assertFalse(result['assets_ready'])

    def test_optional_rebuild_error_does_not_approve_candidate(self):
        from wlre.services.world.auto_catalog import _rebuild_known_resources
        with patch('wlre.services.world.resource_rebuilder.rebuild_raw_resources',
                   side_effect=ValueError('format changed')):
            result = _rebuild_known_resources(
                {'download_bytes': 0, 'downloads_required': 0},
                identity=object(), manifests={'DataPackage': object()},
                bundle_root=None, candidate_root=None,
                max_download_bytes=0, max_downloads=0,
                opener=None, progress=None)
        self.assertEqual(result['status'], 'pending_error')
        self.assertFalse(result['can_send_packets'])

    def test_preview_avoids_extraction_and_writes(self):
        result = run_auto_catalog(**self.kwargs(download=False, parse=False))
        self.assertEqual(result['status'], 'preview')
        self.assertFalse(self.candidates.exists())
        with self.assertRaises(AutoCatalogError):
            run_auto_catalog(**self.kwargs(download=False, parse=True))

    def test_quota_violation_before_download(self):
        row = self.manifests['DataPackage'].index['bundles'][0]
        spec = spec_from_manifest(data_ver='1.3.21', package='DataPackage',
                                  index=self.manifests['DataPackage'].index,
                                  name=row['name'])
        spec.cache_path(self.bundles).unlink()
        with self.assertRaises(OfficialCatalogPipelineError):
            run_auto_catalog(**self.kwargs(max_download_bytes=0, opener=lambda *args:
                                           self.fail('must not reach CDN')))

    def test_cli_no_bindings_and_auto_mode(self):
        from tools import plan_official_catalog
        with patch.object(__import__('wlre.services.world.auto_catalog',
                                     fromlist=['run_auto_catalog']),
                          'run_auto_catalog',
                          return_value={'status': 'review_required'}) as run:
            self.assertEqual(plan_official_catalog.main(['--download', '--parse']), 0)
            self.assertTrue(run.call_args.kwargs['parse'])
            self.assertEqual(plan_official_catalog.main([]), 0)
            self.assertFalse(run.call_args.kwargs['download'])


if __name__ == '__main__':
    unittest.main()
