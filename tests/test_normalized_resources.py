import hashlib
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

from wlre.storage.normalized_resources import load_parsed


class NormalizedResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'inventory.sqlite3'
        self.key = 'a' * 64
        self.raw = {'ItemData_C': b'verified source'}
        self.rows = {7: {'name': '測試', 'values': (1, 2)}, (1, 3): [True, None, 1.5]}

    def load(self, parse=None, key=None, schema='items-v1', raw=None):
        return load_parsed(self.path, key or self.key, 'items', schema,
                           self.raw if raw is None else raw,
                           parse or (lambda: self.rows))

    def query(self, sql, args=()):
        with closing(sqlite3.connect(self.path)) as db, db:
            return db.execute(sql, args).fetchall()

    def test_roundtrip_preserves_integer_tuple_keys_and_returns_independent_rows(self):
        result = self.load()
        self.assertEqual(result, self.rows)
        result[7]['name'] = 'mutated'
        parser = Mock(side_effect=AssertionError('must read database'))
        self.assertEqual(self.load(parser), self.rows)
        parser.assert_not_called()

    def test_checksum_damage_rebuilt_only_from_exact_verified_sources_and_archived(self):
        self.load()
        self.query('UPDATE normalized_snapshots SET data=?', (b'bad derived data',))
        parser = Mock(return_value=self.rows)
        self.assertEqual(self.load(parser), self.rows)
        parser.assert_called_once()
        self.assertEqual(self.query("SELECT status,data FROM normalized_history WHERE status='repaired_derived'"),
                         [('repaired_derived', b'bad derived data')])

    def test_valid_checksum_but_invalid_codec_is_repaired(self):
        self.load()
        raw = b'["unknown",[]]'
        self.query('UPDATE normalized_snapshots SET data=?,sha256=?', (raw, hashlib.sha256(raw).hexdigest()))
        self.assertEqual(self.load(), self.rows)
        self.assertEqual(self.query("SELECT count(*) FROM normalized_history WHERE status='repaired_derived'"), [(1,)])

    def test_unknown_source_never_replaces_old_version_and_failed_raw_is_retained(self):
        self.load()
        parser = Mock(side_effect=ValueError('unknown binary layout'))
        with self.assertRaisesRegex(ValueError, 'unknown binary'):
            self.load(parser, key='b' * 64, raw={'ItemData_C': b'unknown'})
        self.assertEqual(self.load(), self.rows)
        self.assertEqual(self.query('SELECT count(*) FROM normalized_snapshots'), [(1,)])
        self.assertEqual(self.query('SELECT data FROM normalized_raw WHERE sha256=?',
                                   (hashlib.sha256(b'unknown').hexdigest(),)), [(b'unknown',)])
        self.assertEqual(self.query("SELECT status FROM normalized_history WHERE catalog_key=?", ('b'*64,)), [('parse_failed',)])

    def test_repair_failure_retains_original_and_does_not_silently_fallback(self):
        self.load()
        self.query('UPDATE normalized_snapshots SET data=?', (b'bad',))
        with self.assertRaises(ValueError):
            self.load(Mock(side_effect=ValueError('parser rejected')))
        self.assertEqual(self.query('SELECT data FROM normalized_snapshots'), [(b'bad',)])

    def test_same_catalog_changed_bytes_rejected(self):
        self.load()
        with self.assertRaisesRegex(ValueError, 'immutable'):
            self.load(raw={'ItemData_C': b'changed'})
        self.assertEqual(self.load(), self.rows)

    def test_raw_database_corruption_not_repaired_or_hidden(self):
        self.load()
        self.query('UPDATE normalized_raw SET data=?', (b'corrupt original',))
        with self.assertRaisesRegex(ValueError, 'raw resource integrity'):
            self.load()
        self.assertEqual(self.query('SELECT data FROM normalized_raw'), [(b'corrupt original',)])

    def test_schema_upgrade_and_version_rollback_keep_old_snapshots(self):
        self.load()
        new = {9: {'name': 'new'}}
        self.assertEqual(self.load(lambda: new, schema='items-v2'), new)
        self.assertEqual(self.load(lambda: new, key='b'*64), new)
        self.assertEqual(self.load(Mock(side_effect=AssertionError())), self.rows)
        self.assertEqual(self.query('SELECT count(*) FROM normalized_snapshots'), [(3,)])

    def test_future_database_schema_rejected_without_rewriting(self):
        self.load()
        self.query('UPDATE normalized_schema SET version=99')
        with self.assertRaisesRegex(ValueError, 'upgrade required'):
            self.load()
        self.assertEqual(self.query('SELECT version FROM normalized_schema'), [(99,)])

    def test_failed_multi_source_import_publishes_nothing(self):
        def parse():
            _ = {1: 'first valid source'}
            raise ValueError('second invalid source')
        with self.assertRaises(ValueError):
            self.load(parse, raw={'A': b'valid', 'B': b'invalid'})
        self.assertEqual(self.query('SELECT count(*) FROM normalized_snapshots'), [(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM normalized_raw'), [(2,)])

    def test_concurrent_import_parses_once(self):
        parser = Mock(return_value=self.rows)
        with ThreadPoolExecutor(max_workers=4) as executor:
            values = list(executor.map(lambda _: self.load(parser), range(4)))
        self.assertTrue(all(v == self.rows for v in values))
        parser.assert_called_once()

    def test_existing_inventory_tables_untouched(self):
        self.query('CREATE TABLE versions (id INTEGER PRIMARY KEY, catalog_key TEXT)')
        self.query('INSERT INTO versions VALUES (1,?)', (self.key,))
        self.load()
        self.assertEqual(self.query('SELECT * FROM versions'), [(1, self.key)])

    def test_unsupported_values_fail_before_publish(self):
        for value in [object(), float('nan'), {1, 2}]:
            with self.assertRaises(ValueError):
                self.load(lambda: value)
        self.assertEqual(self.query('SELECT count(*) FROM normalized_snapshots'), [(0,)])

    def test_invalid_identity_never_creates_database(self):
        with self.assertRaises(ValueError):
            self.load(key='../wrong')
        self.assertFalse(self.path.exists())

    def test_inspection_reports_damage_without_exposing_or_modifying_payloads(self):
        from wlre.storage.normalized_resources import inspect_database
        self.load()
        report = inspect_database(self.path)
        self.assertEqual(report['snapshots'][0]['status'], 'verified_checksum')
        self.assertNotIn('測試', str(report))
        self.query('UPDATE normalized_snapshots SET data=?', (b'bad',))
        self.assertEqual(inspect_database(self.path)['snapshots'][0]['status'], 'derived_rebuild_required')
        self.query('UPDATE normalized_raw SET data=?', (b'bad raw',))
        self.assertEqual(inspect_database(self.path)['snapshots'][0]['status'], 'raw_integrity_failed')
        self.assertEqual(self.query('SELECT data FROM normalized_snapshots'), [(b'bad',)])
