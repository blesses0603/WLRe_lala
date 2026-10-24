"""Dependency and quota tests; never touches official CDN or game assets."""

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
import zlib

from test_official_manifest_integration import (
    BUNDLE_BODY, BUNDLE_NAME, PACKAGE_VERSION, FakeResponse, synthetic_manifest,
)
from tools.resources.lala_manifest_full_index import parse_manifest
from wlre.services.official_incremental_sync import (
    IncrementalSyncError, build_update_plan, execute_update_plan,
)
from wlre.services.official_manifest_sync import ManifestSpec, VerifiedManifest


OLD_VERSION = '1262_2026_10_20_18_27_33_84'
DEPENDENCY = b'This is another synthetic dependency file'


def manifest(version=PACKAGE_VERSION, *, dependencies=False):
    data = deepcopy(parse_manifest(synthetic_manifest()))
    data['header']['package_version'] = version
    if dependencies:
        md5 = hashlib.md5(DEPENDENCY, usedforsecurity=False).hexdigest()
        crc = zlib.crc32(DEPENDENCY).to_bytes(4, 'little').hex()
        data['bundles'].append({
            'name': 'synthetic_dep.bundle', 'unity_crc': 0,
            'file_hash': md5, 'file_crc': crc, 'file_size': len(DEPENDENCY),
            'encrypted': False, 'tags': [], 'dependency_ids': [], 'dependencies': [],
        })
        data['bundles'][0]['dependencies'] = ['synthetic_dep.bundle']
    spec = ManifestSpec('1.3.21', 'DataPackage', version)
    return VerifiedManifest(spec, data, 'aabbccdd', Path('/private/synthetic.bytes'), False)


