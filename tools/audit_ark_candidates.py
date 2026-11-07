"""Read-only audit of private input against the reviewed, text-free Ark index.

Usage: python -m tools.audit_ark_candidates REPORT.md TextData_C
No input is copied into the repository or sent to a service.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from wlre.services import ark_candidate_data as data
from wlre.services.ark_candidates import index
from wlre.services.expedition.data import parse_text_data
from wlre.storage.ark_questions import fingerprint


def audit(report_bytes, text_bytes):
    if (len(report_bytes) > 2 * 1024 * 1024
            or hashlib.sha256(report_bytes).hexdigest() != data.SOURCE_SHA256):
        raise ValueError('附件與已審核來源不同，須重新審核')
    if (len(text_bytes) > 4 * 1024 * 1024
            or hashlib.sha256(text_bytes).hexdigest() != data.TEXT_SHA256):
        raise ValueError('官方文字表與已核對1296來源不同，須重新審核')
    texts = parse_text_data(text_bytes)
    expected = index(); found = set()
    pattern = r'^### 星舟 (\d+)｜(\d+)\n(.*?)(?=^#{2,3} |\Z)'
    for match in re.finditer(pattern, report_bytes.decode('utf-8'), re.M | re.S):
        _, qid, body = match.groups(); qid = int(qid)
        if qid in found or qid not in expected:
            raise ValueError('題目ID重複或不在已審核範圍')
        found.add(qid)
        question = body.strip().split('\n\n')[0]
        options = [(int(m[1]), m[2]) for m in re.finditer(
            r'^\| ([0-9]+) \| (.*?) \|$', body, re.M)]
        answers = re.findall(r'^正確答案：(.*?)（選項文字 ID：([0-9]+)；', body, re.M)
        if len(options) != 4 or len(answers) != 1:
            raise ValueError('題目選項或候選答案數量無效')
        label, answer = answers[0]; answer = int(answer)
        if dict(options).get(answer) != label:
            raise ValueError('候選答案ID與文字不一致')
        if texts.get(qid) != question or any(texts.get(i) != t for i, t in options):
            raise ValueError('附件題目或選項與官方文字不符')
        q = dict(question=qid, text=question, options=[i for i, _ in options],
                 labels=[t for _, t in options])
        digest, _ = fingerprint(q)
        if expected[qid] != (answer, tuple(sorted(q['options'])), digest):
            raise ValueError('候選索引與審核來源不符')
    if found != set(expected):
        raise ValueError('附件未完整包含200題')
    return dict(questions=len(found), exact_official_text_matches=len(found)*5,
                candidates=len(found)-len(data.QUARANTINED),
                quarantined=len(data.QUARANTINED), user_reviewed=len(data.USER_REVIEWED),
                package_version=data.PACKAGE_VERSION, review_revision=data.REVIEW_REVISION,
                source_sha256=data.SOURCE_SHA256, text_sha256=data.TEXT_SHA256,
                server_confirmed=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('official_text', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.report.read_bytes(), args.official_text.read_bytes()),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
