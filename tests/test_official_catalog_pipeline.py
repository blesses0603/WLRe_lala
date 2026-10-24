"""Tests for official provenance + exact asset resolution + verified Bundle handoff."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from wlre.services.official_manifest_sync import ManifestSpec, VerifiedManifest
from wlre.services.world.catalog_adapters import SourceContract
from wlre.services.world.official_catalog_pipeline import (
    AssetBinding, OfficialCatalogPipelineError,
    plan_catalog_pipeline, plan_current_catalog, run_catalog_pipeline,
)

DATA_VER = '1.3.21'
DATA_REV = '1275_2026_10_21_18_27_33_84'
MAIN_REV = '1275_2026_10_21_19_27_33_84'


def digest_crc(raw):
    return (zlib.crc32(raw) & 0xffffffff).to_bytes(4, 'little').hex()


def index_blob(source):
    return json.dumps({'schema_version': 1, 'source': source,
                       'scenes': {}, 'record_count': 0}).encode('utf-8')


class OfficialPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle_root = self.root / 'bundles'
        self.snapshot = {
            'schema_version': 1, 'origin': 'official_pc_version_endpoint',
            'data_ver': DATA_VER, 'exe_version': DATA_VER,
            'packages': {'DataPackage': DATA_REV, 'MainPackage': MAIN_REV},
            'checked_at_utc': '2026-10-24T00:00:00+00:00',
            'assets_ready': False,
        }
        self.source_data = {
            'npc': index_blob('EventData.NewNpc'),
            'shops': index_blob('EventData.NewInteract'),
            'crafting': struct.pack('<i', 0),
            'scenes': struct.pack('<i', 0),
        }
        self.bindings = []
        self.manifests = {}
        for package, version in self.snapshot['packages'].items():
            bundle_bytes = b'dummy-UnityFS-' + package.encode()
            name = package.lower() + '_data_v.bundle'
            rows = []
            for feature in ('npc', 'shops', 'crafting', 'scenes'):
                if (feature in ('npc', 'shops', 'crafting')) != (package == 'DataPackage'):
                    continue
                path = 'Assets/Test/' + feature
                rows.append({'path': path, 'bundle_name': name})
                raw = self.source_data[feature]
                schema = {'npc': 'eve-npc-json-v1',
                          'shops': 'eve-interact-json-v1',
                          'crafting': 'smith-new-33-v1',
                          'scenes': 'stage-new-76-v1'}[feature]
                contract = SourceContract(
                    feature, feature + '.decoded', schema,
                    hashlib.sha256(raw).hexdigest(), package, version)
                self.bindings.append(AssetBinding(path, contract))
            manifest_bytes = b'YooAsset-Test-' + package.encode()
            receipt = self.root / (package + '.bytes')
            receipt.write_bytes(manifest_bytes)
            index = {'header': {
                'file_version': '2.2.5', 'package_name': package,
                'package_version': version, 'output_name_style': 1,
            }, 'bundles': [{
                'name': name, 'dependencies': [],
                'file_size': len(bundle_bytes),
                'file_hash': hashlib.md5(bundle_bytes).hexdigest(),
                'file_crc': digest_crc(bundle_bytes),
            }], 'assets': rows}
            spec = ManifestSpec(DATA_VER, package, version)
            self.manifests[package] = VerifiedManifest(
                spec, index, digest_crc(manifest_bytes), receipt, False)
            # Simulate previously downloaded and verified private Bundle cache.
            from wlre.services.official_bundle_download import spec_from_manifest
            bundle = spec_from_manifest(data_ver=DATA_VER, package=package,
                                        index=index, name=name)
            destination = bundle.cache_path(self.bundle_root)
            destination.parent.mkdir(parents=True)
            destination.write_bytes(bundle_bytes)

    def plan(self, bindings=None):
        return plan_catalog_pipeline(
            self.snapshot, self.manifests,
            self.bindings if bindings is None else bindings,
            bundle_root=self.bundle_root)

    def test_exact_asset_resolution_with_independent_package_versions(self):
        plan = self.plan()
        self.assertEqual(len(plan.sources), 4)
        self.assertEqual(set(p.package for p in plan.updates),
                         {'DataPackage', 'MainPackage'})
        self.assertEqual({p.download_count for p in plan.updates}, {0})
        self.assertEqual([p.full_version for p in plan.identity.packages],
                         [DATA_REV, MAIN_REV])
        self.assertEqual(len(plan.catalog_key), 64)
        self.assertFalse(plan.summary()['assets_ready'])

    def test_preview_never_runs_extractor_or_sends_packets(self):
        plan = self.plan()
        result, parsed = run_catalog_pipeline(plan, bundle_root=self.bundle_root)
        self.assertEqual(parsed, {})
        self.assertEqual(result['mode'], 'preview')
        self.assertEqual(result['parsed_features'], 0)
        self.assertFalse(result['assets_ready'])

    def test_synced_verified_bundles_feed_all_four_adapters(self):
        plan = self.plan()
        observed = []
        def extractor(binding, paths):
            observed.append((binding.contract.feature, paths))
            self.assertTrue(all(p.is_file() for p in paths))
            return self.source_data[binding.contract.feature]
        result, parsed = run_catalog_pipeline(
            plan, download=True, extractor=extractor, bundle_root=self.bundle_root)
        self.assertEqual(result['parsed_features'], 4)
        self.assertEqual(set(parsed), {'npc', 'shops', 'crafting', 'scenes'})
        self.assertEqual(len(observed), 4)
        self.assertTrue(all(not p.can_send_packets and not p.assets_ready
                            for p in parsed.values()))
        self.assertFalse(result['assets_ready'])

    def test_wrong_assetpath_rejected_without_heuristic_fallback(self):
        mismatched = list(self.bindings)
        mismatched[0] = AssetBinding('Assets/Test/npc_missing',
                                     mismatched[0].contract)
        with self.assertRaisesRegex(OfficialCatalogPipelineError, 'AssetPath missing'):
            self.plan(mismatched)

    def test_outdated_contract_revision_rejected(self):
        mismatched = list(self.bindings)
        original = mismatched[0]
        c = original.contract
        mismatched[0] = AssetBinding(original.asset_path, SourceContract(
            c.feature, c.source_name, c.schema_id, c.expected_sha256,
            c.package, MAIN_REV))
        with self.assertRaisesRegex(OfficialCatalogPipelineError, 'revision'):
            self.plan(mismatched)

    def test_missing_feature_and_duplicate_feature_rejected(self):
        with self.assertRaisesRegex(OfficialCatalogPipelineError, 'one reviewed'):
            self.plan(self.bindings[:3])
        with self.assertRaisesRegex(OfficialCatalogPipelineError, 'one reviewed'):
            self.plan([*self.bindings[:3], self.bindings[0]])

    def test_invalid_manifests_and_tampered_local_hash(self):
        altered = dict(self.manifests)
        original = altered['MainPackage']
        altered['MainPackage'] = VerifiedManifest(
            original.spec, original.index, '00000000',
            original.cache_path, False)
        with self.assertRaises(ValueError):
            plan_catalog_pipeline(self.snapshot, altered, self.bindings,
                                  bundle_root=self.bundle_root)
        # Already planned cache was tampered with; do not call extractor.
        plan = self.plan()
        target = next(row.spec.cache_path(self.bundle_root)
                      for update in plan.updates for row in update.entries
                      if update.package == 'MainPackage')
        target.write_bytes(b'tampered')
        calls = []
        with self.assertRaises(ValueError):
            run_catalog_pipeline(plan, download=True,
                                 extractor=lambda *args: calls.append(args),
                                 bundle_root=self.bundle_root, max_downloads=0)
        self.assertFalse(calls)

    def test_extractor_bad_sha_refuses_all_returned_catalogs(self):
        plan = self.plan()
        with self.assertRaisesRegex(OfficialCatalogPipelineError, 'no catalog activated'):
            run_catalog_pipeline(
                plan, download=True, bundle_root=self.bundle_root,
                extractor=lambda binding, paths: b'wrong-derived-content')

    def test_no_implicit_extraction(self):
        plan = self.plan()
        with self.assertRaisesRegex(OfficialCatalogPipelineError, 'explicit sync'):
            run_catalog_pipeline(plan, download=False,
                                 extractor=lambda binding, paths: b'',
                                 bundle_root=self.bundle_root)

    def test_current_versions_fetch_both_verified_manifests(self):
        observed = []
        def retrieve(spec, *, cache_root=None):
            observed.append(spec.package)
            return self.manifests[spec.package]
        plan = plan_current_catalog(
            self.bindings, observe=lambda: self.snapshot, retrieve=retrieve,
            previous_finder=lambda current, cache_root=None: None,
            bundle_root=self.bundle_root)
        self.assertEqual(observed, ['DataPackage', 'MainPackage'])
        self.assertEqual(len(plan.sources), 4)


if __name__ == '__main__':
    unittest.main()
