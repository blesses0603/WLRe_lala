"""Regression: missing bundled expedition JSON must still load verified SQLite data."""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from wlre.services.expedition import data as expedition_data


class ExpeditionSQLiteFallbackTests(unittest.TestCase):
    def test_missing_original_uses_sqlite(self):
        payload = {'tasks': {'1': {'name': 'test'}}, 'levels': {'1': {'teams': 1}}}
        with TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / 'inventory.sqlite3'
            raw = json.dumps(payload).encode('utf-8')
            import hashlib
            digest = hashlib.sha256(raw).hexdigest()
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE bundled_active (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)')
                db.execute('CREATE TABLE bundled_resources (name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(name,sha256))')
                db.execute('INSERT INTO bundled_active VALUES (?,?)', ('expedition_catalog.json', digest))
                db.execute('INSERT INTO bundled_resources VALUES (?,?,?)', ('expedition_catalog.json', digest, raw))
            with patch.object(expedition_data, 'RESOURCE_ROOT', root):
                with patch('wlre.storage.bundled_database.data_root', return_value=root):
                    # The default DB path is under data_root, so patch the loader to target this isolated DB.
                    from wlre.storage.bundled_database import load_bundled_json
                    with patch('wlre.storage.bundled_database.load_bundled_json',
                               side_effect=lambda name, **kwargs: load_bundled_json(name, database=database, **kwargs)):
                        self.assertEqual(expedition_data.load_catalog(), payload)

    def test_missing_source_and_database_raises(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(expedition_data, 'RESOURCE_ROOT', root):
                with patch('wlre.storage.bundled_database.data_root', return_value=root):
                    with self.assertRaises(FileNotFoundError):
                        expedition_data.load_catalog()


if __name__ == '__main__':
    unittest.main()
