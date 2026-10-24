"""1275 ItemData_C complete Lua-layout decoding and safe catalog switch."""
import struct
import unittest
from types import SimpleNamespace

from wlre.services.items.catalog import CAT
from wlre.services.items.alchemy import META
from wlre.services.items.itemdata_1275 import (
    ItemData1275Error, parse_items_1275, activate_1275_items)


def fake_item(item_id=39852, width=1, height=1):
    """Construct an original-layout fixture without shipping game data."""
    def u8(x): return struct.pack('<B', x)
    def u16(x): return struct.pack('<H', x)
    def u32(x): return struct.pack('<I', x)
    def i32(x): return struct.pack('<i', x)
    def txt(s):
        raw = s.encode('utf-16-le')
        return u16(len(raw)) + raw
    return b''.join((
        txt('自訂1275道具'), u8(23), txt('類型'), u16(item_id),
        u16(0), u16(4253), u16(4253), u16(0)*4,
        u16(25)+u8(0)+i32(500),
        u16(0)+u8(0)+i32(100),
        u8(7)+u8(3)+u8(8)+u8(0),
        u32(0)*16, u8(0)+u8(1), u32(100)+u32(10)+u8(0)+u16(4),
        u32(0)+u8(0)+u32(0)+u16(15003), u16(3)+u16(4)*4,
        txt('測試說明'), u8(0)*3, u16(0), u8(width)+u8(height)+u8(0),
        u16(0), u16(0)*3, u8(0)*6, u16(0)*5, u32(0)*6,
        u16(0)*2, u8(0)*2, u8(0)*4, u16(0)+u8(0), u16(0)*5,
        u8(0), u16(0)*3,
    ))


class ItemData1275Tests(unittest.TestCase):
    def test_complete_fixture_parses_equipment_alchemy_and_icon(self):
        source = parse_items_1275(struct.pack('<i', 1) + fake_item())
        self.assertEqual(source['source_revision'], 1275)
        row = source['items']['39852']
        self.assertEqual(row['name'], '自訂1275道具')
        self.assertEqual(row['kind'], 23)
        self.assertEqual(row['fit_type'], 8)
        self.assertEqual(row['icon_id'], 4253)
        self.assertEqual(row['skill_link'], 15003)
        self.assertEqual(row['restrict'], 4)
        self.assertEqual(row['attributes'][0]['value'], 500)
        self.assertEqual(source['alchemy']['39852']['spares'], [3, 4, 4, 4, 4])

    def test_zero_size_test_items_have_conservative_alchemy_footprint(self):
        source = parse_items_1275(struct.pack('<i', 1)
                                  + fake_item(width=0, height=0))
        self.assertEqual(source['items']['39852']['width'], 0)
        self.assertEqual(source['alchemy']['39852']['width'], 1)
        self.assertEqual(source['alchemy']['39852']['height'], 1)

    def test_truncation_extra_bytes_duplicate_ids_and_invalid_source_fail(self):
        record = fake_item()
        for value in (b'', struct.pack('<i', 1) + record[:-1],
                      struct.pack('<i', 1) + record + b'x',
                      struct.pack('<i', 2) + record + record,
                      struct.pack('<i', 0)):
            with self.subTest(length=len(value)), self.assertRaises(
                    ItemData1275Error):
                parse_items_1275(value)
        with self.assertRaises(ItemData1275Error):
            parse_items_1275(None)

    def test_shared_refs_updated_only_after_full_validation(self):
        source = parse_items_1275(struct.pack('<i', 1) + fake_item())
        original_items, original_meta = dict(CAT['items']), dict(META)
        item_ref, meta_ref = CAT['items'], META
        try:
            self.assertEqual(activate_1275_items(SimpleNamespace(
                revision=1275, item_catalog=source)), 1)
            self.assertIs(CAT['items'], item_ref)
            self.assertIs(META, meta_ref)
            self.assertEqual(CAT['items']['39852']['name'], '自訂1275道具')
            self.assertEqual(META['39852']['spares'][0], 3)
        finally:
            item_ref.clear(); item_ref.update(original_items)
            meta_ref.clear(); meta_ref.update(original_meta)

    def test_unverified_or_incomplete_source_cannot_mutate_shared_refs(self):
        source = parse_items_1275(struct.pack('<i', 1) + fake_item())
        before_items, before_meta = dict(CAT['items']), dict(META)
        for invalid in (
            SimpleNamespace(revision=1262, item_catalog=source),
            SimpleNamespace(revision=1275, item_catalog={}),
            SimpleNamespace(revision=1275, item_catalog={
                **source, 'alchemy': {'9999': source['alchemy']['39852']}}),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(
                    ItemData1275Error):
                activate_1275_items(invalid)
        self.assertEqual(CAT['items'], before_items)
        self.assertEqual(META, before_meta)


if __name__ == '__main__':
    unittest.main()
