"""No packaged 1262 item archive; active item metadata is release-verified 1275."""
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wlre.paths import RESOURCE_ROOT
from wlre.resource_manifest import REQUIRED_RESOURCES
from wlre.services.world.npc_item_data import (
    FILENAME, CATALOG_SHA256, CATALOG_BYTES, load_items, item_catalog, sellable,
)
from wlre.services.world.runtime_1275 import Runtime1275Unavailable
from wlre.services.world.npc_shop import shop_catalog, draft_purchase


class ItemDataRuntimeTests(unittest.TestCase):
    def tearDown(self):
        item_catalog.cache_clear()

    def test_1262_archive_not_shipped(self):
        self.assertNotIn(FILENAME, REQUIRED_RESOURCES)
        self.assertFalse((RESOURCE_ROOT / FILENAME).exists())

    def test_unavailable_current_runtime_does_not_fallback(self):
        item_catalog.cache_clear()
        with patch('wlre.services.world.runtime_1275.active_runtime',
                   side_effect=Runtime1275Unavailable('1275 尚未核實')):
            with self.assertRaises(Runtime1275Unavailable):
                item_catalog()

    def test_verified_current_runtime_items_are_used(self):
        item_catalog.cache_clear()
        source={32297: {'name':'1275 測試品','price':901,'sell_price':6,
                        'restrict':0,'open_used':0,'need_level':0}}
        with patch('wlre.services.world.runtime_1275.active_runtime',
                   return_value=SimpleNamespace(items=source)):
            self.assertIs(item_catalog(),source)
            self.assertEqual(item_catalog()[32297]['price'],901)

    def test_npc_shop_uses_current_items_and_never_authorizes_payment(self):
        item={32297: {'name':'正式測試品','price':750,'sell_price':8,
                      'restrict':0,'open_used':0,'need_level':0}}
        # One synthetic shop fixture, without original game data in the repo.
        scene=10080
        class ShopIndex:
            def get(self, target_scene, idx):
                if (target_scene,idx)!=(scene,6):
                    return None
                return {'form_kind':3,'items': [
                    {'kind':3,'database_kind':2,'text_id':32297,'id':1},
                    {'kind':4,'database_kind':0,'text_id':0,'id':0}]}
        catalog=shop_catalog(scene,6,index=ShopIndex(),item_rows=item)
        self.assertTrue(catalog['item_data_verified'])
        self.assertFalse(catalog['verified_prices'])
        self.assertEqual(catalog['products'][0]['name'],'正式測試品')
        self.assertEqual(catalog['products'][0]['price_gold'],750)
        self.assertFalse(catalog['products'][0]['buy_enabled'])
        preview=draft_purchase(catalog,1,2)
        self.assertEqual(preview['base_total_gold'],1500)
        self.assertIsNone(preview['total_gold'])
        self.assertFalse(preview['enabled'])

    def test_historical_loader_requires_explicit_source_and_integrity(self):
        with self.assertRaises(ValueError):
            load_items()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/FILENAME
            path.write_bytes(b'invalid')
            with self.assertRaises(ValueError):
                load_items(path)
            # A syntactically valid gzip is not a release-approved index.
            path.write_bytes(gzip.compress(json.dumps(
                {'version':1262,'source':'ItemData_C','records':{}}
            ).encode('utf-8')))
            with self.assertRaises(ValueError):
                load_items(path)

    def test_restriction_bit_does_not_trigger_trade(self):
        self.assertFalse(sellable({'restrict':16}))
        self.assertTrue(sellable({'restrict':0}))
        self.assertFalse(sellable(None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
