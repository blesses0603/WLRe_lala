"""Synthetic content only; official text remains a verified runtime input."""
import itertools
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wlre.services import ark_candidate_data as data
from wlre.services.ark_candidates import index, resolve, index_digest
from wlre.storage.ark_questions import fingerprint


def revision(**changes):
    package = SimpleNamespace(name='DataPackage', full_version=data.PACKAGE_VERSION,
                              manifest_sha256=data.MANIFEST_SHA256)
    result = SimpleNamespace(data_ver=data.DATA_VER, packages=[package])
    for k, v in changes.items(): setattr(package, k, v)
    return result


def synthetic(qid=63901):
    row = index()[qid]
    return dict(question=qid, text='離線測試題'+str(qid), options=list(row[1]),
                labels=['測試甲','測試乙','測試丙','測試丁'])


def synthetic_entries():
    return tuple((qid, answer, options, fingerprint(synthetic(qid))[0])
                 for qid, answer, options, _ in data.QUESTIONS)


class CandidateTests(unittest.TestCase):
    def test_real_index_has_200_ids_200_candidates_and_no_static_quarantines(self):
        self.assertEqual(len(index()),200)
        self.assertEqual(len(data.QUARANTINED),0)
        self.assertEqual(len(index())-len(data.QUARANTINED),200)
        self.assertEqual(len(data.REVIEW_REVISION),64)
        self.assertEqual(len(data.USER_REVIEWED),16)

    def test_all_synthetic_records_and_all_24_option_permutations(self):
        questions=[synthetic(qid) for qid in index()]
        entries=synthetic_entries()
        with patch.object(data,'QUESTIONS',entries), patch.object(data,'INDEX_SHA256',index_digest(entries,data.QUARANTINED)):
            for question in questions:
                for order in itertools.permutations(range(4)):
                    q={**question,'options':[question['options'][i] for i in order],
                       'labels':[question['labels'][i] for i in order]}
                    result=resolve(q,revision())
                    expected='quarantined' if q['question'] in data.QUARANTINED else 'candidate'
                    self.assertEqual(result.status,expected)
                    if q['question'] in data.USER_REVIEWED:
                        self.assertEqual(result.source,'user_reviewed')
                    self.assertEqual(result.answer,None if expected=='quarantined' else index()[q['question']][0])

    def test_id_text_and_option_changes_never_reuse(self):
        q=synthetic();entries=synthetic_entries()
        with patch.object(data,'QUESTIONS',entries), patch.object(data,'INDEX_SHA256',index_digest(entries,data.QUARANTINED)):
            for change in [dict(text=q['text']+' '),dict(labels=['不同',*q['labels'][1:]]),
                           dict(options=[1,*q['options'][1:]]),dict(labels=list(reversed(q['labels'])))]:
                self.assertEqual(resolve({**q,**change},revision()).status,'changed')
            self.assertEqual(resolve({**q,'question':123},revision()).status,'not_covered')
            with self.assertRaises(ValueError):resolve({**q,'options':[1,1,2,3]},revision())

    def test_exact_version_and_manifest_required(self):
        q=synthetic();entries=synthetic_entries()
        with patch.object(data,'QUESTIONS',entries), patch.object(data,'INDEX_SHA256',index_digest(entries,data.QUARANTINED)):
            for identity in [None,SimpleNamespace(),revision(full_version='1297_new'),
                             revision(manifest_sha256='0'*64),revision(name='MainPackage'),
                             SimpleNamespace(data_ver='other',packages=revision().packages),
                             SimpleNamespace(data_ver=data.DATA_VER,packages=revision().packages*2)]:
                result=resolve(q,identity)
                self.assertIsNone(result.answer)
                self.assertEqual(result.status,'version_mismatch')

    def test_bad_index_rejected_instead_of_partial_use(self):
        first=data.QUESTIONS[0]
        for entries in [data.QUESTIONS[:-1],data.QUESTIONS+(first,),
                        ((first[0],999,first[2],first[3]),)+data.QUESTIONS[1:],
                        ((first[0],first[1],first[2],'bad'),)+data.QUESTIONS[1:]]:
            with patch.object(data,'QUESTIONS',entries),self.assertRaises(ValueError):index()

    def test_audit_tool_rejects_changed_private_inputs(self):
        from tools.audit_ark_candidates import audit
        with self.assertRaises(ValueError):audit(b'not the reviewed attachment',b'')


if __name__=='__main__':unittest.main()
