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
        self.assertEqual(phases[-2:], ['candidate_write', 'candidate_ready'])
        cached = []
        run_auto_catalog(**self.kwargs(
            progress=lambda phase, details: cached.append(phase),
            extractor=lambda *_: self.fail('must use verified cache')))
        self.assertEqual(cached[-1], 'cached_candidate')
        self.assertNotIn('extract', cached)

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
