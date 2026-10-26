"""Offline audit regression. Synthetic YooAsset archives, no CDN or game login."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock
import zipfile
import zlib

from tools.verify_official_local_bundles import (
    OfflineVerificationError, inspect_manifest_zip, verify_local,
)

DATA_REV = '1275_2026_10_21_18_27_33_84'
MAIN_REV = '1275_2026_10_21_18_29_38_49'
PREFIX = 'Assets/ResourcesBuild/Data/'


def u8(s):
    raw = s.encode('utf-8')
    return struct.pack('<H', len(raw)) + raw


def string_list(items):
    return struct.pack('<H', len(items)) + b''.join(u8(x) for x in items)


def int_list(items):
    return struct.pack('<H', len(items)) + b''.join(struct.pack('<i', n) for n in items)


def fixture_manifest(package, rev, blobs):
    """Use the real YooAsset 2.2.5 field layout and exact four AssetPaths."""
    data = struct.pack('<I', 0x00594F4F) + u8('2.2.5')
    data += struct.pack('<BBBii', 1, 0, 0, 1, 2)
    data += u8('ScriptableBuildPipeline') + u8(package) + u8(rev) + u8(package)
    assets = ([
        ('Eve.bytes', 0), ('ItemData_C.bytes', 1),
        ('SmithData_C.bytes', 2), ('ScenesData_C.bytes', 2),
    ] if package == 'DataPackage' else [])
    data += struct.pack('<i', len(assets))
    for asset, bid in assets:
        path = PREFIX + asset
        data += u8(path) + u8(path) + u8('') + string_list([]) + struct.pack('<i', bid)
    data += struct.pack('<i', len(blobs))
    for name, body in blobs:
        data += (u8(name) + struct.pack('<I', 0) +
                 u8(hashlib.md5(body).hexdigest()) +
                 u8((zlib.crc32(body) & 0xffffffff).to_bytes(4, 'little').hex()) +
                 struct.pack('<qB', len(body), 0) +
                 string_list([]) + int_list([]))
    return data


def make_zip(path, package, rev, blobs):
    raw = fixture_manifest(package, rev, blobs)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(f'{package}_{rev}.bytes', raw)
        z.writestr(f'{package}_{rev}.hash',
                   (zlib.crc32(raw) & 0xffffffff).to_bytes(4, 'little').hex())


class OfflineVerifierTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.data_zip = self.root / 'DataPackage.zip'
        self.main_zip = self.root / 'MainPackage.zip'
        self.bundle_dir = self.root / 'bundles'
        self.bundle_dir.mkdir()
        self.names = (
            'datapackage_data_e.bundle',
            'datapackage_data_i.bundle',
            'datapackage_data_s.bundle')
        self.payloads = (b'UnityFS-fixture-e', b'UnityFS-fixture-i',
                         b'UnityFS-fixture-s')
        make_zip(self.data_zip, 'DataPackage', DATA_REV,
                 list(zip(self.names, self.payloads)))
        make_zip(self.main_zip, 'MainPackage', MAIN_REV, [])

    def kwargs(self, **extra):
        values = {'data_zip': self.data_zip, 'main_zip': self.main_zip,
                  'data_ver': '1.3.21'}
        values.update(extra)
        return values

    def test_both_full_manifests_resolve_four_assets_to_three_bundles(self):
        report = verify_local(**self.kwargs())
        self.assertEqual([p['bundle_count'] for p in report['packages']], [3, 0])
        self.assertEqual(report['required_bundle_count'], 3)
        self.assertEqual(report['features']['npc'], [self.names[0]])
        self.assertEqual(report['features']['shops'], list(self.names[:2]))
        self.assertEqual(report['features']['crafting'], [self.names[2]])
        self.assertEqual(report['features']['scenes'], [self.names[2]])
        self.assertFalse(report['live_official_authentication'])
        self.assertFalse(report['assets_ready'])
        self.assertFalse(report['decoded'])
        self.assertTrue(all(x['status'] == 'missing' for x in report['bundles'].values()))

    def test_manifest_hash_corruption_is_refused_before_bundle_parsing(self):
        with zipfile.ZipFile(self.data_zip, 'r') as z:
            name = next(k for k in z.namelist() if k.endswith('.bytes'))
            raw = z.read(name)
            hashed = next(k for k in z.namelist() if k.endswith('.hash'))
        with zipfile.ZipFile(self.data_zip, 'w') as z:
            z.writestr(name, raw)
            z.writestr(hashed, b'00000000')
        with self.assertRaisesRegex(OfflineVerificationError, 'CRC32'):
            verify_local(**self.kwargs())

    def test_verify_real_file_hashes_before_any_decode(self):
        for name, raw in zip(self.names, self.payloads):
            (self.bundle_dir / name).write_bytes(raw)
        report = verify_local(**self.kwargs(bundle_dir=self.bundle_dir))
        self.assertTrue(all(x['status'] == 'verified' for x in report['bundles'].values()))
        self.assertFalse(report['decoded'])
        (self.bundle_dir / self.names[0]).write_bytes(b'wrong')
        extract = Mock(side_effect=AssertionError('decoder must not be used'))
        with self.assertRaisesRegex(OfflineVerificationError, 'MD5/CRC'):
            verify_local(**self.kwargs(bundle_dir=self.bundle_dir,
                                       decode=True, extractor=extract))
        extract.assert_not_called()

    def test_official_game_yoo_hashed_data_is_read_only(self):
        yoo = self.root / 'WLRE_Data' / 'yoo'
        base = yoo / 'DataPackage' / 'BundleFiles' / '00'
        for idx, raw in enumerate(self.payloads):
            storage = base / (f'{idx:032x}')
            storage.mkdir(parents=True)
            (storage / '__data').write_bytes(raw)
        fake = base / '99999999999999999999999999999999'
        fake.mkdir(parents=True)
        (fake / '__data').write_bytes(b'other bundle')
        report = verify_local(**self.kwargs(game_yoo=yoo))
        self.assertEqual(report['required_bundle_count'], 3)
        self.assertTrue(all(row['status'] == 'verified'
                            for row in report['bundles'].values()))
        self.assertFalse(report['decoded'])
        self.assertEqual(sorted(p.name for p in base.rglob('__data')),
                         ['__data'] * 4)
        # The helper must not rename original hashed files or create a cache.
        self.assertTrue((base / f'{0:032x}' / '__data').exists())

    def test_hashed_game_file_with_wrong_md5_cannot_decode(self):
        yoo = self.root / 'WLRE_Data' / 'yoo'
        base = yoo / 'DataPackage' / 'BundleFiles' / '00' / ('f' * 32)
        base.mkdir(parents=True)
        (base / '__data').write_bytes(b'0' * len(self.payloads[0]))
        extract = Mock()
        with self.assertRaisesRegex(OfflineVerificationError, 'MD5/CRC'):
            verify_local(**self.kwargs(game_yoo=yoo, decode=True,
                                       extractor=extract))
        extract.assert_not_called()

    def test_decode_all_features_without_ever_approving_gameplay(self):
        for name, raw in zip(self.names, self.payloads):
            (self.bundle_dir / name).write_bytes(raw)
        def extractor(binding, paths):
            feature = binding.contract.feature
            if feature in ('npc', 'shops'):
                return json.dumps({
                    'schema_version': 1,
                    'source': binding.contract.source_name,
                    'record_count': 0,
                    'scenes': {},
                }).encode()
            return struct.pack('<i', 0)
        report = verify_local(**self.kwargs(bundle_dir=self.bundle_dir,
                                            decode=True, extractor=extractor))
        self.assertTrue(report['decoded'])
        self.assertEqual(set(report['decoded_features']),
                         {'npc', 'shops', 'crafting', 'scenes'})
        self.assertFalse(report['approved'])
        self.assertFalse(report['can_send_packets'])
        self.assertFalse(report['assets_ready'])

    def test_parser_failure_is_reported_without_partial_activation(self):
        for name, raw in zip(self.names, self.payloads):
            (self.bundle_dir / name).write_bytes(raw)
        with self.assertRaisesRegex(OfflineVerificationError, 'Unrecognized npc'):
            verify_local(**self.kwargs(bundle_dir=self.bundle_dir,
                                       decode=True, extractor=lambda *_: b'bad'))

    def test_reject_decoding_without_bundle_source(self):
        with self.assertRaisesRegex(OfflineVerificationError, 'Bundle'):
            verify_local(**self.kwargs(decode=True))


if __name__ == '__main__':
    unittest.main()
