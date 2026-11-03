"""Durable learning, isolation and conflict tests without game credentials."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

from wlre.storage.ark_questions import QuestionStore


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


if __name__ == '__main__': unittest.main()
