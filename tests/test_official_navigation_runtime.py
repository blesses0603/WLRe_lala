import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from test_official_navigation_cache import cache
from wlre.services.world.official_cache_format import CacheError
from wlre.services.world import official_navigation as official
from wlre.services.world.navigation import Repository, NavigationError


class OfficialRuntime(unittest.TestCase):
    def setUp(self):
        self.blob = cache()
        self.pins = {'12170': {'cache_sha256': hashlib.sha256(self.blob).hexdigest(),
                              'cache_bytes': len(self.blob), 'faces': 1,
                              'scene_bundle_sha256': 'a' * 64, 'dependency_bundle_sha256': 'b' * 64}}
        self.patch = patch.object(official, 'fingerprints', return_value=self.pins)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def archive(self, blob=None, revision=1275):
        buffer = BytesIO()
        with ZipFile(buffer, 'w') as z:
            z.writestr('manifest.json', json.dumps({'resource_revision': revision,
                'kind': 'official_astar_startup_caches', 'models': ['12170']}))
            z.writestr('official/12170.zip', self.blob if blob is None else blob)
        return buffer.getvalue()

    def test_wrong_version_corrupted_cache_and_invalid_zip_are_rejected(self):
        for raw in (self.archive(revision=1262), self.archive(blob=self.blob + b'x'), b'not a ZIP'):
            with self.subTest(size=len(raw)):
                with self.assertRaises(CacheError): official.validate_archive(raw)

    def test_install_validates_before_writing_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'source.zip'
            target = Path(td) / 'private' / official.ARCHIVE
            source.write_bytes(b'bad')
            with self.assertRaises(CacheError): official.install(source, destination=target)
            self.assertFalse(target.parent.exists())
            source.write_bytes(self.archive())
            result = official.install(source, destination=target)
            self.assertEqual(result['models'], 1)
            self.assertFalse(result['can_send_packets'])
            before = target.read_bytes()
            with self.assertRaises(FileExistsError): official.install(source, destination=target)
            self.assertEqual(target.read_bytes(), before)
            self.assertFalse(list(target.parent.glob('.navigation-*')))

    def test_default_repository_uses_only_official_cache_and_exports_source(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / official.ARCHIVE
            path.write_bytes(self.archive())
            with patch('wlre.services.world.runtime_1275.baseline_revision', return_value='1275'), \
                 patch.object(official, 'default_path', return_value=path):
                repository = Repository()
                self.assertEqual(len(repository.catalog), 1)
                mesh = repository.load(12170)
                route = mesh.route([100, 100], [200, 200])
                self.assertEqual(route['source']['kind'], 'official_astar_startup_cache')
                self.assertEqual(route['source']['resource_revision'], 1275)
                self.assertFalse(route['can_send_packets'])
                self.assertFalse(route['original_node_flags_applied'])
                with self.assertRaises(NavigationError): repository.load(13216)

    def test_missing_or_corrupt_official_data_never_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'missing.zip'
            with patch('wlre.services.world.runtime_1275.baseline_revision', return_value='1275'), \
                 patch.object(official, 'default_path', return_value=path):
                for contents in (None, b'bad'):
                    if contents is not None: path.write_bytes(contents)
                    repository = Repository()
                    self.assertEqual(repository.catalog, [])
                    with self.assertRaises(NavigationError): repository.load(12170)

    def test_1275_coordinate_service_does_not_open_legacy_geometry(self):
        from wlre.services.world.coordinates import Coordinates
        with patch('wlre.services.world.runtime_1275.baseline_revision', return_value='1275'), \
             patch('wlre.services.world.coordinates.RESOURCE_ROOT', object()):
            converter = Coordinates()
            self.assertEqual(converter.stages, {})
            self.assertEqual(converter.origins, {})
            with self.assertRaises(NavigationError): converter.mapping(12170)

    def test_packager_accepts_only_exact_pinned_raw_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cache_path = root / '12170_official_cache.zip'
            cache_path.write_bytes(self.blob)
            output = root / official.ARCHIVE
            official.package([root], output)
            self.assertEqual(set(official.load_archive(output)), {'12170'})
            with self.assertRaises(FileExistsError): official.package([root], output)
            cache_path.write_bytes(self.blob + b'changed')
            with self.assertRaises(CacheError): official.package([root], root / 'other.zip')
