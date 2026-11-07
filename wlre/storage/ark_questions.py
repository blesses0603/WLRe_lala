"""Private, version-scoped Ark questions learned only from server results.

Option order is excluded from identity; IDs AND exact texts are included.
Conflicting confirmations are quarantined permanently instead of last-write wins.
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


def identity(token, role, question):
    if (not isinstance(token, tuple) or len(token) != 2 or token[0] is not True
            or not isinstance(token[1], str) or len(token[1]) != 64
            or any(c not in '0123456789abcdef' for c in token[1])
            or type(role) is not int or role <= 0):
        raise ValueError('問答來源或角色尚未確認')
    qid = question['question']; options = question['options']
    text = question['text']; labels = question['labels']
    if (type(qid) is not int or not 0 < qid <= 0xffffffff
            or not isinstance(options, list) or len(options) != 4
            or any(type(i) is not int or not 0 < i <= 0xffffffff for i in options)
            or len(set(options)) != 4 or not isinstance(labels, list) or len(labels) != 4
            or any(not isinstance(s, str) or not s or len(s) > 32768 for s in [text] + labels)):
        raise ValueError('問答文字或選項格式無效')
    payload = dict(question=qid, text=text, options=sorted(zip(options, labels)))
    return token[1], _digest(['ark-role-v1', role]), _digest(payload), payload


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
                version = connection.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, 1):
                    raise ValueError('問答題庫版本不支援')
                connection.execute('''CREATE TABLE IF NOT EXISTS questions (
                    catalog TEXT NOT NULL, role TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL, answer INTEGER, conflict INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'observed', updated INTEGER NOT NULL,
                    PRIMARY KEY (catalog, role, fingerprint))''')
                if version == 0: connection.execute('PRAGMA user_version=1')
                yield connection
        finally:
            connection.close()

    def observe(self, token, role, question):
        catalog, scope, fingerprint, payload = identity(token, role, question)
        with self._connection() as db:
            db.execute('''INSERT OR IGNORE INTO questions
                (catalog,role,fingerprint,payload,updated) VALUES (?,?,?,?,?)''',
                (catalog, scope, fingerprint, json.dumps(payload, ensure_ascii=False), int(time.time())))
            answer, conflict, source = db.execute('''SELECT answer,conflict,source FROM questions
                WHERE catalog=? AND role=? AND fingerprint=?''', (catalog, scope, fingerprint)).fetchone()
        if (not conflict and source == 'server_confirmed' and type(answer) is int
                and answer in question['options']):
            return answer, 'confirmed'
        return None, 'conflict' if conflict else 'unknown'

    def confirm(self, token, role, question, answer):
        if type(answer) is not int or answer not in question['options']:
            raise ValueError('確認答案不在當前選項中')
        catalog, scope, fingerprint, payload = identity(token, role, question)
        with self._connection() as db:
            db.execute('''INSERT OR IGNORE INTO questions
                (catalog,role,fingerprint,payload,updated) VALUES (?,?,?,?,?)''',
                (catalog, scope, fingerprint, json.dumps(payload, ensure_ascii=False), int(time.time())))
            old, conflict = db.execute('''SELECT answer,conflict FROM questions
                WHERE catalog=? AND role=? AND fingerprint=?''', (catalog, scope, fingerprint)).fetchone()
            conflict = bool(conflict or old is not None and old != answer)
            db.execute('''UPDATE questions SET answer=?,conflict=?,source=?,updated=?
                WHERE catalog=? AND role=? AND fingerprint=?''',
                (None if conflict else answer, int(conflict), 'server_confirmed', int(time.time()),
                 catalog, scope, fingerprint))
        return 'conflict' if conflict else 'confirmed'

    def reject(self, token, role, question, answer, candidate=False):
        if type(answer) is not int or answer not in question['options']:
            raise ValueError('拒絕答案不在當前選項中')
        catalog, scope, fingerprint, _ = identity(token, role, question)
        with self._connection() as db:
            db.execute('''UPDATE questions SET answer=NULL,conflict=1,updated=?
                WHERE catalog=? AND role=? AND fingerprint=? AND (answer=? OR ?)''',
                (int(time.time()), catalog, scope, fingerprint, answer, int(candidate is True)))
