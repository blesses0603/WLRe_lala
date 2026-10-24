"""Private-only CLI requirements and historical-cache regression checks."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

from test_official_incremental_sync import manifest, OLD_VERSION
from test_official_manifest_integration import FakeResponse, synthetic_manifest
from tools.plan_official_incremental import (
    IncrementalSyncError, execute_plans, load_private_requirements,
    plan_required_updates, private_report,
)
from wlre.services.official_incremental_sync import find_previous_verified_manifest
from wlre.services.official_manifest_sync import ManifestSpec, fetch_official_manifest


class IncrementalCliTests(unittest.TestCase):
    def test_private_json_exact_selectors_and_reject_globs(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'requirements.json'
            payload = {'schema_version': 1,
                       'packages': {'DataPackage': {
                           'asset_paths': ['Assets/Synthetic/example.txt'],
                           'bundle_names': []}}}
            config.write_text(json.dumps(payload), encoding='utf-8')
            # Executor test mounts contain a placeholder /tmp/.git; bypass
            # only that location guard here to test the JSON schema itself.
            with patch('tools.plan_official_incremental._require_private_path',
                       side_effect=lambda path: Path(path)):
                result = load_private_requirements(config)
            self.assertEqual(result['DataPackage']['asset_paths'],
                             ['Assets/Synthetic/example.txt'])
            payload['packages']['DataPackage']['asset_paths'] = ['Assets/*']
            config.write_text(json.dumps(payload), encoding='utf-8')
            with patch('tools.plan_official_incremental._require_private_path',
                       side_effect=lambda path: Path(path)):
                with self.assertRaisesRegex(IncrementalSyncError, 'exact selectors'):
                    load_private_requirements(config)

    def test_planner_and_private_report_dont_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = manifest()
            summary = {
                'schema_version': 1, 'origin': 'official_pc_version_endpoint',
                'data_ver': '1.3.21', 'exe_version': '1.3.21',
                'packages': {'DataPackage': current.spec.package_version,
                             'MainPackage': '1275_2026_10_21_18_29_38_49'},
                'checked_at_utc': '2026-10-24T00:00:00+00:00', 'assets_ready': False,
            }
            observed = []

            def retrieve(spec, cache_root):
                observed.append(spec.package)
                return current

            requirements = {'DataPackage': {'asset_paths': ['Assets/Synthetic/example.txt'],
                                            'bundle_names': []}}
            plans = plan_required_updates(requirements, observe=lambda: summary,
                                          retrieve=retrieve,
                                          previous_finder=lambda cur, cache_root: None,
                                          cache_root=tmp, bundle_root=tmp)
            self.assertEqual(observed, ['DataPackage'])
            results = execute_plans(plans)
            self.assertEqual(results[0]['mode'], 'preview')
            with self.assertRaisesRegex(IncrementalSyncError, 'Combined Bundle plan exceeds'):
                execute_plans(plans * 2, download=True,
                              max_bytes=plans[0].download_bytes, max_files=1)
            filename = Path(tmp) / 'plan.json'
            with patch('tools.plan_official_incremental._require_private_path',
                       side_effect=lambda path: Path(path)):
                private_report(plans, results, filename)
            content = json.loads(filename.read_text(encoding='utf-8'))
            self.assertEqual(len(content['packages'][0]['needed_bundles']), 1)
            with patch('tools.plan_official_incremental._require_private_path',
                       side_effect=lambda path: Path(path)):
                with self.assertRaisesRegex(IncrementalSyncError, 'Cannot create'):
                    private_report(plans, results, filename)

    def test_find_prior_verified_manifest_from_receipt_without_network(self):
        body = synthetic_manifest(package_version=OLD_VERSION)
        expected = zlib.crc32(body).to_bytes(4, 'little').hex().encode('ascii')

        def opener(req, timeout):
            value = expected if req.full_url.endswith('.hash') else body
            return FakeResponse(req.full_url, value)

        with tempfile.TemporaryDirectory() as tmp:
            old_spec = ManifestSpec('1.3.21', 'DataPackage', OLD_VERSION)
            fetch_official_manifest(old_spec, cache_root=tmp, opener=opener)
            previous = find_previous_verified_manifest(manifest(), cache_root=tmp)
            self.assertIsNotNone(previous)
            self.assertEqual(previous.spec.package_version, OLD_VERSION)
            self.assertEqual(previous.index['asset_count'], 1)


if __name__ == '__main__':
    unittest.main()
