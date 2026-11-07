"""Private version-scoped Ark evidence, with candidates distinct from confirmations.

Option order is excluded from identity; IDs AND exact texts are included.
Contradictory evidence is quarantined permanently instead of last-write wins.
"""
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import time

from wlre.storage.paths import data_root


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def fingerprint(question):
    """Return exact question identity and canonical payload, independent of role."""
    if not isinstance(question, dict):
        raise ValueError('問答文字或選項格式無效')
    qid = question.get('question'); options = question.get('options')
    text = question.get('text'); labels = question.get('labels')
    if (type(qid) is not int or not 0 < qid <= 0xffffffff
            or not isinstance(options, list) or len(options) != 4
            or any(type(i) is not int or not 0 < i <= 0xffffffff for i in options)
            or len(set(options)) != 4 or not isinstance(labels, list) or len(labels) != 4
            or any(not isinstance(s, str) or not s or len(s) > 32768 for s in [text] + labels)):
        raise ValueError('問答文字或選項格式無效')
    payload = dict(question=qid, text=text, options=sorted(zip(options, labels)))
    return _digest(payload), payload


def identity(token, role, question):
    if (not isinstance(token, tuple) or len(token) != 2 or token[0] is not True
            or not isinstance(token[1], str) or len(token[1]) != 64
            or any(c not in '0123456789abcdef' for c in token[1])
            or type(role) is not int or role <= 0):
        raise ValueError('問答來源或角色尚未確認')
    digest, payload = fingerprint(question)
    return token[1], _digest(['ark-role-v1', role]), digest, payload


def _answer(question, answer):
    if type(answer) is not int or answer not in question['options']:
        raise ValueError('答案不在當前選項中')


