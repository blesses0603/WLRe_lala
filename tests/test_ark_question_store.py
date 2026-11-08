"""Durable learning, isolation and conflict tests without game credentials."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from contextlib import closing

from wlre.storage.ark_questions import QuestionStore, fingerprint


class QuestionStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'questions.sqlite3'
        self.store = QuestionStore(self.path)
        self.token = (True, 'a' * 64)
        self.question = dict(question=20, text='題目', options=[21, 22, 23, 24],
                             labels=['甲', '乙', '丙', '丁'])

    def test_unknown_questions_are_saved_without_inventing_answers(self):
        self.assertEqual(self.store.observe(self.token, 1, self.question), (None, 'unknown'))
        with closing(sqlite3.connect(self.path)) as db:
            answer, source = db.execute('SELECT answer,source FROM questions').fetchone()
        self.assertIsNone(answer); self.assertEqual(source, 'observed')

    def test_reopen_and_reordered_options_reuse_text_id(self):
        self.store.confirm(self.token, 1, self.question, 22)
        question = {**self.question, 'options': [24, 21, 23, 22], 'labels': ['丁', '甲', '丙', '乙']}
        self.assertEqual(QuestionStore(self.path).observe(self.token, 1, question), (22, 'confirmed'))

    def test_role_version_text_and_option_changes_do_not_reuse(self):
        self.store.confirm(self.token, 1, self.question, 22)
        self.assertEqual(self.store.observe(self.token, 2, self.question), (None, 'unknown'))
        self.assertEqual(self.store.observe((True, 'b' * 64), 1, self.question), (None, 'unknown'))
        for key, value in [('text', '不同題目'), ('labels', ['甲', '改變', '丙', '丁']),
                           ('options', [21, 22, 23, 25]), ('question', 30)]:
            with self.subTest(key=key):
                question = {**self.question, key: value}
                self.assertEqual(self.store.observe(self.token, 1, question), (None, 'unknown'))

    def test_conflicting_confirmations_remain_quarantined(self):
        self.assertEqual(self.store.confirm(self.token, 1, self.question, 22), 'confirmed')
        self.assertEqual(self.store.confirm(self.token, 1, self.question, 23), 'conflict')
        self.assertEqual(self.store.confirm(self.token, 1, self.question, 22), 'conflict')
        self.assertEqual(self.store.observe(self.token, 1, self.question), (None, 'conflict'))

    def test_wrong_result_only_quarantines_the_matching_confirmed_answer(self):
        self.store.confirm(self.token, 1, self.question, 22)
        self.store.reject(self.token, 1, self.question, 21)
        self.assertEqual(self.store.observe(self.token, 1, self.question), (22, 'confirmed'))
        self.store.reject(self.token, 1, self.question, 22)
        self.assertEqual(self.store.observe(self.token, 1, self.question), (None, 'conflict'))

    def test_concurrent_conflicting_writers_do_not_lose_the_conflict(self):
        self.store.observe(self.token, 1, self.question)
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda answer: QuestionStore(self.path).confirm(
                self.token, 1, self.question, answer), (22, 23)))
        self.assertEqual(self.store.observe(self.token, 1, self.question), (None, 'conflict'))

    def test_invalid_identity_and_answer_never_write(self):
        for token, role in [((False, 'a' * 64), 1), ((True, 'bad'), 1), (self.token, True), (self.token, 0)]:
            with self.subTest(token=token, role=role), self.assertRaises(ValueError):
                self.store.observe(token, role, self.question)
        for answer in (True, 99):
            with self.assertRaises(ValueError): self.store.confirm(self.token, 1, self.question, answer)
        self.assertFalse(self.path.exists())

    def test_malformed_options_and_text_fail_without_writing(self):
        for key, value in [('options', [21, 21, 23, 24]), ('options', [True, 22, 23, 24]),
                           ('labels', ['甲']), ('text', ''), ('text', 'x' * 32769)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.store.observe(self.token, 1, {**self.question, key: value})
        self.assertFalse(self.path.exists())

    def test_corrupt_database_is_not_overwritten(self):
        self.path.write_bytes(b'corrupt database')
        with self.assertRaises(sqlite3.DatabaseError): self.store.observe(self.token, 1, self.question)
        self.assertEqual(self.path.read_bytes(), b'corrupt database')

    def test_future_schema_is_not_replaced(self):
        with closing(sqlite3.connect(self.path)) as db: db.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError): self.store.observe(self.token, 1, self.question)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 99)


    def record(self, answer=22, **metadata):
        return self.store.record_candidate(self.token, 1, self.question, answer,
            metadata.get('source', 'reviewed-local'), metadata.get('revision', 'r1'))

    def test_candidates_are_durable_but_never_server_confirmed(self):
        self.assertEqual(self.record(), 'candidate')
        self.assertEqual(QuestionStore(self.path).observe(self.token, 1, self.question),
                         (None, 'unknown'))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT answer,source FROM questions').fetchone(),
                             (None, 'observed'))
            self.assertEqual(db.execute('SELECT answer,source,revision,rejected FROM candidates').fetchone(),
                             (22, 'reviewed-local', 'r1', 0))
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)

    def test_fingerprint_and_candidate_ignore_only_option_order(self):
        question = {**self.question, 'options': [24, 21, 23, 22], 'labels': ['丁', '甲', '丙', '乙']}
        self.assertEqual(fingerprint(question), fingerprint(self.question))
        self.record()
        self.assertEqual(self.store.record_candidate(self.token, 1, question, 22, 'reviewed', 'r2'),
                         'candidate')
        self.assertEqual(self.store.record_candidate(self.token, 1, question, 23, 'reviewed', 'r3'),
                         'conflict')
        self.assertEqual(self.record(), 'conflict')
        self.assertEqual(self.store.confirm(self.token, 1, question, 22), 'conflict')

    def test_matching_server_and_candidate_in_both_orders(self):
        for server_first in (True, False):
            with self.subTest(server_first=server_first):
                self.store = QuestionStore(self.path.with_name(str(server_first) + '.sqlite3'))
                if server_first:
                    self.store.confirm(self.token, 1, self.question, 22)
                    self.assertEqual(self.record(), 'confirmed')
                else:
                    self.record()
                    self.assertEqual(self.store.confirm(self.token, 1, self.question, 22), 'confirmed')
                self.assertEqual(self.store.observe(self.token, 1, self.question), (22, 'confirmed'))

    def test_mismatching_server_and_candidate_in_both_orders(self):
        for server_first in (True, False):
            with self.subTest(server_first=server_first):
                self.store = QuestionStore(self.path.with_name(str(server_first) + '.sqlite3'))
                if server_first:
                    self.store.confirm(self.token, 1, self.question, 23)
                    self.assertEqual(self.record(), 'conflict')
                else:
                    self.record()
                    self.assertEqual(self.store.confirm(self.token, 1, self.question, 23), 'conflict')
                self.assertEqual(self.record(), 'conflict')
                self.assertEqual(self.store.observe(self.token, 1, self.question), (None, 'conflict'))

    def test_candidate_wrong_result_is_tagged_and_permanent(self):
        self.record()
        self.store.reject(self.token, 1, self.question, 21)
        self.assertEqual(self.record(), 'candidate')
        self.store.reject(self.token, 1, self.question, 22, candidate=True)
        self.assertEqual(self.record(), 'conflict')
        self.assertEqual(self.store.confirm(self.token, 1, self.question, 22), 'conflict')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT rejected FROM candidates').fetchone(), (1,))

    def test_quarantine_without_previous_observation_is_permanent(self):
        self.assertEqual(self.store.quarantine(self.token, 1, self.question), 'conflict')
        self.assertEqual(self.record(), 'conflict')
        self.assertEqual(self.store.confirm(self.token, 1, self.question, 22), 'conflict')

    def test_invalid_candidate_metadata_and_answers_never_write(self):
        for field in ('source', 'revision'):
            for value in (None, True, 1, '', ' ', 'x\n', 'x\x00y', 'x' * 1025):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.record(**{field: value})
        with self.assertRaises(ValueError): self.record(source='server_confirmed')
        for answer in (True, 99):
            with self.assertRaises(ValueError): self.record(answer)
        self.assertFalse(self.path.exists())

    def test_concurrent_candidate_claim_is_once_only(self):
        self.record()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: QuestionStore(self.path).claim_candidate(
                self.token, 1, self.question, 22), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.record(), 'pending')
        reopened = QuestionStore(self.path)
        self.assertFalse(reopened.claim_candidate(self.token, 1, self.question, 22))
        self.assertEqual(reopened.record_candidate(self.token, 1, self.question, 22,
                                                  'reviewed-local', 'r2'), 'pending')

    def test_claim_requires_matching_recorded_nonrejected_candidate(self):
        self.assertFalse(self.store.claim_candidate(self.token, 1, self.question, 22))
        self.record()
        self.assertFalse(self.store.claim_candidate(self.token, 1, self.question, 23))
        self.assertFalse(self.store.claim_candidate(self.token, 2, self.question, 22))
        self.assertFalse(self.store.claim_candidate((True, 'b' * 64), 1, self.question, 22))
        self.store.reject(self.token, 1, self.question, 22, candidate=True)
        self.assertFalse(self.store.claim_candidate(self.token, 1, self.question, 22))

    def test_matching_confirmation_resolves_pending_claim(self):
        self.record()
        self.assertTrue(self.store.claim_candidate(self.token, 1, self.question, 22))
        self.assertEqual(self.store.confirm(self.token, 1, self.question, 22), 'confirmed')
        self.assertEqual(self.record(), 'confirmed')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM candidate_attempts').fetchone(), (0,))

    def test_candidate_rejection_resolves_pending_and_quarantines(self):
        self.record()
        self.assertTrue(self.store.claim_candidate(self.token, 1, self.question, 22))
        self.store.reject(self.token, 1, self.question, 21)
        self.assertEqual(self.record(), 'pending')
        self.store.reject(self.token, 1, self.question, 22, candidate=True)
        self.assertEqual(self.record(), 'conflict')
        self.assertFalse(self.store.claim_candidate(self.token, 1, self.question, 22))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM candidate_attempts').fetchone(), (0,))
            self.assertEqual(db.execute('SELECT rejected FROM candidates').fetchone(), (1,))

    def test_conflicting_candidate_evidence_overrides_pending_status(self):
        self.record()
        self.assertTrue(self.store.claim_candidate(self.token, 1, self.question, 22))
        self.assertEqual(self.record(23, source='other-review', revision='r2'), 'conflict')
        self.assertEqual(self.record(), 'conflict')
        self.assertFalse(self.store.claim_candidate(self.token, 1, self.question, 22))
        self.assertEqual(self.store.confirm(self.token, 1, self.question, 22), 'conflict')

    def test_additive_attempt_table_is_created_for_existing_v2_database(self):
        self.record()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP TABLE candidate_attempts')
            db.commit()
        self.assertTrue(QuestionStore(self.path).claim_candidate(self.token, 1, self.question, 22))
        self.assertEqual(self.record(), 'pending')

    def test_manual_candidate_attempt_persists_across_restart(self):
        self.record()
        self.assertTrue(self.store.record_candidate_attempt(self.token, 1, self.question, 22))
        reopened = QuestionStore(self.path)
        self.assertEqual(reopened.record_candidate(self.token, 1, self.question, 22,
                                                  'reviewed-local', 'r1'), 'pending')
        self.assertFalse(reopened.claim_candidate(self.token, 1, self.question, 22))
        self.assertEqual(reopened.observe(self.token, 1, self.question), (None, 'unknown'))

    def test_manual_candidate_attempt_is_idempotent_with_automatic_claim(self):
        self.record()
        self.assertTrue(self.store.claim_candidate(self.token, 1, self.question, 22))
        for _ in range(2):
            self.assertTrue(self.store.record_candidate_attempt(self.token, 1, self.question, 22))
            self.assertEqual(self.record(), 'pending')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT answer FROM candidate_attempts').fetchall(), [(22,)])

    def test_unmatched_manual_choices_do_not_claim_candidate(self):
        self.assertFalse(self.store.record_candidate_attempt(self.token, 1, self.question, 22))
        self.record()
        self.assertFalse(self.store.record_candidate_attempt(self.token, 1, self.question, 23))
        self.assertFalse(self.store.record_candidate_attempt(self.token, 2, self.question, 22))
        self.assertEqual(self.record(), 'candidate')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM candidate_attempts').fetchone(), (0,))

    def test_manual_attempt_preserves_rejection_and_quarantine(self):
        self.record()
        self.store.reject(self.token, 1, self.question, 22, candidate=True)
        self.assertTrue(self.store.record_candidate_attempt(self.token, 1, self.question, 22))
        self.assertEqual(self.record(), 'conflict')
        self.assertEqual(self.store.observe(self.token, 1, self.question), (None, 'conflict'))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT rejected FROM candidates').fetchone(), (1,))
            self.assertEqual(db.execute('SELECT answer FROM candidate_attempts').fetchone(), (22,))

    def test_manual_candidate_attempt_database_errors_propagate(self):
        self.record()
        with closing(sqlite3.connect(self.path)) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            try:
                with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                    self.store.record_candidate_attempt(self.token, 1, self.question, 22)
            finally:
                blocker.rollback()
        self.assertEqual(self.record(), 'candidate')

    def test_unregistered_manual_candidate_attempt_survives_restart(self):
        self.assertTrue(self.store.record_candidate_attempt(
            self.token, 1, self.question, 22, allow_unregistered=True))
        reopened = QuestionStore(self.path)
        self.assertEqual(reopened.record_candidate(self.token, 1, self.question, 22,
                                                  'reviewed-local', 'r1'), 'pending')
        self.assertFalse(reopened.claim_candidate(self.token, 1, self.question, 22))
        self.assertEqual(reopened.observe(self.token, 1, self.question), (None, 'unknown'))

    def test_unregistered_attempt_preserves_conflicting_candidate_and_claim(self):
        self.record()
        self.assertTrue(self.store.claim_candidate(self.token, 1, self.question, 22))
        self.assertTrue(self.store.record_candidate_attempt(
            self.token, 1, self.question, 23, allow_unregistered=True))
        self.assertEqual(self.record(), 'conflict')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT answer FROM candidates').fetchone(), (22,))
            self.assertEqual(db.execute('SELECT answer FROM candidate_attempts').fetchone(), (22,))

    def test_unregistered_attempt_conflicting_with_later_candidate_is_quarantined(self):
        self.assertTrue(self.store.record_candidate_attempt(
            self.token, 1, self.question, 23, allow_unregistered=True))
        self.assertEqual(self.record(), 'conflict')
        self.assertEqual(self.store.observe(self.token, 1, self.question), (None, 'conflict'))

    def test_unregistered_attempt_validates_answer_and_flag_before_writing(self):
        with self.assertRaises(ValueError):
            self.store.record_candidate_attempt(self.token, 1, self.question, 99,
                                                allow_unregistered=True)
        with self.assertRaises(ValueError):
            self.store.record_candidate_attempt(self.token, 1, self.question, 22,
                                                allow_unregistered=1)
        self.assertFalse(self.path.exists())

    def test_connection_configures_bounded_sqlite_busy_budget(self):
        with self.store._connection() as db:
            self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone(), (250,))

    def test_busy_database_fails_closed_without_retry(self):
        self._assert_busy_database_fails_closed()

    def test_slow_connection_does_not_change_busy_budget_or_retry(self):
        # Controlled delay outside SQLite's busy handler, not a CI timing limit.
        # A correct 250 ms busy budget cannot bound the whole operation's wall
        # time (macOS SQLite sleep overshoot has also been observed in CI).
        self._assert_busy_database_fails_closed(connection_delay=1.05)

    def _assert_busy_database_fails_closed(self, connection_delay=0):
        self.store.observe(self.token, 1, self.question)
        real_connect = sqlite3.connect
        statements = []
        busy_budgets = []
        closed = []

        class ObservedConnection(sqlite3.Connection):
            def execute(connection, sql, *args, **kwargs):
                statements.append(sql)
                if sql == 'BEGIN IMMEDIATE':
                    busy_budgets.append(super().execute('PRAGMA busy_timeout').fetchone()[0])
                return super().execute(sql, *args, **kwargs)

            def close(connection):
                closed.append(connection.in_transaction)
                return super().close()

        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs, factory=ObservedConnection)
            if connection_delay:
                time.sleep(connection_delay)
            return connection

        with closing(real_connect(self.path)) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            try:
                with patch('wlre.storage.ark_questions.sqlite3.connect', side_effect=connect) as opened:
                    with self.assertRaisesRegex(sqlite3.OperationalError, 'locked') as raised:
                        self.record()
                # Structured SQLite error codes were added in Python 3.11.
                if hasattr(raised.exception, 'sqlite_errorcode'):
                    self.assertEqual(raised.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
                opened.assert_called_once_with(self.path, timeout=0.25)
                self.assertEqual(busy_budgets, [250])
                self.assertEqual(statements, ['BEGIN IMMEDIATE'])
                self.assertEqual(closed, [False])
            finally:
                blocker.rollback()
        self.assertEqual(self.store.observe(self.token, 1, self.question), (None, 'unknown'))
        with closing(real_connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM candidates').fetchone(), (0,))

    def test_concurrent_candidate_conflicts_are_not_lost(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda answer: QuestionStore(self.path).record_candidate(
                self.token, 1, self.question, answer, 'reviewed', 'r1'), (22, 23)))
        self.assertIn('conflict', results)
        self.assertEqual(self.record(), 'conflict')

    def test_concurrent_candidate_and_server_conflict_is_not_lost(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.record), executor.submit(
                QuestionStore(self.path).confirm, self.token, 1, self.question, 23)]
            results = [future.result() for future in futures]
        self.assertIn('conflict', results)
        self.assertEqual(self.store.observe(self.token, 1, self.question), (None, 'conflict'))

    def test_old_schema_migration_preserves_confirmed_evidence(self):
        for version in (0, 1):
            with self.subTest(version=version):
                path = self.path.with_name('v' + str(version) + '.sqlite3')
                store = QuestionStore(path)
                store.confirm(self.token, 1, self.question, 22)
                with closing(sqlite3.connect(path)) as db:
                    db.execute('DROP TABLE candidates')
                    db.execute('PRAGMA user_version=' + str(version))
                    db.commit()
                self.assertEqual(store.observe(self.token, 1, self.question), (22, 'confirmed'))
                self.assertEqual(store.record_candidate(self.token, 1, self.question, 22,
                                                       'reviewed', 'r1'), 'confirmed')
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (2,))


if __name__ == '__main__': unittest.main()
