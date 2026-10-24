"""Integration with PR #53 full parser using only generated, non-game bytes."""

import hashlib
import io
import struct
import tempfile
import unittest
import zlib

from tools.check_official_manifests import inspect_current_manifests
from tools.resources.lala_manifest_full_index import parse_manifest
from wlre.services.official_bundle_download import fetch_bundle, spec_from_manifest
from wlre.services.official_manifest_sync import ManifestSpec, fetch_official_manifest


PACKAGE_VERSION = '1275_2026_10_21_18_27_33_84'
BUNDLE_BODY = b'Synthetic fixture, NOT a Unity asset.' * 10
BUNDLE_NAME = 'lala_synthetic_example.bundle'


def u16text(value):
    encoded = value.encode('utf-8')
    return struct.pack('<H', len(encoded)) + encoded


def synthetic_manifest(package_version=PACKAGE_VERSION):
    """One asset and one bundle, valid YooAsset 2.2.5 binary layout."""
    md5 = hashlib.md5(BUNDLE_BODY, usedforsecurity=False).hexdigest()
    crc_le = zlib.crc32(BUNDLE_BODY).to_bytes(4, 'little').hex()
    return b''.join((
        struct.pack('<I', 0x00594F4F), u16text('2.2.5'),
        b'\x00\x00\x00', struct.pack('<ii', 1, 0),
        u16text('ScriptableBuildPipeline'), u16text('DataPackage'),
        u16text(package_version), u16text(''),
        struct.pack('<i', 1),
        u16text('synthetic'), u16text('Assets/Synthetic/example.txt'),
        u16text('non-game-guid'), struct.pack('<H', 0), struct.pack('<i', 0),
        struct.pack('<i', 1), u16text(BUNDLE_NAME), struct.pack('<I', 0),
        u16text(md5), u16text(crc_le), struct.pack('<q', len(BUNDLE_BODY)),
        b'\x00', struct.pack('<H', 0), struct.pack('<H', 0),
    ))


class FakeResponse(io.BytesIO):
    status = 200

    def __init__(self, url, body):
        super().__init__(body)
        self.url = url
        self.headers = {'Content-Length': str(len(body))}

    def geturl(self):
        return self.url


class IntegrationTests(unittest.TestCase):
    def test_real_parser_remote_manifest_to_bundle_then_cache(self):
        body = synthetic_manifest()
        hash_text = zlib.crc32(body).to_bytes(4, 'little').hex().encode('ascii')
        calls = []

        def opener(req, timeout):
            calls.append(req.full_url)
            if req.full_url.endswith('DataPackage.hash'):
                return FakeResponse(req.full_url, hash_text)
            if req.full_url.endswith('DataPackage.bytes'):
                return FakeResponse(req.full_url, body)
            if req.full_url.endswith('/' + BUNDLE_NAME):
                return FakeResponse(req.full_url, BUNDLE_BODY)
            raise AssertionError('Unexpected source: ' + req.full_url)

        with tempfile.TemporaryDirectory() as tmp:
            spec = ManifestSpec('1.3.21', 'DataPackage', PACKAGE_VERSION)
            first = fetch_official_manifest(spec, cache_root=tmp, opener=opener)
            self.assertEqual(first.index, parse_manifest(body))
            self.assertEqual(len(first.index['assets']), 1)
            self.assertEqual(len(first.index['bundles']), 1)
            selected = spec_from_manifest(data_ver=spec.data_ver,
                                          package=spec.package, index=first.index,
                                          name=BUNDLE_NAME)
            location = fetch_bundle(selected, cache_root=tmp, opener=opener)
            self.assertEqual(location.read_bytes(), BUNDLE_BODY)
            self.assertEqual(fetch_bundle(selected, cache_root=tmp, opener=opener), location)
            cached = fetch_official_manifest(spec, cache_root=tmp, opener=opener)
            self.assertFalse(cached.downloaded)
            self.assertEqual(calls.count(spec.url('bytes')), 1)
            self.assertEqual(calls.count(selected.url), 1)

    def test_cli_summary_keeps_asset_paths_private_and_ready_false(self):
        manifest_index = parse_manifest(synthetic_manifest())

        def observe():
            return {
                'schema_version': 1, 'origin': 'official_pc_version_endpoint',
                'data_ver': '1.3.21', 'exe_version': '1.3.21',
                'packages': {'DataPackage': PACKAGE_VERSION,
                             'MainPackage': '1275_2026_10_21_18_29_38_49'},
                'checked_at_utc': '2026-10-24T00:00:00+00:00', 'assets_ready': False,
            }

        class Result:
            index = manifest_index
            hash_text = '11223344'
            downloaded = False

        summary = inspect_current_manifests(observe=observe, retrieve=lambda spec: Result(),
                                             packages=('DataPackage',))
        self.assertFalse(summary['assets_ready'])
        self.assertEqual(summary['packages']['DataPackage']['asset_count'], 1)
        self.assertEqual(summary['packages']['DataPackage']['bundle_count'], 1)
        self.assertNotIn('Assets/Synthetic/example.txt', str(summary))


if __name__ == '__main__':
    unittest.main()
