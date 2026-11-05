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


if __name__=='__main__':unittest.main()
