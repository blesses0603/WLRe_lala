"""Synthetic Bundle payloads only; no game resources or network needed."""

import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import zlib

from wlre.services.official_bundle_download import (
    BundleDownloadError, BundleSpec, fetch_bundle, spec_from_manifest,
)


BODY = b'LaLa synthetic bundle fixture, not a game asset.\n' * 16
HASH = hashlib.md5(BODY, usedforsecurity=False).hexdigest()
CRC = (zlib.crc32(BODY) & 0xffffffff).to_bytes(4, 'little').hex()


def spec():
    return BundleSpec('1.3.21', 'DataPackage', '1275_2026_10_21_18_27_33_84',
                      'datapackage_data_v.bundle', len(BODY), HASH, CRC)


class FakeResponse(io.BytesIO):
    status = 200

    def __init__(self, url, body=BODY, declared=None):
        super().__init__(body)
        self.url = url
        self.headers = {'Content-Length': str(len(body) if declared is None else declared)}

    def geturl(self):
        return self.url


class BundleDownloadTests(unittest.TestCase):
    def test_manifest_crc_is_little_endian_not_conventional_crc_hex(self):
        self.assertEqual(CRC, zlib.crc32(BODY).to_bytes(4, 'little').hex())
        self.assertNotEqual(CRC, f'{zlib.crc32(BODY) & 0xffffffff:08x}')

    def test_known_1275_url_is_strictly_derived(self):
        value = spec()
        self.assertEqual(value.url,
                         'https://wlreftpsrc.chinesegamer.net/WLN/TW/1.3.21/'
                         'ResourcesPC/AssetBundle/datapackage_data_v.bundle')

    def test_verify_and_reuse_cache_without_second_network_request(self):
        value = spec()
        called = []
        def opener(req, timeout):
            called.append(req.full_url)
            return FakeResponse(req.full_url)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            location = fetch_bundle(value, cache_root=root, opener=opener)
            self.assertEqual(location.read_bytes(), BODY)
            self.assertEqual(fetch_bundle(value, cache_root=root, opener=opener), location)
            self.assertEqual(called, [value.url])

    def test_invalid_content_rejected_without_partial_file(self):
        value = spec()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(BundleDownloadError):
                fetch_bundle(value, cache_root=root,
                             opener=lambda req, timeout: FakeResponse(req.full_url, b'bad'))
            self.assertFalse(value.cache_path(root).exists())
            self.assertEqual(list(root.rglob('*.partial')), [])

    def test_wrong_hash_or_redirect_rejected(self):
        value = spec()
        wrong = BundleSpec(value.data_ver, value.package, value.package_version,
                           value.name, value.file_size, '0'*32, value.file_crc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(BundleDownloadError):
                fetch_bundle(wrong, cache_root=root,
                             opener=lambda req, timeout: FakeResponse(req.full_url))
            with self.assertRaises(BundleDownloadError):
                fetch_bundle(value, cache_root=root,
                             opener=lambda req, timeout: FakeResponse('https://evil.example/file'))

    def test_invalid_bundle_names_cannot_escape_cache(self):
        value = spec()
        for name in ('../secrets.bundle', 'bad/bundle.bundle', 'DATA_v.bundle?x=1',
                     'https://evil.example/a.bundle'):
            with self.subTest(name=name), self.assertRaises(BundleDownloadError):
                BundleSpec(value.data_ver, value.package, value.package_version,
                           name, value.file_size, value.file_hash, value.file_crc)

    def test_manifest_record_must_match_package(self):
        value = spec()
        index = {'header': {'package_name': value.package,
                            'package_version': value.package_version,
                            'file_version': '2.2.5', 'output_name_style': 1},
                 'bundles': [{'name': value.name, 'file_size': value.file_size,
                              'file_hash': value.file_hash, 'file_crc': value.file_crc}]}
        self.assertEqual(spec_from_manifest(data_ver=value.data_ver,
                                             package=value.package,
                                             index=index, name=value.name), value)
        with self.assertRaises(BundleDownloadError):
            spec_from_manifest(data_ver=value.data_ver,
                               package='MainPackage', index=index, name=value.name)


if __name__ == '__main__':
    unittest.main()
