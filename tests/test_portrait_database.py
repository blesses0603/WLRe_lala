import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from wlre.services.world.portrait_database import import_portraits, _decode


class PortraitDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'portraits.sqlite3'
        self.inputs = {'expected': [('player', '1')], 'bundles': {'test': 'verified'}}
        self.npcs = {}
    def tearDown(self): self.tmp.cleanup()
    def decode(self):
        yield 'player', '1', Image.new('RGBA', (2, 2), 'red'), Image.new('RGBA', (2, 2), 'white'), {'reviewed': True}
    def build(self, key='a', inputs=None, decode=None, verify=lambda: None):
        return import_portraits(self.path,key,inputs or self.inputs,decode or self.decode,self.npcs,verify_sources=verify)
    def test_import_reuse_and_integrity(self):
        first = self.build()
        second = self.build(decode=lambda: self.fail('decoded valid cache'))
        self.assertEqual(first.available,second.available)
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT base,base_sha,base_pixels FROM portraits').fetchone()
        self.assertEqual(_decode(*row).getpixel((0,0)), (255,0,0,255))
    def test_missing_row_repairs(self):
        self.build()
        with sqlite3.connect(self.path) as db:db.execute('DELETE FROM portraits')
        self.assertEqual(self.build().available,frozenset({('player','1')}))
    def test_same_version_changed_source_refused(self):
        self.build()
        with self.assertRaises(ValueError):self.build(inputs={**self.inputs,'bundles':{'different':'source'}})
    def test_partial_or_source_failure_preserves_old_version(self):
        self.build()
        with self.assertRaises(ValueError):self.build(key='b',decode=lambda: iter(()))
        def changed():raise ValueError('replaced source')
        with self.assertRaises(ValueError):self.build(key='b',verify=changed)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT key FROM portrait_versions').fetchall(),[('a',)])
            self.assertEqual(db.execute('SELECT key FROM portraits').fetchall(),[('a',)])
    def test_corrupt_pixels_rebuilt(self):
        self.build()
        with sqlite3.connect(self.path) as db:db.execute("UPDATE portraits SET base_pixels='bad'")
        self.build()
        with sqlite3.connect(self.path) as db:
            row=db.execute('SELECT base,base_sha,base_pixels FROM portraits').fetchone()
        _decode(*row).close()
    def test_null_material_metadata_repairs(self):
        self.build()
        with sqlite3.connect(self.path) as db:db.execute('UPDATE portraits SET metadata=NULL')
        self.build()
        with sqlite3.connect(self.path) as db:
            self.assertIsInstance(db.execute('SELECT metadata FROM portraits').fetchone()[0],str)

    def test_unknown_schema_never_overwrites(self):
        self.build()
        with sqlite3.connect(self.path) as db:db.execute('UPDATE portrait_schema SET version=99')
        with self.assertRaises(ValueError):self.build()
    def test_unsupported_index_and_oversize(self):
        with self.assertRaises(ValueError):self.build(inputs={'expected':[]})
        def too_big():yield 'player','1',Image.new('RGBA',(257,1)),Image.new('RGBA',(2,2)),{}
        with self.assertRaises(ValueError):self.build(decode=too_big)

if __name__ == '__main__': unittest.main()
