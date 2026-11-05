import unittest
import struct
import hashlib
import os
from pathlib import Path
from unittest.mock import patch
from wlre.services.world.itemdata_v1 import parse_itemdata, ItemDataDecodeError


def sample(iid=39852, price=125, name='蘋果'):
    enc=lambda s: s.encode('utf-16-le')
    namebytes=enc(name);kindbytes=enc('雜物')
    out=struct.pack('<H',len(namebytes))+namebytes+b'\x01'+struct.pack('<H',len(kindbytes))+kindbytes
    out+=struct.pack('<H',iid)
    out+=bytes(2+2+2+4*2+2*(2+1+4)+4+4*4*4)
    out+=struct.pack('<BBIIBH',0,10,price,55,2,16)
    out+=bytes(4+1+4+2+5*2)
    out+=struct.pack('<H',0)
    out+=bytes(3+2+1+1)
    out+=bytes(1+2+2+2+2+1+1+1)
    out+=bytes(1+1+1+2+2+2+2+2)
    out+=bytes(6*4)
    out+=bytes(2+2+1+1+1+1+1+1+2+1)
    out+=bytes(5*2)
    out+=bytes(1+2+2+2)
    return out


class ItemDataTests(unittest.TestCase):
    def test_itemdata_price_and_sale_restrictions(self):
        result=parse_itemdata(struct.pack('<I',1)+sample())
        self.assertEqual(result[39852]['name'],'蘋果')
        self.assertEqual(result[39852]['price'],125)
        self.assertEqual(result[39852]['sell_price'],55)
        self.assertEqual(result[39852]['restrict'],16)
        self.assertEqual(result[39852]['open_used'],0)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ItemDataDecodeError):
            parse_itemdata(struct.pack('<I',2)+sample()+sample())

    def test_truncated_and_extra_payload_rejected(self):
        blob=struct.pack('<I',1)+sample()
        for raw in (blob[:-1],blob+b'\x00'):
            with self.assertRaises(ItemDataDecodeError):
                parse_itemdata(raw)

    def test_invalid_unicode_rejected(self):
        blob=bytearray(struct.pack('<I',1)+sample())
        blob[4]=3
        with self.assertRaises(ItemDataDecodeError):
            parse_itemdata(bytes(blob))

    def test_1296_preserves_unknown_tail_and_consumes_whole_file(self):
        version = '1296_2026_11_04_13_34_19_13'
        raw = struct.pack('<I', 2) + sample(10) + b'\x00\xff' + sample(11) + b'\x12\x34'
        with patch('wlre.services.world.itemdata_v1.ITEMDATA_1296_SHA256', hashlib.sha256(raw).hexdigest()):
            rows = parse_itemdata(raw, package_version=version)
            self.assertEqual(rows[10]['unknown_tail_1296_hex'], '00ff')
            self.assertEqual(rows[11]['unknown_tail_1296_hex'], '1234')
            self.assertEqual(parse_itemdata(raw), rows)
            with self.assertRaises(ItemDataDecodeError):
                parse_itemdata(raw, package_version='1297_2026_11_05_00_00_00_00')
            with self.assertRaises(ItemDataDecodeError):
                parse_itemdata(raw, package_version='1286_2026_10_29_13_42_37_94')
            with self.assertRaises(ItemDataDecodeError):
                parse_itemdata(raw[:-1], package_version=version)
        for malformed in (raw[:-1], raw + b'\x00'):
            with patch('wlre.services.world.itemdata_v1.ITEMDATA_1296_SHA256', hashlib.sha256(malformed).hexdigest()):
                with self.assertRaises(ItemDataDecodeError):
                    parse_itemdata(malformed, package_version=version)

    @unittest.skipUnless(os.environ.get('WLRE_ITEMDATA_1296_BUNDLE'), 'private official bundle not supplied')
    def test_private_1296_bundle(self):
        import UnityPy
        from wlre.services.world.unity_textasset import _payload
        bundle = Path(os.environ['WLRE_ITEMDATA_1296_BUNDLE'])
        env = UnityPy.load(str(bundle))
        raw = next(_payload(obj, path) for path, obj in env.container.items()
                   if path.lower().endswith('/itemdata_c.bytes'))
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '5195d5ee8ae201dea55439274914930551176c3fcf50d735e03b09c5d04acbb4')
        starts = []
        from wlre.services.world import itemdata_v1

        class RecordingReader(itemdata_v1.Reader):
            def utf16(self, *, allow_empty=False):
                if not allow_empty:
                    starts.append(self.pos)
                return super().utf16(allow_empty=allow_empty)

        with patch.object(itemdata_v1, 'Reader', RecordingReader):
            rows = parse_itemdata(raw, package_version='1296_2026_11_04_13_34_19_13')
        self.assertEqual(starts[0], 4)
        offsets = [boundary - 2 for boundary in starts[1:] + [len(raw)]]
        self.assertEqual(len(rows), 11366)
        self.assertEqual(len(offsets), len(rows))
        self.assertTrue(all(bytes.fromhex(row['unknown_tail_1296_hex']) == raw[offset:offset+2]
                            for row, offset in zip(rows.values(), offsets)))



    def test_reviewed_1296_extended_fields_and_legacy_isolation(self):
        # Independent synthetic wire values for official ItemData:New fields.
        blob=bytearray(sample(321,name='A'))
        # u16 name bytes + UTF16 A + kind + u16 kind bytes + kind + item ID.
        start=2+2+1+2+len('雜物'.encode('utf-16-le'))+2
        struct.pack_into('<HHH',blob,start,7,4321,5432)
        struct.pack_into('<HBiHBi',blob,start+6+8,25,2,-17,26,3,450)
        material_at=start+6+8+14
        struct.pack_into('<BBBB',blob,material_at,3,44,5,67)
        spares_at=material_at+4+64+13+11
        struct.pack_into('<5H',blob,spares_at,8,9,10,11,12)
        size_at=spares_at+10+2
        struct.pack_into('<3B',blob,size_at,2,3,4)
        struct.pack_into('<2B',blob,size_at+5,6,7)
        time_at=size_at+7+12+3
        struct.pack_into('<3H',blob,time_at,13,14,15)
        blob[time_at+6+4+24+5]=1
        legacy=struct.pack('<I',1)+blob
        self.assertNotIn('icon_id',parse_itemdata(legacy)[321])
        raw=legacy+struct.pack('<H',6789)
        with patch('wlre.services.world.itemdata_v1.ITEMDATA_1296_SHA256',hashlib.sha256(raw).hexdigest()):
            row=parse_itemdata(raw,package_version='1296_2026_11_04_13_34_19_13')[321]
        self.assertEqual(row['attributes'],[{'kind':25,'effect':2,'value':-17},{'kind':26,'effect':3,'value':450}])
        self.assertEqual(row['flags2'],1);self.assertTrue(row['is_pvp_time_over']);self.assertFalse(row['stackable'])
        expected={'kind':1,'order':7,'icon_id':4321,'shop_icon_id':5432,
                  'material':3,'level':44,'fit_type':5,'special':67,
                  'spares':[8,9,10,11,12],'size_l':2,'size_w':3,'size_h':4,
                  'item_w':6,'item_h':7,'available_time':13,'limited_time':14,
                  'use_count':15,'style_bank_set_sort_id':6789}
        self.assertEqual({key:row[key] for key in expected},expected)

if __name__=='__main__':unittest.main()
