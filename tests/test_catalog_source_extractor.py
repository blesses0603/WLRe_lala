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


    def test_shop_verified_related_itemdata_enriches_base_price(self):
        import json
        from wlre.services.world.itemdata_v1 import ItemDataDecodeError
        primary = binding('shops', 'eve-interact-json-v1',
                          'Eve.bytes', 'EventData.NewInteract')
        item = AssetBinding(primary.asset_path, primary.contract,
                            ('Assets/ResourcesBuild/Data/ItemData_C.bytes',))
        scenes = {'schema_version': 1, 'source': 'EventData.NewInteract',
                  'record_count': 1,
                  'scenes': {'500': [{'index': 8, 'form_kind': 3,
                                     'items': [{'id': 1, 'text_id': 3874,
                                                'database_kind': 2, 'kind': 3}]}]}}
        def read_asset(source, paths):
            return b'raw-items' if source.asset_path.endswith('ItemData_C.bytes') else b'raw-eve'
        with (patch('wlre.services.world.catalog_source_extractor.extract_textasset',
                    side_effect=read_asset),
              patch('wlre.services.world.catalog_source_extractor.derive_eve_index',
                    return_value=json.dumps(scenes).encode()),
              patch('wlre.services.world.catalog_source_extractor.parse_itemdata',
                    return_value={3874: {'name': '物品', 'price': 100,
                                         'sell_price': 40, 'restrict': 0,
                                         'open_used': 0, 'need_level': 5}})):
            result = json.loads(extract_catalog_source(item, ()))
        self.assertTrue(result['itemdata_verified'])
        self.assertEqual(result['itemdata_count'], 1)
        offer = result['scenes']['500'][0]['items'][0]
        self.assertEqual(offer['item_data']['price'], 100)
        self.assertFalse(offer['buy_enabled'])

        with (patch('wlre.services.world.catalog_source_extractor.extract_textasset',
                    side_effect=read_asset),
              patch('wlre.services.world.catalog_source_extractor.derive_eve_index',
                    return_value=json.dumps(scenes).encode()),
              patch('wlre.services.world.catalog_source_extractor.parse_itemdata',
                    return_value={})):
            with self.assertRaises(ItemDataDecodeError):
                extract_catalog_source(item, ())

    def test_shop_unreviewed_related_path_is_refused(self):
        primary = binding('shops', 'eve-interact-json-v1',
                          'Eve.bytes', 'EventData.NewInteract')
        item = AssetBinding(primary.asset_path, primary.contract,
                            ('Assets/Custom/Other.bytes',))
        with patch('wlre.services.world.catalog_source_extractor.extract_textasset',
                   return_value=b'raw'):
            with patch('wlre.services.world.catalog_source_extractor.derive_eve_index',
                       return_value=b'{"schema_version":1}'):
                with self.assertRaisesRegex(UnityTextAssetError, 'exact reviewed'):
                    extract_catalog_source(item, ())



if __name__ == '__main__':
    unittest.main()
