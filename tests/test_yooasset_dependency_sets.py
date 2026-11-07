"""YooAsset 2.2.10 GetAllDependencies semantics, using synthetic bundles."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import zlib
from wlre.services.official_manifest_sync import ManifestSpec, VerifiedManifest
from wlre.services.official_incremental_sync import build_update_plan, execute_update_plan, IncrementalSyncError


def manifest(edges):
    spec = ManifestSpec('1.3.23', 'MainPackage', '1296_2026_11_04_13_36_07_72')
    rows = []
    for name, deps in edges.items():
        raw = name.encode()
        rows.append(dict(name=name, dependencies=deps, file_hash=hashlib.md5(raw).hexdigest(),
                         file_crc=zlib.crc32(raw).to_bytes(4, 'little').hex(),
                         file_size=len(raw), unity_crc=0, encrypted=False, tags=[]))
    index = dict(header=dict(file_version='2.2.5', package_name=spec.package,
                            package_version=spec.package_version, output_name_style=1),
                 bundles=rows, assets=[dict(path='Assets/Synthetic.asset', bundle_name='root.bundle')])
    return VerifiedManifest(spec, index, '00000000', Path('/synthetic.bytes'), False)


class DependencySetTests(unittest.TestCase):
    def plan(self, edges, roots=('root.bundle',)):
        with tempfile.TemporaryDirectory() as directory:
            return build_update_plan(manifest(edges), bundle_names=roots, cache_root=directory)

    def test_mutual_complete_sets_are_finite_and_unique(self):
        plan = self.plan({'root.bundle': ['dep.bundle'], 'dep.bundle': ['root.bundle']})
        self.assertEqual([r.spec.name for r in plan.entries], ['dep.bundle', 'root.bundle'])
        self.assertEqual(plan.download_count, 2)

    def test_lists_are_not_recursively_reinterpreted(self):
        edges = {'root.bundle': ['dep.bundle'], 'dep.bundle': ['extra.bundle'], 'extra.bundle': []}
        self.assertEqual({r.spec.name for r in self.plan(edges).entries}, {'root.bundle', 'dep.bundle'})
        self.assertEqual(len(self.plan(edges, ('root.bundle', 'dep.bundle')).entries), 3)

    def test_duplicate_selectors_and_dependencies_do_not_duplicate_downloads(self):
        plan = self.plan({'root.bundle': ['dep.bundle', 'dep.bundle'], 'dep.bundle': []}, ('root.bundle', 'root.bundle'))
        self.assertEqual(plan.download_count, 2)

    def test_missing_dependency_still_rejected(self):
        with self.assertRaisesRegex(IncrementalSyncError, 'Missing Bundle dependency'):
            self.plan({'root.bundle': ['missing.bundle']})

    def test_asset_selection_matches_explicit_root(self):
        m = manifest({'root.bundle': ['dep.bundle'], 'dep.bundle': ['root.bundle']})
        with tempfile.TemporaryDirectory() as directory:
            p = build_update_plan(m, asset_paths=['Assets/Synthetic.asset'], cache_root=directory)
        self.assertEqual([r.spec.name for r in p.entries], ['dep.bundle', 'root.bundle'])

    def test_cycle_does_not_bypass_download_budget(self):
        p = self.plan({'root.bundle': ['dep.bundle'], 'dep.bundle': ['root.bundle']})
        opener = Mock(side_effect=AssertionError('network'))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(IncrementalSyncError):
                execute_update_plan(p, cache_root=directory, download=True, max_download_bytes=1, opener=opener)
        opener.assert_not_called()
