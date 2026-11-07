from contextlib import closing
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
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
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute('SELECT base,base_sha,base_pixels FROM portraits').fetchone()
        with _decode(*row) as image:
            self.assertEqual(image.getpixel((0,0)), (255,0,0,255))
    def test_missing_row_repairs(self):
        self.build()
        with closing(sqlite3.connect(self.path)) as db, db:db.execute('DELETE FROM portraits')
        self.assertEqual(self.build().available,frozenset({('player','1')}))
    def test_same_version_changed_source_refused(self):
        self.build()
        with self.assertRaises(ValueError):self.build(inputs={**self.inputs,'bundles':{'different':'source'}})
    def test_partial_or_source_failure_preserves_old_version(self):
        self.build()
        with self.assertRaises(ValueError):self.build(key='b',decode=lambda: iter(()))
        def changed():raise ValueError('replaced source')
        with self.assertRaises(ValueError):self.build(key='b',verify=changed)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT key FROM portrait_versions').fetchall(),[('a',)])
            self.assertEqual(db.execute('SELECT key FROM portraits').fetchall(),[('a',)])
    def test_corrupt_pixels_rebuilt(self):
        self.build()
        with closing(sqlite3.connect(self.path)) as db, db:db.execute("UPDATE portraits SET base_pixels='bad'")
        self.build()
        with closing(sqlite3.connect(self.path)) as db, db:
            row=db.execute('SELECT base,base_sha,base_pixels FROM portraits').fetchone()
        _decode(*row).close()
    def test_null_material_metadata_repairs(self):
        self.build()
        with closing(sqlite3.connect(self.path)) as db, db:db.execute('UPDATE portraits SET metadata=NULL')
        self.build()
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertIsInstance(db.execute('SELECT metadata FROM portraits').fetchone()[0],str)

    def test_unknown_schema_never_overwrites(self):
        self.build()
        with closing(sqlite3.connect(self.path)) as db, db:db.execute('UPDATE portrait_schema SET version=99')
        with self.assertRaises(ValueError):self.build()
    def test_unsupported_index_and_oversize(self):
        with self.assertRaises(ValueError):self.build(inputs={'expected':[]})
        def too_big():yield 'player','1',Image.new('RGBA',(257,1)),Image.new('RGBA',(2,2)),{}
        with self.assertRaises(ValueError):self.build(decode=too_big)

    def assert_connections_closed(self, connections):
        self.assertTrue(connections)
        for connection in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')

    def tracked_connections(self, connections):
        connect = sqlite3.connect
        def tracked(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connections.append(connection)
            return connection
        return patch('wlre.services.world.portrait_database.sqlite3.connect', side_effect=tracked)

    def test_import_closes_connections_on_success_and_exception(self):
        connections = []
        def failed_verification():
            raise ValueError('source changed')
        with self.tracked_connections(connections):
            self.build()
            self.build()  # Existing snapshot early-return path.
            with self.assertRaises(ValueError):
                self.build(key='b', verify=failed_verification)
        self.assertEqual(len(connections), 3)
        self.assert_connections_closed(connections)

    def test_image_read_closes_connections_on_success_and_exception(self):
        catalog = self.build()
        connections = []
        with self.tracked_connections(connections):
            with patch('wlre.services.world.portrait_render.render',
                       side_effect=lambda *args: Image.new('RGBA', (2, 2))):
                with catalog.image('player', '1', ()) as image:
                    self.assertEqual(image.size, (2, 2))
        self.assert_connections_closed(connections)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE portrait_schema SET version=99')
        connections = []
        with self.tracked_connections(connections):
            with self.assertRaises(ValueError):
                catalog.image('player', '1', ())
        self.assert_connections_closed(connections)

if __name__ == '__main__': unittest.main()
