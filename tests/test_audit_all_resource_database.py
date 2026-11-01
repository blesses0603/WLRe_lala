"""Tests for read-only full resource inventory audit."""
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tools.audit_all_resource_database import audit


class FullResourceAuditTests(unittest.TestCase):
    def test_identical_missing_and_mismatch(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            assets = root / 'assets'
            assets.mkdir()
            (assets / 'a.json').write_bytes(b'{"a":1}')
            (assets / 'b.zip').write_bytes(b'zip-content')
            (assets / 'c.gz').write_bytes(b'compressed')
            database = root / 'db.sqlite3'
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE bundled_resources (name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(name,sha256))')
                a = (assets / 'a.json').read_bytes()
                digest = hashlib.sha256(a).hexdigest()
                db.execute('INSERT INTO bundled_active VALUES (?,?)', ('a.json', digest))
                db.execute('INSERT INTO bundled_resources VALUES (?,?,?)', ('a.json', digest, a))
                db.execute('INSERT INTO bundled_active VALUES (?,?)', ('b.zip', '0' * 64))
            report = audit(database, assets)
            self.assertEqual([x['status'] for x in report['files']],
                             ['identical', 'active_hash_mismatch', 'not_imported'])
            self.assertEqual(report['summary']['total'], 3)
            self.assertFalse(report['all_identical'])

    def test_corrupt_blob_and_missing_database(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'a.json').write_bytes(b'hello')
            missing = audit(root / 'missing.sqlite3', root)
            self.assertEqual(missing['error'], 'database_missing')
            database = root / 'db.sqlite3'
            digest = hashlib.sha256(b'hello').hexdigest()
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE bundled_resources (name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(name,sha256))')
                db.execute('INSERT INTO bundled_active VALUES (?,?)', ('a.json', digest))
                db.execute('INSERT INTO bundled_resources VALUES (?,?,?)', ('a.json', digest, b'bad'))
            report = audit(database, root)
            self.assertEqual(report['files'][0]['status'], 'blob_corrupt')


if __name__ == '__main__':
    unittest.main()