class IncrementalPlanTests(unittest.TestCase):
    def test_no_implicit_bulk_selection_or_missing_asset(self):
        with self.assertRaisesRegex(IncrementalSyncError, 'Explicit required'):
            build_update_plan(manifest())
        with self.assertRaisesRegex(IncrementalSyncError, 'Required resources missing'):
            build_update_plan(manifest(), asset_paths=['Assets/NotFound.prefab'])

    def test_dependency_closure_is_downloaded_before_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_update_plan(manifest(dependencies=True),
                                     asset_paths=['Assets/Synthetic/example.txt'], cache_root=tmp)
            self.assertEqual([x.spec.name for x in plan.entries],
                             ['synthetic_dep.bundle', BUNDLE_NAME])
            self.assertEqual(plan.download_count, 2)
            self.assertEqual(plan.download_bytes, len(BUNDLE_BODY) + len(DEPENDENCY))
            self.assertEqual(plan.summary()['required_asset_count'], 1)
            self.assertNotIn('Assets/Synthetic/example.txt', str(plan.summary()))
            self.assertFalse(plan.summary()['assets_ready'])

    def test_manifest_diff_tracks_modified_and_removed_without_scheduling_all(self):
        current = manifest(dependencies=True)
        previous = manifest(OLD_VERSION, dependencies=True)
        previous.index['bundles'][1]['file_hash'] = '0' * 32
        previous.index['bundles'].append({
            **deepcopy(previous.index['bundles'][1]), 'name': 'removed_old.bundle',
            'dependencies': [],
        })
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_update_plan(current, previous=previous,
                                     bundle_names=[BUNDLE_NAME], cache_root=tmp)
            self.assertEqual((plan.added_count, plan.modified_count, plan.removed_count),
                             (0, 1, 1))
            self.assertEqual([x.change for x in plan.entries],
                             ['modified', 'unchanged'])
            self.assertEqual(len(plan.entries), 2)

    def test_identical_verified_old_bundle_reused_without_network(self):
        current, previous = manifest(), manifest(OLD_VERSION)
        with tempfile.TemporaryDirectory() as tmp:
            old = previous.index['bundles'][0]
            from wlre.services.official_bundle_download import spec_from_manifest
            old_spec = spec_from_manifest(data_ver='1.3.21', package='DataPackage',
                                          index=previous.index, name=old['name'])
            old_path = old_spec.cache_path(tmp)
            old_path.parent.mkdir(parents=True)
            old_path.write_bytes(BUNDLE_BODY)
            plan = build_update_plan(current, previous=previous,
                                     asset_paths=['Assets/Synthetic/example.txt'],
                                     cache_root=tmp)
            self.assertEqual(plan.entries[0].action, 'reuse_previous')
            self.assertEqual(plan.download_bytes, 0)
            result = execute_update_plan(plan, cache_root=tmp, download=True,
                                         max_download_bytes=0, max_downloads=0)
            self.assertEqual(result['completed'], 1)
            self.assertFalse(result['assets_ready'])
            self.assertEqual(plan.entries[0].spec.cache_path(tmp).read_bytes(), BUNDLE_BODY)

    def test_1276_next_week_and_new_dataver_reuse_unchanged_content(self):
        previous = manifest()
        current = manifest('1276_2026_10_29_08_00_00_01')
        current_spec = ManifestSpec('1.3.22', 'DataPackage',
                                    '1276_2026_10_29_08_00_00_01')
        current = VerifiedManifest(current_spec, current.index, current.hash_text,
                                   current.cache_path, current.downloaded)
        with tempfile.TemporaryDirectory() as tmp:
            from wlre.services.official_bundle_download import spec_from_manifest
            old = spec_from_manifest(data_ver=previous.spec.data_ver,
                                     package='DataPackage', index=previous.index,
                                     name=BUNDLE_NAME)
            old_path = old.cache_path(tmp)
            old_path.parent.mkdir(parents=True)
            old_path.write_bytes(BUNDLE_BODY)
            plan = build_update_plan(current, previous=previous,
                                     bundle_names=[BUNDLE_NAME], cache_root=tmp)
            self.assertEqual(plan.data_ver, '1.3.22')
            self.assertEqual(plan.package_version, current_spec.package_version)
            self.assertEqual(plan.entries[0].action, 'reuse_previous')
            self.assertEqual(plan.download_bytes, 0)

    def test_download_is_opt_in_and_quota_checked_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_update_plan(manifest(), bundle_names=[BUNDLE_NAME], cache_root=tmp)
            requests = []

            def opener(req, timeout):
                requests.append(req.full_url)
                return FakeResponse(req.full_url, BUNDLE_BODY)

            self.assertEqual(execute_update_plan(plan, cache_root=tmp)['mode'], 'preview')
            with self.assertRaisesRegex(IncrementalSyncError, 'quota'):
                execute_update_plan(plan, cache_root=tmp, download=True,
                                    max_download_bytes=len(BUNDLE_BODY) - 1, opener=opener)
            self.assertEqual(requests, [])
            result = execute_update_plan(plan, cache_root=tmp, download=True,
                                         max_download_bytes=len(BUNDLE_BODY),
                                         max_downloads=1, opener=opener)
            self.assertEqual(result['completed'], 1)
            self.assertEqual(len(requests), 1)

    def test_corrupt_previous_cache_forces_download_instead_of_reuse(self):
        current, previous = manifest(), manifest(OLD_VERSION)
        with tempfile.TemporaryDirectory() as tmp:
            from wlre.services.official_bundle_download import spec_from_manifest
            old = spec_from_manifest(data_ver='1.3.21', package='DataPackage',
                                     index=previous.index, name=BUNDLE_NAME)
            source = old.cache_path(tmp)
            source.parent.mkdir(parents=True)
            source.write_bytes(b'corrupt')
            plan = build_update_plan(current, previous=previous,
                                     bundle_names=[BUNDLE_NAME], cache_root=tmp)
            self.assertEqual(plan.entries[0].action, 'download')

    def test_missing_dependency_or_cycle_fails_closed(self):
        current = manifest(dependencies=True)
        current.index['bundles'][1]['dependencies'] = [BUNDLE_NAME]
        with self.assertRaisesRegex(IncrementalSyncError, 'cycle'):
            build_update_plan(current, bundle_names=[BUNDLE_NAME])
        current.index['bundles'][1]['dependencies'] = ['unknown.bundle']
        with self.assertRaisesRegex(IncrementalSyncError, 'Missing Bundle dependency'):
            build_update_plan(current, bundle_names=[BUNDLE_NAME])


if __name__ == '__main__':
    unittest.main()
