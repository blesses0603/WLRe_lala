from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from wlre.storage.bundled_database import load_bundled_json


class BundledDatabaseTests(unittest.TestCase):
    def test_imports_and_keeps_each_bundled_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'catalog.json'
            database = root / 'resources.sqlite3'
            source.write_text(json.dumps({'version': 1262}), encoding='utf-8')
            self.assertEqual(load_bundled_json(source.name, root=root, database=database)['version'], 1262)
            source.write_text(json.dumps({'version': 1275}), encoding='utf-8')
            self.assertEqual(load_bundled_json(source.name, root=root, database=database)['version'], 1275)
            source.unlink()
            self.assertEqual(load_bundled_json(source.name, root=root, database=database)['version'], 1275)
            with closing(sqlite3.connect(database)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM bundled_resources').fetchone()[0], 2)

    def test_missing_source_uses_database_for_all_catalogs(self):
        names = ('combat_catalog.json', 'crafting_catalog.json', 'alchemy_catalog.json',
                 'expedition_catalog.json', 'map_names.json', 'portals.json',
                 'item_icon_map.json', 'item_stackable.json', 'stage_coordinates.json')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'resources.sqlite3'
            for name in names:
                source = root / name
                expected = {'catalog': name, 'revision': 1262}
                source.write_text(json.dumps(expected), encoding='utf-8')
                self.assertEqual(load_bundled_json(name, root=root, database=database), expected)
                source.unlink()
                self.assertEqual(load_bundled_json(name, root=root, database=database), expected)
            with closing(sqlite3.connect(database)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM bundled_active').fetchone()[0], len(names))

    def test_rejects_corrupt_database_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'catalog.json').write_text('{}', encoding='utf-8')
            database = root / 'resources.sqlite3'
            load_bundled_json('catalog.json', root=root, database=database)
            with closing(sqlite3.connect(database)) as db, db:
                db.execute("UPDATE bundled_resources SET data=?", (b'bad',))
            with self.assertRaises(ValueError):
                load_bundled_json('catalog.json', root=root, database=database)
