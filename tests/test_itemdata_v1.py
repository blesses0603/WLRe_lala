import unittest
import struct
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


if __name__=='__main__':unittest.main()