def _metadata(value):
    return (isinstance(value, str) and 0 < len(value) <= 1024
            and value == value.strip()
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


class QuestionStore:
    def __init__(self, path=None):
        self.path = path if path is not None else data_root() / 'ark_questions.sqlite3'

    @contextmanager
    def _connection(self):
        from pathlib import Path
        path = Path(self.path); path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=0.25)
        try:
            with connection:
                # Lock before reading evidence/schema, so competing writers cannot
                # both decide independently that their contradictory answer is new.
                connection.execute('BEGIN IMMEDIATE')
                version = connection.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, 1, 2):
                    raise ValueError('問答題庫版本不支援')
                connection.execute('''CREATE TABLE IF NOT EXISTS questions (
                    catalog TEXT NOT NULL, role TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL, answer INTEGER, conflict INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'observed', updated INTEGER NOT NULL,
                    PRIMARY KEY (catalog, role, fingerprint))''')
                connection.execute('''CREATE TABLE IF NOT EXISTS candidates (
                    catalog TEXT NOT NULL, role TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    answer INTEGER NOT NULL, source TEXT NOT NULL, revision TEXT NOT NULL,
                    rejected INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL,
                    PRIMARY KEY (catalog, role, fingerprint))''')
                connection.execute('''CREATE TABLE IF NOT EXISTS candidate_attempts (
                    catalog TEXT NOT NULL, role TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    answer INTEGER NOT NULL, updated INTEGER NOT NULL,
                    PRIMARY KEY (catalog, role, fingerprint))''')
                if version < 2: connection.execute('PRAGMA user_version=2')
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _observe(db, key, payload):
        db.execute('''INSERT OR IGNORE INTO questions
            (catalog,role,fingerprint,payload,updated) VALUES (?,?,?,?,?)''',
            (*key, json.dumps(payload, ensure_ascii=False), int(time.time())))
        return db.execute('''SELECT answer,conflict,source FROM questions
            WHERE catalog=? AND role=? AND fingerprint=?''', key).fetchone()

    @staticmethod
    def _quarantine(db, key):
        db.execute('''UPDATE questions SET answer=NULL,conflict=1,updated=?
            WHERE catalog=? AND role=? AND fingerprint=?''', (int(time.time()), *key))

    def observe(self, token, role, question):
        *key, payload = identity(token, role, question)
        with self._connection() as db:
            answer, conflict, source = self._observe(db, key, payload)
        if (not conflict and source == 'server_confirmed' and type(answer) is int
                and answer in question['options']):
            return answer, 'confirmed'
        return None, 'conflict' if conflict else 'unknown'

    def record_candidate(self, token, role, question, answer, source, revision):
        """Persist reviewed evidence without promoting it to a server answer."""
        *key, payload = identity(token, role, question)
        _answer(question, answer)
        if not _metadata(source) or source == 'server_confirmed' or not _metadata(revision):
            raise ValueError('候選答案來源或版本格式無效')
        with self._connection() as db:
            old, conflict, old_source = self._observe(db, key, payload)
            candidate = db.execute('''SELECT answer,rejected FROM candidates
                WHERE catalog=? AND role=? AND fingerprint=?''', key).fetchone()
            pending = db.execute('''SELECT answer FROM candidate_attempts
                WHERE catalog=? AND role=? AND fingerprint=?''', key).fetchone()
            conflict = bool(conflict or (candidate and (candidate[0] != answer or candidate[1]))
                            or (pending and pending[0] != answer)
                            or (old_source == 'server_confirmed' and old != answer))
            # Retain the first contradictory candidate as evidence; a matching
            # revision may refresh provenance but can never lift quarantine.
            if candidate is None:
                db.execute('''INSERT INTO candidates
                    (catalog,role,fingerprint,answer,source,revision,updated)
                    VALUES (?,?,?,?,?,?,?)''', (*key, answer, source, revision, int(time.time())))
            elif not conflict:
                db.execute('''UPDATE candidates SET source=?,revision=?,updated=?
                    WHERE catalog=? AND role=? AND fingerprint=?''',
                    (source, revision, int(time.time()), *key))
            if conflict:
                self._quarantine(db, key)
                return 'conflict'
            pending = db.execute('''SELECT 1 FROM candidate_attempts
                WHERE catalog=? AND role=? AND fingerprint=?''', key).fetchone()
            if pending:
                return 'pending'
            return 'confirmed' if old_source == 'server_confirmed' else 'candidate'

    def claim_candidate(self, token, role, question, answer):
        """Claim one reviewed attempt durably; only a server result resolves it."""
        *key, payload = identity(token, role, question)
        _answer(question, answer)
        with self._connection() as db:
            question_row = db.execute('''SELECT conflict FROM questions
                WHERE catalog=? AND role=? AND fingerprint=?''', key).fetchone()
            candidate = db.execute('''SELECT answer,rejected FROM candidates
                WHERE catalog=? AND role=? AND fingerprint=?''', key).fetchone()
            if (question_row is None or question_row[0] or candidate is None
                    or candidate[0] != answer or candidate[1]):
                return False
            result = db.execute('''INSERT OR IGNORE INTO candidate_attempts
                (catalog,role,fingerprint,answer,updated) VALUES (?,?,?,?,?)''',
                (*key, answer, int(time.time())))
            return result.rowcount == 1

    def record_candidate_attempt(self, token, role, question, answer, *, allow_unregistered=False):
        """Persist a matching explicit selection, including an existing claim.

        This is evidence recording, not permission to auto-send. Manual choices
        can be recorded even under quarantine, without clearing any safety flag.
        A caller that independently matched a bundled candidate may explicitly
        allow an unregistered attempt. Existing contradictory evidence is retained
        and quarantined. Database failures propagate before sending.
        """
        *key, payload = identity(token, role, question)
        _answer(question, answer)
        if type(allow_unregistered) is not bool:
            raise ValueError('候選答案追蹤參數格式無效')
        with self._connection() as db:
            candidate = db.execute('''SELECT answer FROM candidates
                WHERE catalog=? AND role=? AND fingerprint=?''', key).fetchone()
            if (candidate is None or candidate[0] != answer) and not allow_unregistered:
                return False
            self._observe(db, key, payload)
            pending = db.execute('''SELECT answer FROM candidate_attempts
                WHERE catalog=? AND role=? AND fingerprint=?''', key).fetchone()
            if ((candidate is not None and candidate[0] != answer)
                    or (pending is not None and pending[0] != answer)):
                self._quarantine(db, key)
            db.execute('''INSERT OR IGNORE INTO candidate_attempts
                (catalog,role,fingerprint,answer,updated) VALUES (?,?,?,?,?)''',
                (*key, answer, int(time.time())))
            return True

    def confirm(self, token, role, question, answer):
        *key, payload = identity(token, role, question)
        _answer(question, answer)
        with self._connection() as db:
            old, conflict, _ = self._observe(db, key, payload)
            candidate = db.execute('''SELECT answer,rejected FROM candidates
                WHERE catalog=? AND role=? AND fingerprint=?''', key).fetchone()
            conflict = bool(conflict or old is not None and old != answer
                            or candidate and (candidate[0] != answer or candidate[1]))
            if conflict:
                self._quarantine(db, key)
            else:
                db.execute('''UPDATE questions SET answer=?,source='server_confirmed',updated=?
                    WHERE catalog=? AND role=? AND fingerprint=?''',
                    (answer, int(time.time()), *key))
                db.execute('''DELETE FROM candidate_attempts
                    WHERE catalog=? AND role=? AND fingerprint=?''', key)
        return 'conflict' if conflict else 'confirmed'

    def quarantine(self, token, role, question):
        *key, payload = identity(token, role, question)
        with self._connection() as db:
            self._observe(db, key, payload)
            self._quarantine(db, key)
        return 'conflict'

    def reject(self, token, role, question, answer, candidate=False):
        *key, payload = identity(token, role, question)
        _answer(question, answer)
        with self._connection() as db:
            if candidate is True:
                self._observe(db, key, payload)
                self._quarantine(db, key)
                db.execute('''DELETE FROM candidate_attempts
                    WHERE catalog=? AND role=? AND fingerprint=?''', key)
                db.execute('''UPDATE candidates SET rejected=1,updated=?
                    WHERE catalog=? AND role=? AND fingerprint=?''', (int(time.time()), *key))
            else:
                db.execute('''UPDATE questions SET answer=NULL,conflict=1,updated=?
                    WHERE catalog=? AND role=? AND fingerprint=? AND answer=?''',
                    (int(time.time()), *key, answer))
