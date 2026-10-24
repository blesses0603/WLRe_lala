"""Offline synthetic tests for LuaScriptPathList parser and private cache."""

from pathlib import Path
import tempfile
import unittest

from wlre.services.official_lua_index import (
    LuaIndexError, cache_path, compare_lists, list_url, load_cache,
    parse_list, save_cache,
)


class OfficialLuaIndexTests(unittest.TestCase):
    def test_real_observed_format(self):
        body = (b'Lua/event.lua|F380E6CD47545F6B811B6652057DB741\r\n'
                b'Lua/list.lua|A47E312676C8B9435CD00092F610B91E\r\n')
        got = parse_list(body)
        self.assertEqual(len(got), 2)
        self.assertEqual(got['Lua/event.lua'], 'f380e6cd47545f6b811b6652057db741')
        self.assertEqual(list_url('1.3.21'),
                         'https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/'
                         'LuaScripts/LuaScriptPathList.txt')

    def test_hash_difference(self):
        old = {'Lua/event.lua': 'a'*32, 'Lua/removed.lua': 'b'*32}
        new = {'Lua/event.lua': 'c'*32, 'Lua/new.lua': 'd'*32}
        self.assertEqual(compare_lists(new, old),
                         {'first_observation': False, 'added': 1,
                          'modified': 1, 'removed': 1, 'unchanged': 0})

    def test_reject_path_traversal_duplicate_invalid_digest(self):
        for body in (b'Lua/../bad.lua|' + b'a'*32,
                     b'Lua/bad\\one.lua|' + b'a'*32,
                     b'Other/test.lua|' + b'a'*32,
                     b'Lua/foo.lua|INVALID',
                     (b'Lua/test.lua|' + b'a'*32 + b'\n') * 2):
            with self.subTest(body=body), self.assertRaises(LuaIndexError):
                parse_list(body)

    def test_invalid_data_ver_rejected(self):
        for item in ('../../foo', '1.3.21/..', 'http://evil', '1.3.21?q=x'):
            with self.subTest(item=item), self.assertRaises(LuaIndexError):
                list_url(item)

    def test_atomic_cache_roundtrip_and_bounded_read(self):
        entries = {'Lua/list.lua': 'a'*32, 'Lua/Common/Atlas.lua': 'b'*32}
        with tempfile.TemporaryDirectory() as tmp:
            target = cache_path('1.3.21', tmp)
            self.assertIsNone(load_cache('1.3.21', tmp))
            self.assertEqual(save_cache('1.3.21', entries, base=tmp), target)
            self.assertEqual(load_cache('1.3.21', tmp), entries)
            target.write_bytes(b'not json')
            with self.assertRaises(LuaIndexError):
                load_cache('1.3.21', tmp)


if __name__ == '__main__':
    unittest.main()
