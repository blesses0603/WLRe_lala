"""Pinned battle-quote source: no guessing when the official bytes change."""
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from wlre.services.world import npc_battle_catalog as catalog
from wlre.services.world.npc_localization import load_battle_talk, battle_lines
from wlre.storage.normalized_resources import load_parsed


def fixture():
    raw=struct.pack('<I',2)+struct.pack('<HIBHB',1,100,4,1,5)+struct.pack('<HIBHB',1,101,3,50,5)
    def text(key,value):
        data=value.encode('utf-16-le');return struct.pack('<IH',key,len(data))+data
    return raw,struct.pack('<I',2)+text(100,'測試甲')+text(101,'測試乙')


class BattleTalkMigration(unittest.TestCase):
    def test_unknown_source_is_rejected_without_fingerprint_override(self):
        raw,_=fixture()
        with self.assertRaisesRegex(ValueError,'指紋'):catalog.parse_known_battle_talk(raw)

    def test_synthetic_layout_same_text_namespace_and_copy_isolation(self):
        raw,text=fixture()
        with patch.object(catalog,'KNOWN_SHA256',hashlib.sha256(raw).hexdigest()):
            groups=catalog.build_catalog(raw,text)
        self.assertEqual(groups[1][1],dict(text_id=101,kind=3,parameter=50,duration=5))
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=SimpleNamespace(battle_talk=groups)):
            copied=load_battle_talk();copied[1][0]['kind']=99
            self.assertEqual(load_battle_talk()[1][0]['kind'],4)
            self.assertEqual(battle_lines(1,load_battle_talk(),{100:'甲',101:'乙'}),[(100,'甲'),(101,'乙')])

    def test_cold_start_does_not_use_old_bundled_database(self):
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=SimpleNamespace(battle_talk=None)), patch(
                'wlre.storage.bundled_database.load_legacy_resource',side_effect=AssertionError('no fallback')):
            with self.assertRaises(ValueError):load_battle_talk()

    def test_bad_length_and_missing_current_text_refuse(self):
        raw,text=fixture()
        for bad in (raw[:-1],struct.pack('<I',3)+raw[4:]):
            with patch.object(catalog,'KNOWN_SHA256',hashlib.sha256(bad).hexdigest()):
                with self.assertRaises(ValueError):catalog.parse_known_battle_talk(bad)
        with patch.object(catalog,'KNOWN_SHA256',hashlib.sha256(raw).hexdigest()):
            with self.assertRaises(ValueError):catalog.build_catalog(raw,struct.pack('<I',0))

    def test_new_unreviewed_source_preserves_old_snapshot(self):
        raw,text=fixture()
        with tempfile.TemporaryDirectory() as folder, patch.object(catalog,'KNOWN_SHA256',hashlib.sha256(raw).hexdigest()):
            path=Path(folder)/'db.sqlite3'
            def load(key,source):return load_parsed(path,key,'npc-battle-talk','npc-battle-talk-known-v1',
                {'NpcTalkData_C':source,'TextData_C':text},lambda:catalog.build_catalog(source,text))
            old=load('a'*64,raw)
            with self.assertRaises(ValueError):load('b'*64,raw+b'x')
            self.assertEqual(load('a'*64,raw),old)
