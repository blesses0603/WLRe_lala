"""1262 historical SQLite fallback regression, no server or user DB required."""
import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from wlre.paths import RESOURCE_ROOT
from wlre.storage.bundled_database import read_pinned_legacy_bytes, load_legacy_resource


class LegacySQLiteFallbackTests(unittest.TestCase):
    def test_verified_npc_catalog_without_source_file(self):
        from wlre.paths import RESOURCE_ROOT
        original = (RESOURCE_ROOT / 'npc_event_index_1262.json.gz').read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        with TemporaryDirectory() as folder:
            db_path = Path(folder) / 'resources.sqlite3'
            with closing(sqlite3.connect(db_path)) as db, db:
                db.execute('CREATE TABLE bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE bundled_resources (name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(name,sha256))')
                db.execute('INSERT INTO bundled_active VALUES (?,?)', ('npc_event_index_1262.json.gz', digest))
                db.execute('INSERT INTO bundled_resources VALUES (?,?,?)', ('npc_event_index_1262.json.gz', digest, original))
            self.assertEqual(read_pinned_legacy_bytes('npc_event_index_1262.json.gz', database=db_path), original)

    def test_sqlite_preferred_even_if_source_differs(self):
        name = 'npc_event_index_1262.json.gz'
        original = (RESOURCE_ROOT / name).read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        with TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / 'catalog.sqlite3'
            with closing(sqlite3.connect(db_path)) as db, db:
                db.execute('CREATE TABLE bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE bundled_resources (name TEXT, sha256 TEXT, data BLOB, PRIMARY KEY(name,sha256))')
                db.execute('INSERT INTO bundled_active VALUES (?,?)', (name, digest))
                db.execute('INSERT INTO bundled_resources VALUES (?,?,?)', (name, digest, original))
            (root / name).write_bytes(b'wrong source')
            self.assertEqual(load_legacy_resource(name, root=root, database=db_path), original)
            with closing(sqlite3.connect(db_path)) as db, db:
                db.execute('UPDATE bundled_resources SET data=? WHERE name=?', (b'corrupt', name))
            with self.assertRaises(ValueError):
                load_legacy_resource(name, root=root, database=db_path)

    def test_missing_database_uses_verified_original(self):
        name = 'npc_talk_1262.json.gz'
        with TemporaryDirectory() as folder:
            self.assertEqual(
                load_legacy_resource(name, root=RESOURCE_ROOT,
                                     database=Path(folder) / 'absent.sqlite3'),
                (RESOURCE_ROOT / name).read_bytes())

    def test_missing_db_fails_closed(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                read_pinned_legacy_bytes('npc_talk_1262.json.gz', database=Path(folder)/'missing.db')

    def test_unknown_name_is_rejected(self):
        with self.assertRaises(ValueError):
            read_pinned_legacy_bytes('untrusted.json')


if __name__ == '__main__':
    unittest.main()
