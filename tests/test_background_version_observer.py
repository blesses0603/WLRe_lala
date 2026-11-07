"""Offline-only metadata observation, bounded scheduling and stale-result tests."""

from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from wlre.services import background_version_observer as observer
from wlre.services import official_version


DATA = '1296_2026_11_04_13_34_19_13'
MAIN = '1295_2026_11_04_13_35_19_13'
RESOURCE_MAP = b'[{"ExeVer":"1.3.0","DataVer":"1.3.22.1"}]'


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def identity():
    return {'schema_version': 1, 'data_ver': '1.3.22.1', 'exe_version': '1.3.0',
            'packages': [
                {'name': 'DataPackage', 'full_version': DATA,
                 'manifest_sha256': 'a' * 64, 'manifest_crc32_le': '1' * 8},
                {'name': 'MainPackage', 'full_version': MAIN,
                 'manifest_sha256': 'b' * 64, 'manifest_crc32_le': '2' * 8}]}


def result(status='identifiers_match', official=None, database=None):
    versions = observer.version_identifiers_from_database(identity())
    return observer.ObservationResult(
        status, 'observed' if status != 'unverified' else 'official_unavailable',
        official or versions, database or versions, '2026-11-07T10:00:00+00:00')


class BackgroundVersionObserverTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / 'inventory.sqlite3'
        self.clock = Clock()
        self.calls = []
        urls = official_version.official_package_urls('1.3.22.1')
        self.responses = {official_version.RESOURCE_MAP_URL: RESOURCE_MAP,
                          urls['DataPackage']: DATA.encode(),
                          urls['MainPackage']: MAIN.encode()}
        self.write_identity(identity())

    def write_identity(self, document):
        content = json.dumps(document, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS versions (id INTEGER PRIMARY KEY, catalog_key TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS version_identities (version_id INTEGER PRIMARY KEY, identity TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS sync_state (singleton INTEGER PRIMARY KEY, active_id INTEGER)')
            db.execute('INSERT OR REPLACE INTO versions VALUES (1, ?)',
                       (hashlib.sha256(content.encode('ascii')).hexdigest(),))
            db.execute('INSERT OR REPLACE INTO version_identities VALUES (1, ?)', (content,))
            db.execute('INSERT OR REPLACE INTO sync_state VALUES (1, 1)')

    def fetch(self, url, *, timeout):
        self.calls.append((url, timeout))
        return self.responses[url]

    def observe(self, **kwargs):
        return observer.observe_background_versions(
            database_path=self.path, fetcher=kwargs.pop('fetcher', self.fetch),
            clock=self.clock, **kwargs)

    def test_exact_three_metadata_reads_and_read_only_database_identity(self):
        before = self.path.read_bytes()
        filenames = sorted(self.root.iterdir())
        got = self.observe()
        urls = official_version.official_package_urls('1.3.22.1')
        self.assertEqual(self.calls, [(official_version.RESOURCE_MAP_URL, 12.0),
                                     (urls['DataPackage'], 12.0), (urls['MainPackage'], 12.0)])
        self.assertEqual(got.status, 'identifiers_match')
        self.assertEqual(got.official, got.database)
        self.assertEqual(got.database.data_package, DATA)
        self.assertEqual(got.database.main_package, MAIN)
        self.assertEqual(got.database.data_ver, '1.3.22.1')
        self.assertEqual(got.database.exe_version, '1.3.0')
        self.assertIsNotNone(datetime.fromisoformat(got.checked_at_utc).tzinfo)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(filenames, sorted(self.root.iterdir()))
        self.assertFalse(hasattr(got, 'login_allowed'))
        self.assertFalse(hasattr(got, 'can_send_packets'))
        with self.assertRaises(FrozenInstanceError):
            got.status = 'different'

    def test_no_runtime_manifests_bundles_content_checks_or_database_writes(self):
        forbidden = (
            'wlre.services.world.dynamic_bundle_runtime.prepare_dynamic_runtime',
            'wlre.services.world.dynamic_bundle_runtime.activate_for_official',
            'wlre.services.official_manifest_sync.fetch_official_manifest',
            'wlre.services.official_bundle_download.fetch_bundle',
            'wlre.services.world.resource_database.database_matches_runtime',
            'wlre.services.world.resource_database.record_inventory',
            'wlre.services.world.eve_v115.derive_eve_indexes',
            'wlre.services.official_resource_sync.save_snapshot',
        )
        mocks = []
        for target in forbidden:
            patcher = patch(target, side_effect=AssertionError('Heavy work is forbidden'))
            mocks.append(patcher.start())
            self.addCleanup(patcher.stop)
        sql_reads = []
        connect = sqlite3.connect

        def readonly_connect(*args, **kwargs):
            self.assertTrue(args[0].endswith('?mode=ro'))
            self.assertIs(kwargs.get('uri'), True)
            db = connect(*args, **kwargs)

            def authorize(action, table, column, database, source):
                if action == sqlite3.SQLITE_READ:
                    sql_reads.append(table)
                    return (sqlite3.SQLITE_OK if table in
                            ('sync_state', 'versions', 'version_identities') else sqlite3.SQLITE_DENY)
                if action != sqlite3.SQLITE_SELECT:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            db.set_authorizer(authorize)
            return db

        with patch('sqlite3.connect', side_effect=readonly_connect):
            self.assertEqual(self.observe().status, 'identifiers_match')
        self.assertEqual(set(sql_reads), {'sync_state', 'versions', 'version_identities'})
        for forbidden_call in mocks:
            forbidden_call.assert_not_called()

    def test_each_version_field_is_compared_including_full_package_timestamp(self):
        for field, value in (('exe_version', '1.3.1'), ('data_ver', '1.3.22.2'),
                             ('DataPackage', DATA[:-2] + '14'),
                             ('MainPackage', MAIN[:-2] + '14')):
            with self.subTest(field=field):
                document = identity()
                if field.endswith('Package'):
                    next(row for row in document['packages'] if row['name'] == field)['full_version'] = value
                else:
                    document[field] = value
                self.write_identity(document)
                self.assertEqual(self.observe().status, 'identifiers_differ')

    def test_new_executable_selects_new_data_path_not_stale_path(self):
        urls = official_version.official_package_urls('1.4.0')
        self.responses.update({official_version.RESOURCE_MAP_URL:
                               RESOURCE_MAP[:-1] + b',{"ExeVer":"1.4.0","DataVer":"1.4.0"}]',
                               urls['DataPackage']: DATA.encode(), urls['MainPackage']: MAIN.encode()})
        got = self.observe()
        self.assertEqual(got.status, 'identifiers_differ')
        self.assertEqual(got.official.exe_version, '1.4.0')
        self.assertEqual([call[0] for call in self.calls][1:],
                         [urls['DataPackage'], urls['MainPackage']])

    def test_missing_database_never_created_or_reported_matching(self):
        self.path.unlink()
        got = self.observe()
        self.assertEqual((got.status, got.reason), ('unverified', 'database_unavailable'))
        self.assertIsNotNone(got.official)
        self.assertIsNone(got.database)
        self.assertFalse(self.path.exists())

    def test_corrupt_or_symlink_database_is_unverified(self):
        self.path.write_bytes(b'not sqlite')
        self.assertEqual(self.observe().status, 'unverified')
        self.path.unlink()
        target = self.root / 'target.sqlite3'
        target.write_bytes(b'unchanged')
        self.path.symlink_to(target)
        self.assertEqual(self.observe().status, 'unverified')
        self.assertEqual(target.read_bytes(), b'unchanged')

    def test_unhashed_modified_identity_is_unverified(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE version_identities SET identity='{}'")
        self.assertEqual(self.observe().status, 'unverified')

    def test_malformed_rehashed_database_identity_is_unverified(self):
        cases = []
        for field, value in (('schema_version', True), ('exe_version', 'bad'),
                             ('data_ver', '../../private')):
            cases.append(dict(identity(), **{field: value}))
        duplicate = identity()
        duplicate['packages'][1] = dict(duplicate['packages'][0])
        cases.append(duplicate)
        for field, value in (('full_version', '1296'), ('manifest_sha256', 'bad'),
                             ('manifest_crc32_le', 'bad'), ('name', ['DataPackage'])):
            document = identity()
            document['packages'][0][field] = value
            cases.append(document)
        for document in cases:
            with self.subTest(document=document):
                self.write_identity(document)
                self.assertEqual(self.observe().status, 'unverified')

    def test_resource_content_is_deliberately_not_verified(self):
        # A version hint must not become a content proof. Even this fixture has
        # no resources table; full gate remains solely responsible for bytes.
        changed_hash = identity()
        changed_hash['packages'][0]['manifest_sha256'] = 'c' * 64
        self.write_identity(changed_hash)
        got = self.observe()
        self.assertEqual(got.status, 'identifiers_match')
        self.assertFalse(hasattr(got, 'database_verified'))

    def test_offline_or_bad_metadata_does_not_fall_back_to_stale_identity(self):
        for value in (OSError('private URL/token must not appear'), b'<html>error</html>',
                      b'x' * (official_version.MAX_RESPONSE_BYTES + 1)):
            with self.subTest(value=type(value)):
                fetch = Mock(side_effect=value) if isinstance(value, Exception) else Mock(return_value=value)
                got = self.observe(fetcher=fetch)
                self.assertEqual((got.status, got.reason), ('unverified', 'official_unavailable'))
                self.assertIsNone(got.official)
                self.assertNotIn('private', repr(got))
                self.assertEqual(fetch.call_count, 1)

    def test_partial_metadata_failure_is_not_a_successful_observation(self):
        def fetch(url, *, timeout):
            if url.endswith('MainPackage.version'):
                raise TimeoutError('slow CDN')
            return self.fetch(url, timeout=timeout)
        got = self.observe(fetcher=fetch)
        self.assertEqual(got.status, 'unverified')
        self.assertIsNone(got.official)

    def test_slow_metadata_within_budget_succeeds(self):
        def fetch(url, *, timeout):
            self.clock.advance(7)
            return self.fetch(url, timeout=timeout)
        got = self.observe(fetcher=fetch)
        self.assertEqual(got.status, 'identifiers_match')
        self.assertEqual([timeout for _, timeout in self.calls], [12.0, 12.0, 12.0])
        self.assertEqual(self.clock.now, 21)

    def test_remaining_budget_shrinks_request_timeout_and_discards_late_response(self):
        def fetch(url, *, timeout):
            self.clock.advance(11)
            return self.fetch(url, timeout=timeout)
        got = self.observe(fetcher=fetch)
        self.assertEqual([timeout for _, timeout in self.calls], [12.0, 12.0, 8.0])
        self.assertEqual((got.status, got.reason), ('unverified', 'timeout'))
        self.assertIsNone(got.official)

    def test_budget_exhaustion_stops_subsequent_gets_and_database_read(self):
        def fetch(url, *, timeout):
            self.clock.advance(30)
            return self.fetch(url, timeout=timeout)
        with patch.object(observer, 'read_active_database_identity') as read:
            got = self.observe(fetcher=fetch)
        self.assertEqual((got.status, got.reason), ('unverified', 'timeout'))
        self.assertEqual(len(self.calls), 1)
        read.assert_not_called()

    def test_late_database_read_cannot_publish_match(self):
        def read(path):
            self.clock.advance(31)
            return identity()
        with patch.object(observer, 'read_active_database_identity', side_effect=read):
            got = self.observe()
        self.assertEqual((got.status, got.reason), ('unverified', 'timeout'))
        self.assertIsNone(got.database)

    def test_invalid_timeout_settings_do_not_start_io(self):
        for key in ('request_timeout', 'timeout_budget'):
            for value in (True, -1, 0, 31, float('inf'), float('nan')):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.observe(**{key: value})
        self.assertEqual(self.calls, [])

    def test_production_transport_has_no_retry_or_redirect_fallback(self):
        url = official_version.RESOURCE_MAP_URL
        for code in (301, 400, 403, 404, 500):
            with self.subTest(code=code):
                opened = Mock(side_effect=HTTPError(url, code, 'private response', None, None))
                with patch.object(observer, 'build_opener', return_value=Mock(open=opened)):
                    with self.assertRaises(official_version.VersionSourceError):
                        observer._fetch_metadata(url, timeout=12)
                self.assertEqual(opened.call_count, 1)
        self.assertIsNone(observer._NoRedirect().redirect_request(None, None, 302, '', {}, url))

    def test_production_transport_uses_existing_url_body_and_response_checks(self):
        class Response(io.BytesIO):
            status = 200
            def geturl(self):
                return official_version.RESOURCE_MAP_URL
        opened = Mock(side_effect=lambda *a, **k: Response(RESOURCE_MAP))
        with patch.object(observer, 'build_opener', return_value=Mock(open=opened)):
            self.assertEqual(observer._fetch_metadata(official_version.RESOURCE_MAP_URL,
                                                     timeout=8), RESOURCE_MAP)
            with self.assertRaises(official_version.VersionSourceError):
                observer._fetch_metadata('https://example.com/private', timeout=8)
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(opened.call_args.kwargs['timeout'], 8)
        self.assertEqual(opened.call_args.args[0].full_url, official_version.RESOURCE_MAP_URL)


class ObservationScheduleTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.schedule = observer.ObservationSchedule(clock=self.clock)

    def complete(self, outcome=None):
        token = self.schedule.begin()
        self.assertIsNotNone(token)
        self.assertTrue(self.schedule.finish(token, outcome or result()))

    def test_default_interval_and_single_flight_even_when_forced(self):
        token = self.schedule.begin()
        self.assertIsNotNone(token)
        self.assertIsNone(self.schedule.begin(force=True))
        self.assertIsNone(self.schedule.seconds_until_due())
        self.assertTrue(self.schedule.finish(token, result()))
        self.assertEqual(self.schedule.seconds_until_due(), 300)
        self.assertIsNone(self.schedule.begin())
        self.clock.advance(300)
        self.assertIsNotNone(self.schedule.begin())

    def test_initial_delay_and_bounded_configuration(self):
        for value, expected in ((-1, 60), ('90', 90), (9999, 3600),
                                ('invalid', 300), (True, 300), (float('nan'), 300)):
            with self.subTest(value=value):
                schedule = observer.ObservationSchedule(value, clock=self.clock, initial_delay=True)
                self.assertEqual(schedule.interval_seconds, expected)
                self.assertEqual(schedule.seconds_until_due(), expected)
                self.assertIsNone(schedule.begin())

    def test_failure_backoff_one_two_five_ten_minutes_and_success_reset(self):
        for delay in (60, 120, 300, 600, 600):
            self.complete(result('unverified'))
            self.assertEqual(self.schedule.seconds_until_due(), delay)
            self.clock.advance(delay)
        self.complete()
        self.assertEqual(self.schedule.failure_count, 0)
        self.assertEqual(self.schedule.seconds_until_due(), 300)

    def test_forced_failure_replaces_current_match_but_retains_historical_time(self):
        self.complete()
        previous_time = self.schedule.last_success_at
        token = self.schedule.begin(force=True)
        self.assertTrue(self.schedule.finish(token, result('unverified')))
        self.assertEqual(self.schedule.latest.status, 'unverified')
        self.assertEqual(self.schedule.last_success_at, previous_time)
        self.assertEqual(self.schedule.seconds_until_due(), 60)

    def test_close_disables_manual_checks_and_discards_late_success(self):
        token = self.schedule.begin()
        self.schedule.close()
        self.assertIsNone(self.schedule.begin(force=True))
        self.assertFalse(self.schedule.finish(token, result()))
        self.assertIsNone(self.schedule.latest)
        self.assertIsNone(self.schedule.seconds_until_due())
        self.schedule.supersede(result().official)
        self.assertIsNone(self.schedule.begin(force=True))

    def test_supersede_preserves_physical_single_flight_and_discards_previous_generation(self):
        token = self.schedule.begin()
        baseline = replace(result().official, data_package=DATA[:-2] + '14')
        self.schedule.supersede(baseline)
        self.assertIsNone(self.schedule.begin(force=True))
        self.assertFalse(self.schedule.finish(token, result()))
        self.assertIsNone(self.schedule.latest)
        self.assertEqual(self.schedule.seconds_until_due(), 300)
        self.clock.advance(300)
        current = self.schedule.begin()
        self.assertFalse(self.schedule.finish(token, result('unverified')))
        self.assertTrue(self.schedule.finish(current, result()))
        self.assertIs(self.schedule.changed_from_baseline, True)

    def test_matching_official_and_database_can_still_differ_from_full_gate_baseline(self):
        baseline = result().official
        self.schedule.supersede(baseline)
        self.clock.advance(300)
        newer = replace(baseline, main_package=MAIN[:-2] + '14')
        self.complete(result(official=newer, database=newer))
        self.assertEqual(self.schedule.latest.status, 'identifiers_match')
        self.assertTrue(self.schedule.changed_from_baseline)
        self.assertEqual(self.schedule.baseline, baseline)

    def test_background_match_never_creates_or_updates_full_gate_baseline(self):
        self.complete()
        self.assertIsNone(self.schedule.baseline)
        self.assertIsNone(self.schedule.changed_from_baseline)
        # Only an explicit full-gate handoff supplies the baseline. A later
        # observation is not a new compatibility/authorization timestamp.
        baseline = result().official
        self.schedule.supersede(baseline)
        self.clock.advance(300)
        self.complete()
        self.assertEqual(self.schedule.baseline, baseline)
        self.assertFalse(self.schedule.changed_from_baseline)

    def test_setting_interval_does_not_reset_results_or_inflight_tokens(self):
        self.complete()
        latest = self.schedule.latest
        token = self.schedule.begin(force=True)
        self.assertEqual(self.schedule.set_interval('120'), 120)
        self.assertIs(self.schedule.latest, latest)
        self.assertIsNotNone(self.schedule.last_success_at)
        self.assertIsNone(self.schedule.begin(force=True))
        self.assertTrue(self.schedule.finish(token, result()))
        self.assertEqual(self.schedule.seconds_until_due(), 120)

    def test_setting_interval_cannot_shorten_failure_backoff(self):
        for delay in (60, 120, 300, 600):
            self.complete(result('unverified'))
            self.assertEqual(self.schedule.set_interval(60), 60)
            self.assertEqual(self.schedule.seconds_until_due(), delay)
            self.clock.advance(delay)

    def test_invalid_result_is_unverified_and_cannot_leave_matching_status(self):
        self.complete()
        token = self.schedule.begin(force=True)
        self.assertTrue(self.schedule.finish(token, {'status': 'identifiers_match'}))
        self.assertEqual(self.schedule.latest.status, 'unverified')

    def test_incomplete_or_inconsistent_frozen_result_cannot_claim_match(self):
        for bad in (replace(result(), official=None), replace(result(), database=None),
                    replace(result(), status='identifiers_differ')):
            with self.subTest(bad=bad):
                token = self.schedule.begin(force=True)
                self.assertTrue(self.schedule.finish(token, bad))
                self.assertEqual(self.schedule.latest.status, 'unverified')

    def test_token_from_other_schedule_cannot_release_or_complete_live_worker(self):
        mine = self.schedule.begin()
        other = observer.ObservationSchedule(clock=self.clock).begin()
        self.assertFalse(self.schedule.finish(other, result()))
        self.assertIsNone(self.schedule.begin(force=True))
        self.assertTrue(self.schedule.finish(mine, result()))

    def test_concurrent_begins_reserve_only_one_worker(self):
        tokens = []
        barrier = threading.Barrier(8)
        def begin():
            barrier.wait()
            tokens.append(self.schedule.begin(force=True))
        threads = [threading.Thread(target=begin) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sum(token is not None for token in tokens), 1)


if __name__ == '__main__':
    unittest.main()
