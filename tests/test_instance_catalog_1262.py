from contextlib import closing
"""Current catalog integrity, cold startup, atomic repair and selection tests."""
import struct
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from copy import deepcopy
from wlre.network.wire import Writer, ProtocolError
from wlre.services.world.instance_runtime import build_catalog
from wlre.services.instance_browser import official_catalog, entries_for, selected_entry, selection_fields
from wlre.storage.normalized_resources import load_parsed
from test_itemdata_v1 import sample


def payloads():
    def dungeon(variant, scene, kind=1, npc=0):
        w=Writer().u16(7).u8(kind).u8(variant).u16(scene).u32(10)
        w.u8(1).u8(0).u8(0).u16(1).u16(2).u16(npc).u8(0)
        w.u8(10).u32(3874).u32(5)
        for _ in range(15): w.u8(0).u32(0).u32(0)
        return w.u8(1).u8(0).u8(0).u8(0).build()
    stages=[]
    for scene in (500,501,502):
        stage=bytearray(76)
        struct.pack_into('<HIH',stage,2,0,10,123)
        struct.pack_into('<H',stage,0,scene)
        stage[21]=4;stage[23]=2;stage[24]=10
        stages.append(stage)
    def text(key,name):
        raw=name.encode('utf-16-le');return struct.pack('<IH',key,len(raw))+raw
    e=Writer().u8(1).u32(20).u16(1).u16(2).u8(3).u16(0).u16(0).u16(0)
    for _ in range(4):e.u16(0)
    e.u8(0).u32(0).u32(0)
    return {'DungeonData_C':struct.pack('<i',3)+dungeon(1,500)+dungeon(2,501)+dungeon(3,502,2,1),
            'CooperateEventData_C':struct.pack('<i',1)+e.build(),
            'ScenesData_C':struct.pack('<i',3)+b''.join(stages),
            'TextData_C':struct.pack('<i',2)+text(10,'測試副本')+text(20,'測試活動'),
            'ItemData_C':struct.pack('<i',1)+sample(iid=3874)}


class CurrentInstanceCatalog(unittest.TestCase):
    def build(self, raw=None):
        return build_catalog(raw or payloads(),'a'*64,'1286_2026_10_29_13_42_37_94')

    def test_composite_identity_rewards_and_unknown_variant(self):
        catalog=self.build();rows=catalog['records']
        self.assertEqual([(r['id'],r['variant']) for r in rows],[(7,1),(7,2),(7,3)])
        self.assertEqual(rows[0]['awards'],[[1,10,3874,5]])
        self.assertIsNone(rows[0]['is_open'])
        self.assertFalse(rows[2]['creation_supported'])
        self.assertEqual(rows[2]['name'],'測試活動')
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=SimpleNamespace(instances=catalog)):
            command=selection_fields(rows[0]);self.assertEqual(selected_entry('main',command)['variant'],1)
            command['catalog_key']='old'
            with self.assertRaises(ProtocolError):selected_entry('main',command)
            with self.assertRaises(ProtocolError):selected_entry('main',{'catalog_id':7})
            copied=official_catalog();copied['records'].clear()
            self.assertEqual(len(entries_for('main')),2)

    def test_cold_start_ignores_legacy_data(self):
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=SimpleNamespace(instances=None)), patch(
                'wlre.storage.bundled_database.load_legacy_resource',side_effect=AssertionError('no fallback')):
            self.assertEqual(entries_for('main'),())
            with self.assertRaises(ProtocolError):official_catalog()

    def test_duplicate_composite_or_event_id_rejected(self):
        raw=payloads();raw['DungeonData_C']=struct.pack('<i',2)+raw['DungeonData_C'][4:172]*2
        with self.assertRaises(ValueError):self.build(raw)
        raw=payloads();raw['CooperateEventData_C']=struct.pack('<i',2)+raw['CooperateEventData_C'][4:]*2
        with self.assertRaisesRegex(ValueError,'重複'):self.build(raw)

    def test_missing_name_scene_item_and_truncated_binary_rejected(self):
        for table in payloads():
            raw=payloads();raw[table]=raw[table][:-1]
            with self.subTest(table=table),self.assertRaises(ValueError):self.build(raw)
        raw=payloads();d=bytearray(raw['DungeonData_C']);struct.pack_into('<H',d,8,9999);raw['DungeonData_C']=bytes(d)
        with self.assertRaisesRegex(ValueError,'場景'):self.build(raw)
        raw=payloads();raw['TextData_C']=struct.pack('<i',0)
        with self.assertRaises(ValueError):self.build(raw)
        raw=payloads();raw['ItemData_C']=struct.pack('<i',0)
        with self.assertRaises(ValueError):self.build(raw)

    def test_database_hit_repair_and_failed_new_version_keep_old(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalog.sqlite3';raw=payloads()
            def load(key='a'*64, source=None, parser=None):
                source=raw if source is None else source
                return load_parsed(path,key,'instances','instances-v1',source,
                    parser or (lambda:build_catalog(source,key,'1286_2026_10_29_13_42_37_94')))
            original=load()
            self.assertEqual(load(parser=Mock(side_effect=AssertionError('database hit'))),original)
            with closing(sqlite3.connect(path)) as db, db:db.execute('UPDATE normalized_snapshots SET data=?',(b'broken',))
            self.assertEqual(load(),original)
            bad={**raw,'DungeonData_C':b'unknown layout'}
            with self.assertRaises(ValueError):load('b'*64,bad)
            self.assertEqual(load(),original)
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute("SELECT count(*) FROM normalized_history WHERE status='repaired_derived'").fetchone()[0],1)

    def test_packet_builder_refuses_ambiguous_id_requires_variant(self):
        from wlre.network.instance_actions import create_coop_room
        rows=[dict(id=5,variant=v,npc_id=v,min_members=2,max_members=4,creation_supported=True,catalog_key='new') for v in (1,2)]
        with patch('wlre.network.instance_actions.entries_for',return_value=rows):
            with self.assertRaises(ProtocolError):create_coop_room(5,2,public=True)
            with self.assertRaises(ProtocolError):create_coop_room(5,2,public=True,variant=2,catalog_key='old')
            self.assertEqual(create_coop_room(5,2,public=True,variant=2).payload[1:3],bytes((2,2)))
