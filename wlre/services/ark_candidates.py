"""Reviewed, unconfirmed astronomy answers bound to exact official content.

The index contains IDs and hashes only. It cannot display an old question or
replace verified runtime resources. A candidate is never a server answer key.
"""
from dataclasses import dataclass
import re
import hashlib
import json

from wlre.storage.ark_questions import fingerprint
from wlre.services import ark_candidate_data as data


@dataclass(frozen=True)
class Decision:
    answer: int | None
    status: str
    reason: str = ''
    source: str = 'reviewed_import'
    revision: str = data.REVIEW_REVISION


def index_digest(questions, quarantined):
    payload=dict(questions=questions,quarantined=quarantined,user_reviewed=data.USER_REVIEWED,source=data.SOURCE_SHA256,
                 data_ver=data.DATA_VER,version=data.PACKAGE_VERSION,
                 manifest=data.MANIFEST_SHA256,text=data.TEXT_SHA256,revision=data.REVIEW_REVISION)
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,
                                     separators=(',',':')).encode('utf-8')).hexdigest()


def index():
    """Validate reviewed code data; callers fail closed on any damaged record."""
    if (not isinstance(data.USER_REVIEWED,dict)
            or any(type(k) is not int or not isinstance(v,str) or not v for k,v in data.USER_REVIEWED.items())
            or not isinstance(data.QUARANTINED,dict)
            or any(type(k) is not int or not isinstance(v,str) or not v for k,v in data.QUARANTINED.items())
            or index_digest(data.QUESTIONS,data.QUARANTINED)!=data.INDEX_SHA256):
        raise ValueError('候選題庫內容校驗失敗，請人工選答')
    result = {}
    expected = set(range(63901, 64001, 5)) | set(range(103505, 104405, 5))
    for qid, answer, options, digest in data.QUESTIONS:
        if (type(qid) is not int or qid in result or qid not in expected
                or not isinstance(options, tuple) or len(options) != 4
                or type(answer) is not int or answer not in options
                or any(type(i) is not int or i <= 0 for i in options)
                or len(set(options)) != 4 or not isinstance(digest, str)
                or re.fullmatch('[0-9a-f]{64}', digest) is None):
            raise ValueError('候選題庫索引無效，請人工選答')
        result[qid] = (answer, options, digest)
    if (set(result) != expected or not set(data.QUARANTINED).issubset(expected)
            or not set(data.USER_REVIEWED).issubset(expected)
            or set(data.USER_REVIEWED) & set(data.QUARANTINED)):
        raise ValueError('候選題庫範圍不完整，請人工選答')
    return result


def resolve(question, identity):
    """Do not reuse a candidate across versions, text changes or option changes."""
    entry = index().get(question.get('question'))
    if entry is None:
        return Decision(None, 'not_covered')
    revisions = [p for p in getattr(identity, 'packages', ())
                 if getattr(p, 'name', None) == 'DataPackage']
    if (getattr(identity, 'data_ver', None) != data.DATA_VER or len(revisions) != 1
            or getattr(revisions[0], 'full_version', None) != data.PACKAGE_VERSION
            or getattr(revisions[0], 'manifest_sha256', None) != data.MANIFEST_SHA256):
        return Decision(None, 'version_mismatch', '候選庫尚未審核此官方資料版本')
    answer, options, digest = entry
    actual, _ = fingerprint(question)
    if tuple(sorted(question['options'])) != options or actual != digest:
        return Decision(None, 'changed', '題目或完整選項內容與審核版本不符')
    reason = data.QUARANTINED.get(question['question'])
    if question['question'] in data.QUARANTINED:
        return Decision(None, 'quarantined', reason)
    if question['question'] in data.USER_REVIEWED:
        return Decision(answer, 'candidate', data.USER_REVIEWED[question['question']], source='user_reviewed')
    return Decision(answer, 'candidate', '人工審核候選，尚未經伺服器確認，仍可能答錯')
