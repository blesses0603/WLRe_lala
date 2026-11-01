"""1262 SQLite 歷史資料缺檔測試；不使用正式伺服器。"""
import hashlib
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wlre.storage.bundled_database import read_pinned_legacy_bytes


class LegacySQLiteMissingFilesTests(unittest.TestCase):
    def test_missing_files_can_read_existing_database_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'legacy.sqlite3'
            name = 'instance_catalog_1262.json'
            data = b'{"version":1262}'
            digest = hashlib.sha256(data).hexdigest()
            with closing(sqlite3.connect(db)) as con, con:
                con.execute('CREATE TABLE bundled_resources (name TEXT, sha256 TEXT, data BLOB)')
                con.execute('CREATE TABLE bundled_active (name TEXT, sha256 TEXT)')
                con.execute('INSERT INTO bundled_resources VALUES (?, ?, ?)', (name, digest, data))
                con.execute('INSERT INTO bundled_active VALUES (?, ?)', (name, digest))
            self.assertEqual(read_pinned_legacy_bytes(name, database=db), data)
            self.assertFalse((Path(tmp) / name).exists())

    def test_corrupt_or_missing_database_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'legacy.sqlite3'
            with self.assertRaises(FileNotFoundError):
                read_pinned_legacy_bytes('instance_catalog_1262.json', database=db)
            with closing(sqlite3.connect(db)) as con, con:
                con.execute('CREATE TABLE bundled_resources (name TEXT, sha256 TEXT, data BLOB)')
                con.execute('CREATE TABLE bundled_active (name TEXT, sha256 TEXT)')
                con.execute('INSERT INTO bundled_resources VALUES (?, ?, ?)',
                            ('instance_catalog_1262.json', '0'*64, b'corrupt'))
                con.execute('INSERT INTO bundled_active VALUES (?, ?)',
                            ('instance_catalog_1262.json', '0'*64))
            with self.assertRaises(ValueError):
                read_pinned_legacy_bytes('instance_catalog_1262.json', database=db)

    def test_unknown_name_is_rejected(self):
        with self.assertRaises(ValueError):
            read_pinned_legacy_bytes('../unsafe.json')


if __name__ == '__main__':
    unittest.main()
