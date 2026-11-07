from contextlib import closing
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from wlre.services.official_server_list import (
    sync_server_list, read_cached_server_list, parse_server_list, fetch_server_list,
    server_list_url)


def snapshot():
    return {'schema_version': 1, 'origin': 'official_pc_version_endpoint',
            'data_ver': '1.3.23', 'exe_version': '1.3.0',
            'packages': {'DataPackage': '1296_2026_11_04_13_34_19_13',
                         'MainPackage': '1296_2026_11_04_13_36_07_72'},
            'checked_at_utc': '2026-11-05T00:00:00+00:00', 'assets_ready': False}


def body(address='8.8.8.8'):
    return json.dumps([{'id': 1, 'name': '測試群組'},
                       {'id': 101, 'name': '測試一線', 'address': address, 'port': 16988}]).encode()


class OfficialServerListTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / 'resources.sqlite3'

    def sync(self, raw=None, observe=None):
        return sync_server_list(database=self.db, observe=observe or snapshot,
                                fetch=lambda version: body() if raw is None else raw)

    def test_first_offline_install_has_no_bundled_fallback_or_empty_database(self):
        self.assertEqual(read_cached_server_list(database=self.db)['rows'], [])
        self.assertFalse(self.db.exists())
        with patch('wlre.services.official_server_list.database_path', return_value=self.db), \
                patch('wlre.storage.full_resource_seed.read_config', side_effect=AssertionError('seed accessed')):
            from wlre.storage.server_lines import load
            self.assertEqual(load(), [])

    def test_verified_online_import_is_read_from_database_and_retains_source(self):
        result = self.sync()
        cached = read_cached_server_list(database=self.db)
        self.assertEqual(cached['rows'][0]['host'], '8.8.8.8')
        self.assertEqual(cached['origin'], result['origin'])
        self.assertEqual(cached['status'], 'cached')
        self.assertEqual(cached['data_ver'], '1.3.23')

    def test_changed_list_preserves_old_snapshot(self):
        self.sync(); self.sync(body('1.1.1.1'))
        self.assertEqual(read_cached_server_list(database=self.db)['rows'][0]['host'], '1.1.1.1')
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM normalized_snapshots WHERE feature='server_list'").fetchone()[0], 2)

    def test_bad_update_preserves_usable_version_and_failed_source(self):
        self.sync()
        with self.assertRaises(ValueError): self.sync(b'not JSON')
        cached = read_cached_server_list(database=self.db)
        self.assertEqual(cached['rows'][0]['host'], '8.8.8.8')
        self.assertEqual(cached['status'], 'cached_after_refresh_failure')
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT data FROM normalized_raw WHERE sha256=?',
                                        (hashlib.sha256(b'not JSON').hexdigest(),)).fetchone()[0], b'not JSON')

    def test_version_race_does_not_activate(self):
        newer = snapshot(); newer['data_ver'] = '1.3.24'
        with self.assertRaises(ValueError): self.sync(observe=Mock(side_effect=[snapshot(), newer]))
        self.assertEqual(read_cached_server_list(database=self.db)['rows'], [])

    def test_endpoint_and_group_corruption_rejected(self):
        for address in ('127.0.0.1', '10.0.0.1', 'https://example.com', '8.8.8.8:80', 'localhost'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                parse_server_list(body(address))
        bad = json.loads(body()); bad[1]['id'] = 201
        with self.assertRaises(ValueError): parse_server_list(json.dumps(bad).encode())
        bad = json.loads(body()); bad.append(bad[1])
        with self.assertRaises(ValueError): parse_server_list(json.dumps(bad).encode())

    def test_corrupt_snapshot_never_returns_seed_data(self):
        self.sync()
        with closing(sqlite3.connect(self.db)) as db, db: db.execute('UPDATE normalized_snapshots SET data=?', (b'bad',))
        with self.assertRaises(ValueError): read_cached_server_list(database=self.db)

    def test_corrupt_database_reports_value_error(self):
        self.db.write_bytes(b'not a database')
        with self.assertRaises(ValueError): read_cached_server_list(database=self.db)

    def test_fetch_bounded_same_origin_and_rejects_redirect_response(self):
        url = server_list_url('1.3.23')
        class Response(io.BytesIO):
            status = 200
            def geturl(self): return url
        def opener(request, timeout):
            self.assertEqual(request.full_url, url)
            self.assertEqual(request.get_header('Accept'), '*/*')
            return Response(body())
        self.assertEqual(fetch_server_list('1.3.23', opener=opener), body())
        with self.assertRaises(ValueError): fetch_server_list('../bad', opener=opener)
        with self.assertRaises(ValueError):
            fetch_server_list('1.3.23', opener=lambda *a, **k: Response(b'x' * 65537))
        with patch.object(Response, 'geturl', return_value='https://example.com/list'):
            with self.assertRaises(ValueError): fetch_server_list('1.3.23', opener=opener)

    def test_account_keys_use_new_official_list_and_old_settings_stay_intact(self):
        from wlre.storage.account_settings import server_scope
        self.sync()
        with patch('wlre.services.official_server_list.database_path', return_value=self.db):
            self.assertEqual(server_scope('8.8.8.8', 16988), ('official', 1))
            self.assertEqual(server_scope('custom.invalid', 1234), ('custom', 'custom.invalid', 1234))
