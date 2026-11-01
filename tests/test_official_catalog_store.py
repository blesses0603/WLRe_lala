"""Atomic official catalog metadata persistence tests."""
from contextlib import closing
import tempfile
from pathlib import Path
import unittest

from wlre.services.world.catalog_adapters import FEATURES, ParsedCatalog
from wlre.services.world.official_catalog_store import (
    active_official_catalog, store_official_catalog,
)


class OfficialCatalogStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'official.sqlite'

    def records(self, key='a' * 64):
        return {name: ParsedCatalog(key, name, name + '.bytes', 'schema-v1',
                'b' * 64, 0, {}, False, False) for name in FEATURES}

    def test_atomic_publish_and_read_only_result(self):
        self.assertIsNone(active_official_catalog(self.path))
        self.assertEqual(store_official_catalog(self.path, self.records()), 'a' * 64)
        status = active_official_catalog(self.path)
        self.assertEqual(set(status['sources']), set(FEATURES))
        self.assertFalse(status['can_send_packets'])
        self.assertFalse(status['assets_ready'])

    def test_missing_source_preserves_active_version(self):
        store_official_catalog(self.path, self.records())
        incomplete = self.records('c' * 64)
        incomplete.pop('npc')
        with self.assertRaises(ValueError):
            store_official_catalog(self.path, incomplete)
        self.assertEqual(active_official_catalog(self.path)['catalog_key'], 'a' * 64)

    def test_mixed_version_rejected(self):
        records = self.records()
        records['npc'] = self.records('c' * 64)['npc']
        with self.assertRaises(ValueError):
            store_official_catalog(self.path, records)
        self.assertIsNone(active_official_catalog(self.path))

    def test_corrupt_active_metadata_is_not_loaded(self):
        import sqlite3
        store_official_catalog(self.path, self.records())
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE official_catalog_sources SET sha256=? WHERE feature=?',
                       ('invalid', 'npc'))
        self.assertIsNone(active_official_catalog(self.path))

    def test_incomplete_active_metadata_is_not_loaded(self):
        import sqlite3
        store_official_catalog(self.path, self.records())
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM official_catalog_sources WHERE feature=?', ('shops',))
        self.assertIsNone(active_official_catalog(self.path))

    def test_immutable_revision_rejected(self):
        store_official_catalog(self.path, self.records())
        records = self.records()
        old = records['npc']
        records['npc'] = ParsedCatalog(old.catalog_key, old.feature,
                old.source_name, old.schema_id, 'c' * 64, old.record_count,
                old.records, False, False)
        with self.assertRaises(ValueError):
            store_official_catalog(self.path, records)
        self.assertEqual(active_official_catalog(self.path)['sources']['npc']['sha256'], 'b' * 64)


if __name__ == '__main__':
    unittest.main()
