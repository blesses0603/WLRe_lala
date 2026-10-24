"""Catalog source bridge: raw Unity TextAsset -> reviewed format/derived Eve index."""
import hashlib
import unittest
from unittest.mock import patch

from wlre.services.world.catalog_adapters import SourceContract
from wlre.services.world.official_catalog_pipeline import AssetBinding
from wlre.services.world.catalog_source_extractor import (
    extract_catalog_source, UnityTextAssetError,
)


REV = '1275_2026_10_21_18_27_33_84'


def binding(feature, schema, asset, source):
    return AssetBinding(
        'Assets/ResourcesBuild/Data/' + asset,
        SourceContract(feature, source, schema, '0'*64, 'DataPackage', REV))


class CatalogSourceExtractorTests(unittest.TestCase):
    def test_npc_and_interact_use_eve_binary_converter(self):
        examples = (
            ('npc', 'eve-npc-json-v1', 'EventData.NewNpc'),
            ('shops', 'eve-interact-json-v1', 'EventData.NewInteract'),
        )
        for feature, schema, source in examples:
            with self.subTest(feature=feature):
                item = binding(feature, schema, 'Eve.bytes', source)
                with (patch('wlre.services.world.catalog_source_extractor.extract_textasset',
                            return_value=b'official-Eve') as extract,
                      patch('wlre.services.world.catalog_source_extractor.derive_eve_index',
                            return_value=b'{"schema_version":1}') as derive):
                    self.assertEqual(extract_catalog_source(item, ()), b'{"schema_version":1}')
                    extract.assert_called_once_with(item, ())
                    derive.assert_called_once_with(b'official-Eve', source)

    def test_table_textassets_pass_binary_exactly(self):
        for feature, schema, asset in (
            ('crafting', 'smith-new-33-v1', 'SmithData_C.bytes'),
            ('scenes', 'stage-new-76-v1', 'ScenesData_C.bytes'),
        ):
            item = binding(feature, schema, asset, asset[:-6])
            with patch('wlre.services.world.catalog_source_extractor.extract_textasset',
                       return_value=b'\x00\xff') as extract:
                self.assertEqual(extract_catalog_source(item, ()), b'\x00\xff')
                extract.assert_called_once_with(item, ())

    def test_no_fallback_for_mismatched_source_name_or_asset_path(self):
        for item in (
            binding('npc', 'eve-npc-json-v1', 'NpcData.bytes', 'EventData.NewNpc'),
            binding('shops', 'eve-interact-json-v1', 'Eve.bytes', 'Other'),
            binding('crafting', 'smith-new-33-v1', 'Eve.bytes', 'Eve'),
        ):
            with patch('wlre.services.world.catalog_source_extractor.extract_textasset',
                       return_value=b'raw'):
                with self.assertRaises(UnityTextAssetError):
                    extract_catalog_source(item, ())


if __name__ == '__main__':
    unittest.main()
