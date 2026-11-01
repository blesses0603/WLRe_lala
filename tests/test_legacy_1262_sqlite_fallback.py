"""1262 historical SQLite fallback regression, no server or user DB required."""
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from wlre.storage.bundled_database import read_pinned_legacy_bytes


class LegacySQLiteFallbackTests(unittest.TestCase):
    def test_verified_npc_catalog_without_source_file(self):
        from wlre.paths import RESOURCE_ROOT
        original = (RESOURCE_ROOT / 'npc_event_index_1262.json.gz').read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        with TemporaryDirectory() as folder:
            db_path = Path(folder) / 'resources.sqlite3'
            with sqlite3.connect(db_path) as db:
                db.execute('CREATE TABLE bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE bundled_resources (name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(name,sha256))')
                db.execute('INSERT INTO bundled_active VALUES (?,?)', ('npc_event_index_1262.json.gz', digest))
                db.execute('INSERT INTO bundled_resources VALUES (?,?,?)', ('npc_event_index_1262.json.gz', digest, original))
            self.assertEqual(read_pinned_legacy_bytes('npc_event_index_1262.json.gz', database=db_path), original)

    def test_missing_db_fails_closed(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                read_pinned_legacy_bytes('npc_talk_1262.json.gz', database=Path(folder)/'missing.db')

    def test_unknown_name_is_rejected(self):
        with self.assertRaises(ValueError):
            read_pinned_legacy_bytes('untrusted.json')


if __name__ == '__main__':
    unittest.main()
