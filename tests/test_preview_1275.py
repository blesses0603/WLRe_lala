"""Read-only 1275 bridge regression tests; official binary ZIPs are not in Git."""
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

from wlre.services.world.preview_1275 import (
    Preview1275, PreviewNPCIndex, PreviewInteractIndex,
    PreviewError, load_preview, parse_smith_1275,
)
from wlre.services.world.npc_shop import draft_purchase, shop_catalog


def smith_record(item_id=39852):
    row = bytearray(33)
    struct.pack_into('<H', row, 0, item_id)
    row[4] = 1
    struct.pack_into('<H', row, 5, 38017)
    row[7] = 1
    struct.pack_into('<HB', row, 8, 37043, 3)
    row[23] = 1
    struct.pack_into('<H', row, 24, 60)
    return bytes(row)


def interact_fixture():
    return {'scenes': {'10000': [{'index': 7, 'form_kind': 3,
             'link_number': 0,
             'items': [{'id': 1, 'text_id': 39852, 'database_kind': 2,
                        'kind': 3}]}]}}


class Preview1275Tests(unittest.TestCase):
    def test_smith_1275_recipes_have_main_catalog_shape(self):
        raw = struct.pack('<i', 1) + smith_record()
        rows = parse_smith_1275(raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[39852]['tool_id'], 38017)
        self.assertEqual(rows[39852]['materials'], [{'item_id': 37043, 'count': 3}])
        self.assertEqual(rows[39852]['seconds'], 60)

    def test_smith_1275_rejects_corruption_duplicates_and_bad_count(self):
        valid = struct.pack('<i', 1) + smith_record()
        for invalid in (valid[:-1], valid + b'x',
                        struct.pack('<i', 2) + smith_record() * 2,
                        struct.pack('<i', -1)):
            with self.subTest(size=len(invalid)), self.assertRaises(PreviewError):
                parse_smith_1275(invalid)

    def test_npc_shop_optional_1275_rows_never_enable_purchase(self):
        i = PreviewInteractIndex(interact_fixture())
        catalog = shop_catalog(10000, 7, index=i,
                               item_rows={39852: {'name': '1275 測試物品',
                                                   'price': 25, 'sell_price': 4,
                                                   'restrict': 16}})
        self.assertEqual(catalog['products'][0]['price_gold'], 25)
        self.assertEqual(catalog['products'][0]['item_id'], 39852)
        self.assertFalse(catalog['verified_prices'])
        self.assertFalse(catalog['products'][0]['buy_enabled'])
        self.assertFalse(draft_purchase(catalog, 1, 2)['enabled'])

    def test_legacy_shop_defaults_unchanged_and_bad_injection_rejected(self):
        i = PreviewInteractIndex(interact_fixture())
        self.assertIsNone(shop_catalog(10000, 7, index=i, item_rows=[]))

    def test_portals_are_never_authorized_by_scene_presence(self):
        c = Preview1275(PreviewNPCIndex({'scenes': {}}),
                        PreviewInteractIndex({'scenes': {}}),
                        {}, {}, {}, {}, frozenset({10000}))
        self.assertFalse(c.can_send_packets)
        self.assertTrue(c.portal_status(10000)['exists'])
        self.assertFalse(c.portal_status(10000)['can_send_packets'])
        self.assertFalse(c.portal_status(9999)['exists'])
        self.assertFalse(c.portal_status(9999)['can_send_packets'])

    def test_loading_rejects_unverified_archive(self):
        with patch('wlre.services.world.preview_1275.verify_archive',
                   side_effect=ValueError('bad SHA-256')):
            with self.assertRaises(ValueError):
                load_preview(Path('invalid.zip'), Path('other.zip'))

    def test_scene_and_recipe_results_are_copies(self):
        c = Preview1275(
            PreviewNPCIndex({'scenes': {'10000': [{'index': 1, 'npc_id': 10, 'event_ids': [2]}]}}),
            PreviewInteractIndex({'scenes': {}}),
            {}, {}, {}, {39852: {'item_id': 39852}}, frozenset())
        c.npc_for_scene(10000)[0]['index'] = 999
        c.recipe(39852)['item_id'] = 4
        c.npc_for_scene(10000)[0]['event_ids'].append(200)
        self.assertEqual(c.npc_for_scene(10000)[0]['event_ids'], [2])
        self.assertEqual(c.npc_for_scene(10000)[0]['index'], 1)
        self.assertEqual(c.recipe(39852)['item_id'], 39852)


if __name__ == '__main__':
    unittest.main()
