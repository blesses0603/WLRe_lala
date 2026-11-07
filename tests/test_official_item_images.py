from contextlib import closing
import sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
from wlre.services.world.item_image_database import import_images,ItemImageCatalog,image_paths,PREFIX,current_catalog

class ItemImageDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'items.sqlite3'
        self.paths=(PREFIX+'s1000.png',PREFIX+'s4321.png')
        self.decode=Mock(side_effect=lambda:iter((p,Image.new('RGBA',(8,8),'red')) for p in self.paths))
    def load(self,key='a',decode=None,verify=None):
        return import_images(self.path,key,{'mapping':{79:4321,80:9999}},self.paths,decode or self.decode,verify_sources=verify)
    def test_complete_mapping_fallback_and_cold_start(self):
        images=self.load();catalog=ItemImageCatalog(images,{79:4321,80:9999})
        self.assertEqual(catalog.icon(79),4321)
        for item in [80,81,None]:self.assertEqual(catalog.icon(item),1000)
        self.assertEqual(catalog.png(80),images.png(1000))
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=None):self.assertIsNone(current_catalog())
    def test_cache_repair_and_failed_update_preserve_previous(self):
        images=self.load();old=images.png(4321);self.load();self.assertEqual(self.decode.call_count,1)
        with self.assertRaises(ValueError):self.load('b',decode=lambda:iter([]))
        with self.assertRaises(ValueError):self.load('b',verify=Mock(side_effect=ValueError('source changed')))
        self.assertEqual(images.png(4321),old)
        with closing(sqlite3.connect(self.path)) as db, db:db.execute('UPDATE map_images SET png=? WHERE model=4321',(b'broken',))
        with self.assertRaises(ValueError):images.png(4321)
        self.assertEqual(self.load().png(4321),old)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT catalog_key FROM image_versions').fetchall(),[('a',)])
            self.assertEqual(db.execute('SELECT png FROM image_history WHERE model=4321').fetchone()[0],b'broken')
    def test_duplicate_wrong_size_and_unreviewed_path_rejected(self):
        for rows in [[(self.paths[0],Image.new('RGBA',(8,8)))]*2,[(self.paths[0],Image.new('RGBA',(513,8)))]]:
            with self.assertRaises(ValueError):self.load(decode=lambda:iter(rows))
        for paths in [[],self.paths*2,[PREFIX+'unknown.png']]:
            with self.assertRaises(ValueError):image_paths(SimpleNamespace(index={'assets':[{'path':p} for p in paths]}))
    def test_schema_and_immutable_source_fail_closed(self):
        self.load()
        with self.assertRaises(ValueError):import_images(self.path,'a',{'mapping':'changed'},self.paths,self.decode)
        with closing(sqlite3.connect(self.path)) as db, db:db.execute('UPDATE image_schema SET version=2')
        with self.assertRaises(ValueError):self.load()
        with closing(sqlite3.connect(self.path)) as db, db:self.assertEqual(db.execute('SELECT version FROM image_schema').fetchone()[0],2)
