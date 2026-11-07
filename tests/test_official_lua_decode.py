import hashlib,importlib.util,struct,unittest
from unittest.mock import patch
from tools.official_lua_decode import decode_reviewed,_cbc_decode,_parameters,MAX_LUA_BYTES

class LuaSourceBounds(unittest.TestCase):
    def test_unreviewed_source_and_metadata_fail_closed(self):
        with self.assertRaises(ValueError):decode_reviewed('unknown.lua',b'x',b'')
        with self.assertRaises(ValueError):_parameters(b'')

@unittest.skipUnless(importlib.util.find_spec('Crypto'),'optional pycryptodome research dependency')
class LuaCodecTests(unittest.TestCase):
    def test_known_synthetic_vector_and_cipher_roundtrip(self):
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        key=bytes(range(16));iv=bytes(reversed(range(16)));plain=b'function example() return 7 end\n'
        cipher=AES.new(key,AES.MODE_CBC,iv).encrypt(pad(plain,16))
        known={'synthetic.lua':(hashlib.sha256(cipher).hexdigest(),hashlib.sha256(plain).hexdigest())}
        with patch('tools.official_lua_decode.KNOWN_FILES',known),patch('tools.official_lua_decode._parameters',return_value=(key,iv)):
            self.assertEqual(decode_reviewed('synthetic.lua',cipher,b''),plain)
            with self.assertRaises(ValueError):decode_reviewed('synthetic.lua',cipher[:-1]+bytes([cipher[-1]^1]),b'')
        for raw in (b'',b'x',b'0'*(MAX_LUA_BYTES+16)):
            with self.assertRaises(ValueError):_cbc_decode(raw,key,iv)
    def test_valid_padding_does_not_replace_cleartext_fingerprint_check(self):
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        key=b'1'*16;iv=b'2'*16;cipher=AES.new(key,AES.MODE_CBC,iv).encrypt(pad(b'wrong',16))
        with patch('tools.official_lua_decode.KNOWN_FILES',{'synthetic.lua':(hashlib.sha256(cipher).hexdigest(),'0'*64)}),patch('tools.official_lua_decode._parameters',return_value=(key,iv)):
            with self.assertRaisesRegex(ValueError,'independent'):decode_reviewed('synthetic.lua',cipher,b'')
