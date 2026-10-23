"""Real ItemData_C 1262 names, prices, restrictions and fail-closed UI."""
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from wlre.paths import RESOURCE_ROOT
from wlre.services.world.npc_item_data import (
    FILENAME, CATALOG_BYTES, CATALOG_SHA256, SOURCE_SHA256,
    RECORD_COUNT, load_items, item_catalog, sellable,
)
from wlre.services.world.npc_interact import NPCInteractIndex
from wlre.services.world.npc_shop import shop_catalog, draft_purchase
from wlre.network.wire import ProtocolError


class ItemData1262Tests(unittest.TestCase):
    def test_full_catalog_source_and_content_integrity(self):
        file=RESOURCE_ROOT/FILENAME
        raw=file.read_bytes()
        self.assertEqual(len(raw),CATALOG_BYTES)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),CATALOG_SHA256)
        obj=json.loads(gzip.decompress(raw).decode('utf-8'))
        self.assertEqual(obj['source_sha256'],SOURCE_SHA256)
        self.assertEqual(obj['version'],1262)
        self.assertEqual(len(obj['records']),RECORD_COUNT)
        data=load_items()
        self.assertEqual(len(data),11287)
        self.assertEqual(data[32297]['name'],'果粒蘋果汁')
        self.assertEqual(data[32297]['price'],750)
        self.assertEqual(data[32297]['sell_price'],8)
        self.assertEqual(data[10044]['name'],'赤鐵軍刀')
        self.assertEqual(data[10044]['price'],510)
        self.assertEqual(sum(not sellable(v) for v in data.values()),5301)
        self.assertFalse(sellable(data[10002]))
        self.assertTrue(sellable(data[10044]))

    def test_all_real_npc_shop_items_resolved(self):
        eve=NPCInteractIndex()
        source=item_catalog()
        offers=[]
        for scene,rows in eve.scenes.items():
            for index,row in rows.items():
                if row['form_kind'] not in (2,3):
                    continue
                cat=shop_catalog(scene,index,index=eve)
                self.assertTrue(cat['item_data_verified'])
                self.assertFalse(cat['verified_prices'])  # final price / live gold not verified
                for product in cat['products']:
                    official=source[product['item_id']]
                    self.assertEqual(product['name'],official['name'])
                    self.assertEqual(product['price_gold'],official['price'])
                    self.assertEqual(product['sell_price_gold'],official['sell_price'])
                    self.assertEqual(product['npc_sell_allowed'],sellable(official))
                    self.assertFalse(product['buy_enabled'])
                    offers.append(product['item_id'])
        self.assertEqual(len(offers),309)
        self.assertEqual(len(set(offers)),215)

    def test_offline_preview_never_authorizes_payment(self):
        cat=shop_catalog(10080,6)
        preview=draft_purchase(cat,1,2)
        self.assertEqual(preview['base_unit_gold'],750)
        self.assertEqual(preview['base_total_gold'],1500)
        self.assertIsNone(preview['total_gold'])
        self.assertFalse(preview['enabled'])
        with self.assertRaises(ProtocolError):
            draft_purchase(cat,1,999999999)

    def test_bad_file_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/FILENAME
            target.write_bytes(b'broken')
            with self.assertRaises(Exception):load_items(target)
        with tempfile.TemporaryDirectory() as folder:
            raw=gzip.decompress((RESOURCE_ROOT/FILENAME).read_bytes())
            obj=json.loads(raw)
            obj['records']['32297']['price']='not-a-number'
            target=Path(folder)/FILENAME
            target.write_bytes(gzip.compress(json.dumps(obj).encode('utf-8')))
            with self.assertRaises(ValueError):load_items(target)


# These historical tests verify bundled 1262 fixtures explicitly. Production
# LaLa now defaults to 1275, with no implicit source fallback.
from unittest.mock import patch as _legacy_patch
_legacy_context = None


def setUpModule():
    global _legacy_context
    _legacy_context = _legacy_patch(
        'wlre.services.world.runtime_1275.baseline_revision', return_value='1262')
    _legacy_context.start()
    from wlre.services.world.npc_item_data import item_catalog
    item_catalog.cache_clear()


def tearDownModule():
    from wlre.services.world.npc_item_data import item_catalog
    item_catalog.cache_clear()
    _legacy_context.stop()

