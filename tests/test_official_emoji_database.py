import sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from types import SimpleNamespace
from emoji_fixtures import RAW,PIN,sprites,catalog
from wlre.services.world.emoji_database import parse_entries,import_catalog,png_bytes,current_entries,current_png

class EmojiDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'emoji.sqlite3'
        self.pin=patch('wlre.services.world.emoji_database.KNOWN_SHA256',PIN);self.pin.start();self.addCleanup(self.pin.stop)
    def load(self,key='a'*64,raw=RAW,decode=None):
        return import_catalog(self.db,key,{'EmojiData_C':raw},decode or (lambda:iter(sprites())))
    def test_mapping_and_cache_hit_are_from_database(self):
        c=self.load();self.assertEqual(c['entries']['2']['sprite'],'Emoji_002');self.assertFalse(c['entries']['2']['show_in_list'])
        decode=Mock(side_effect=AssertionError('decode again'))
        self.assertEqual(self.load(decode=decode),c);decode.assert_not_called();self.assertTrue(png_bytes(c,'1'))
    def test_unknown_source_retained_without_overwriting_old_version(self):
        old=self.load()
        with self.assertRaisesRegex(ValueError,'未知'):
            self.load('b'*64,RAW+b'unknown')
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('select count(*) from normalized_snapshots').fetchone()[0],1)
            self.assertEqual(db.execute("select count(*) from normalized_history where status='parse_failed'").fetchone()[0],1)
        self.assertEqual(self.load(),old)
    def test_missing_duplicate_and_oversized_images_fail_atomically(self):
        from PIL import Image
        self.load()
        for rows in (sprites()[:1],sprites()+sprites()[:1],[('Emoji_001_1',Image.new('RGBA',(513,1))) ]):
            with self.assertRaises(ValueError):self.load('b'*64,decode=lambda:iter(rows))
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('select count(*) from normalized_snapshots').fetchone()[0],1)
    def test_corrupt_derived_snapshot_repaired_and_archived(self):
        old=self.load()
        with sqlite3.connect(self.db) as db:db.execute("update normalized_snapshots set data=?",(b'broken',))
        self.assertEqual(self.load(),old)
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute("select count(*) from normalized_history where status='repaired_derived'").fetchone()[0],1)
    def test_source_change_during_import_prevents_publication(self):
        with self.assertRaises(ValueError):
            import_catalog(self.db,'a'*64,{'EmojiData_C':RAW},lambda:iter(sprites()),Mock(side_effect=ValueError('changed')))
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('select count(*) from normalized_snapshots').fetchone()[0],0)
    def test_immutable_identity_and_unknown_schema_rejected(self):
        self.load()
        with self.assertRaises(ValueError):self.load(raw=RAW+b'x')
        with sqlite3.connect(self.db) as db:db.execute('update normalized_schema set version=999')
        with self.assertRaises(ValueError):self.load()
    def test_cold_start_invalidation_and_copy_isolation(self):
        runtime=SimpleNamespace(emoji_catalog=None)
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=runtime):
            self.assertEqual(current_entries(),{});self.assertIsNone(current_png('1'))
            runtime.emoji_catalog=self.load();copy=current_entries();copy['1']['sprite']='bad'
            self.assertEqual(current_entries()['1']['sprite'],'Emoji_001')
            self.assertTrue(current_png('1'))
            runtime.emoji_catalog=None;self.assertIsNone(current_png('1'))
    def test_corrupt_png_is_rejected(self):
        c=self.load();c['images']['1']['png']='!!!!'
        with self.assertRaises(ValueError):png_bytes(c,'1')
    def test_emoji_download_budget_rejected_before_network(self):
        from wlre.services.world.dynamic_bundle_runtime import prepare_dynamic_runtime,DynamicRuntimeUnavailable
        observe=Mock(side_effect=AssertionError('network'))
        for kwargs in ({'max_emoji_download_bytes':32*1024*1024+1},{'max_emoji_downloads':9},{'max_emoji_downloads':True}):
            with self.assertRaises(DynamicRuntimeUnavailable):prepare_dynamic_runtime(observe=observe,**kwargs)
        observe.assert_not_called()
