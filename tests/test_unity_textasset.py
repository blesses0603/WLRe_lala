"""Offline bounded extraction tests; mocks UnityPy but not origin verification."""
import hashlib
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wlre.services.world.catalog_adapters import SourceContract
from wlre.services.world.official_catalog_pipeline import AssetBinding
from wlre.services.world.unity_textasset import UnityTextAssetError, extract_textasset


def _header():
    # Minimal structurally valid UnityFS header; decoder is stubbed.
    head = (b'UnityFS\x00' + struct.pack('>I', 6) + b'5.x.x\x00'
            + b'2019.4.0f1\x00')
    size = len(head) + 20 + 20
    return head + struct.pack('>QIII', size, 20, 64, 0x40) + b'\x00' * 20


class TextAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = b'\x00\xfe\x01\xffexample\x00'
        self.asset_path = 'Assets/ResourcesBuild/Data/SmithData_C.bytes'
        self.binding = AssetBinding(self.asset_path, SourceContract(
            'crafting', 'SmithData_C', 'smith-new-33-v1',
            hashlib.sha256(self.raw).hexdigest(), 'DataPackage',
            '1275_2026_10_21_18_27_33_84'))
        self.first = self.root / 'data_s.bundle'
        self.first.write_bytes(_header())

    def loader(self, *, script=None, asset_name='SmithData_C', kind='TextAsset', key=None):
        body = self.raw if script is None else script
        obj = SimpleNamespace(type=SimpleNamespace(name=kind), read=lambda:
                              SimpleNamespace(name=asset_name, script=body))
        return lambda path: SimpleNamespace(container={key or self.asset_path: obj})

    def test_exact_path_textasset_binary_roundtrip(self):
        self.assertEqual(extract_textasset(self.binding, (self.first,),
                                           loader=self.loader()), self.raw)

    def test_surrogateescape_binary_roundtrip(self):
        surrogate = self.raw.decode('utf8', 'surrogateescape')
        self.assertEqual(extract_textasset(self.binding, (self.first,),
                                           loader=self.loader(script=surrogate)), self.raw)

    def test_wrong_path_never_falls_back_to_name(self):
        with self.assertRaisesRegex(UnityTextAssetError, 'Exact AssetPath'):
            extract_textasset(self.binding, (self.first,), loader=self.loader(
                key='Assets/Another/SmithData_C.bytes'))

    def test_wrong_class_or_asset_name_is_rejected(self):
        with self.assertRaisesRegex(UnityTextAssetError, 'TextAsset'):
            extract_textasset(self.binding, (self.first,),
                              loader=self.loader(kind='Texture2D'))
        with self.assertRaisesRegex(UnityTextAssetError, 'identity'):
            extract_textasset(self.binding, (self.first,),
                              loader=self.loader(asset_name='OtherData_C'))

    def test_unityfs_magic_and_header_required(self):
        self.first.write_bytes(b'UnityFS\x00' + b'bad')
        with self.assertRaises(UnityTextAssetError):
            extract_textasset(self.binding, (self.first,), loader=self.loader())

    def test_duplicate_asset_and_non_unique_bundle_rejected(self):
        second = self.root / 'second.bundle'
        second.write_bytes(_header())
        with self.assertRaisesRegex(UnityTextAssetError, 'Duplicate TextAsset'):
            extract_textasset(self.binding, (self.first, second), loader=self.loader())
        with self.assertRaisesRegex(UnityTextAssetError, 'Duplicated Bundle'):
            extract_textasset(self.binding, (self.first, self.first), loader=self.loader())

    def test_empty_or_excessive_payload_is_rejected(self):
        for value in (b'', b'0' * (16*1024*1024+1)):
            with self.assertRaises(UnityTextAssetError):
                extract_textasset(self.binding, (self.first,),
                                  loader=self.loader(script=value))

    def test_bad_loader_and_missing_package(self):
        with self.assertRaises(UnityTextAssetError):
            extract_textasset(self.binding, (self.first,), loader=123)
        with patch('wlre.services.world.unity_textasset._loader',
                   side_effect=UnityTextAssetError('UnityPy missing')):
            with self.assertRaisesRegex(UnityTextAssetError, 'UnityPy missing'):
                extract_textasset(self.binding, (self.first,))


if __name__ == '__main__':
    unittest.main()
