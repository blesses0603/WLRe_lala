"""Execute retained ark_candidates.py on synthetic inputs; never load official text or connect.

Also copy the retained, text-free reviewed data into C#. Data fingerprints are untouched.
Source-file fingerprints normalize CRLF bytes ONLY so Windows checkouts verify identically.
"""
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import itertools
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'dotnet/Lala.Core.Tests/TestSupport'))
from gzip_json_fixture import gzip_json_bytes
from wlre.services import ark_candidate_data as data
from wlre.services import ark_candidates as source
from wlre.storage.ark_questions import fingerprint

FIELDS = ('DATA_VER', 'PACKAGE_VERSION', 'MANIFEST_SHA256', 'TEXT_SHA256', 'SOURCE_SHA256',
          'REVIEW_REVISION', 'INDEX_SHA256', 'QUESTIONS', 'QUARANTINED', 'USER_REVIEWED')
ORIGINAL = {name: getattr(data, name) for name in FIELDS}


def invoke(values, function):
    with ExitStack() as stack:
        for name, value in values.items():
            stack.enter_context(patch.object(data, name, value))
        return function()


def rehash(values):
    values = dict(values)
    values['INDEX_SHA256'] = invoke(values, lambda: source.index_digest(values['QUESTIONS'], values['QUARANTINED']))
    return values


def question(qid):
    row = source.index()[qid]
    return dict(question=qid, text='離線測試題' + str(qid), options=list(row[1]),
                labels=['測試甲', '測試乙', '測試丙', '測試丁'])


def identity(**changes):
    result = dict(data_ver=data.DATA_VER, packages=[dict(name='DataPackage', full_version=data.PACKAGE_VERSION,
                                                       manifest_sha256=data.MANIFEST_SHA256)])
    result.update(changes)
    return result


def as_identity(value):
    if value is None:
        return None
    result = dict(value)
    if 'packages' in result:
        result['packages'] = [SimpleNamespace(**p) if p is not None else None for p in result['packages']]
    return SimpleNamespace(**result)


# All production 200 records, source/review digests and 16 user decisions are retained.
source.index()
synthetic = rehash({**ORIGINAL, 'QUESTIONS': tuple((qid, answer, options, fingerprint(question(qid))[0])
                                               for qid, answer, options, _ in data.QUESTIONS)})
quarantine = rehash({**synthetic, 'QUARANTINED': {63901: '離線隔離原因'}, 'USER_REVIEWED': {}})
unsorted = rehash({**synthetic, 'QUESTIONS': ((63901, 63902, (63903, 63902, 63904, 63905),
                                            synthetic['QUESTIONS'][0][3]),) + synthetic['QUESTIONS'][1:]})
indices = dict(reviewed=ORIGINAL, synthetic=synthetic, quarantine=quarantine, unsorted=unsorted,
               changed_revision=rehash({**synthetic, 'REVIEW_REVISION': 'synthetic-later-revision'}))
cases = []


def resolve_case(name, q=None, version=None, index='synthetic', default_version=True):
    q = question(63901) if q is None else q
    version = identity() if version is None and default_version else version
    try:
        expected = invoke(indices[index], lambda: asdict(source.resolve(q, as_identity(version))))
        error = None
    except (ValueError, UnicodeEncodeError) as exc:
        expected, error = None, type(exc).__name__
    cases.append(dict(name=name, index=index, question=q, identity=version, expected=expected, error=error))


for qid in source.index():
    q = question(qid)
    for order in itertools.permutations(range(4)):
        resolve_case(f'{qid}-' + ''.join(map(str, order)),
                     {**q, 'options': [q['options'][i] for i in order], 'labels': [q['labels'][i] for i in order]})
q = question(63901)
for name, change in [('text-space', dict(text=q['text'] + ' ')), ('text-case', dict(text='OFFLINE')),
                     ('labels-reversed', dict(labels=list(reversed(q['labels'])))),
                     ('changed-label', dict(labels=['不同', *q['labels'][1:]])),
                     ('changed-id', dict(options=[1, *q['options'][1:]])),
                     ('reordered-ids-not-labels', dict(options=list(reversed(q['options'])))),
                     ('unknown-id', dict(question=123)), ('zero-id-uncovered', dict(question=0)),
                     ('duplicate-options', dict(options=[1, 1, 2, 3])), ('zero-option', dict(options=[0, 2, 3, 4])),
                     ('short-options', dict(options=[1, 2, 3])), ('empty-options', dict(options=[])),
                     ('missing-options', dict(options=None)), ('empty-text', dict(text='')),
                     ('missing-text', dict(text=None)), ('empty-label', dict(labels=['', 'a', 'b', 'c'])),
                     ('missing-label', dict(labels=[None, 'a', 'b', 'c'])), ('missing-labels', dict(labels=None)),
                     ('short-labels', dict(labels=['a', 'b', 'c'])), ('oversize-text', dict(text='x' * 32769)),
                     ('oversize-label', dict(labels=['x' * 32769, 'a', 'b', 'c']))]:
    resolve_case(name, {**q, **change})
    if name in ('duplicate-options', 'missing-text', 'missing-options'):
        resolve_case(name + '-version-first', {**q, **change}, identity(data_ver='other'))
        resolve_case(name + '-coverage-first', {**q, **change, 'question': 123}, None, default_version=False)
for name, version in [('none', None), ('empty', {}), ('no-packages', dict(data_ver=data.DATA_VER)),
                      ('wrong-data', identity(data_ver='other')), ('duplicate-package', identity(packages=identity()['packages'] * 2)),
                      ('empty-packages', identity(packages=[])), ('null-package', identity(packages=[None])),
                      ('extra-package', identity(packages=[dict(name='MainPackage'), *identity()['packages']])),
                      ('two-other-packages', identity(packages=[dict(name='MainPackage'), dict(name='MainPackage'), *identity()['packages']]))]:
    resolve_case('version-' + name, q, version, default_version=False)
for field in ('name', 'full_version', 'manifest_sha256'):
    for change in (None, '', 'wrong', identity()['packages'][0][field].upper()):
        package = {**identity()['packages'][0], field: change}
        resolve_case('version-field-' + field + '-' + str(change), q, identity(packages=[package]))
resolve_case('reviewed-real-data-does-not-match-synthetic', q, index='reviewed')
resolve_case('decision-revision-captured-at-import', q, index='changed_revision')
resolve_case('quarantined', q, index='quarantine')
resolve_case('quarantine-content-first', {**q, 'text': 'other'}, index='quarantine')
resolve_case('quarantine-version-first', q, identity(data_ver='other'), index='quarantine')
resolve_case('unsorted-index-options-never-match', q, index='unsorted')
resolve_case('irrelevant-evidence-ignored', {**q, 'known_answer': 63903, 'answer_source': 'server_confirmed',
                                            'selected': 2, 'award': [1, 2, 3], 'selected_candidate': True})

# Adversarial exact Unicode, controls, maximum lengths; all use retained fingerprint().
for number, text in enumerate(['e\u0301', 'é', '😀𐀀\u2028\u2029', '<>&+ / \\" \b\f\n\r\t\0\x1f\x7f',
                               '😀' * 32768, '\0' * 32768]):
    altered = {**q, 'text': text, 'labels': [text] * 4}
    name = 'content-' + str(number)
    indices[name] = rehash({**synthetic, 'QUESTIONS': ((63901, 63902, tuple(q['options']), fingerprint(altered)[0]),)
                                                   + synthetic['QUESTIONS'][1:]})
    resolve_case(name, altered, index=name)
    if number < 4:
        resolve_case(name + '-changed', {**altered, 'text': text + ' '}, index=name)

index_cases = []

def index_case(name, changes, recalculate=True):
    values = {**ORIGINAL, **changes}
    if recalculate:
        values = rehash(values)
    try:
        actual = invoke(values, source.index)
        expected, error = len(actual), None
    except ValueError as exc:
        expected, error = None, str(exc)
    index_cases.append(dict(name=name, data=values, expected_count=expected, error=error))

first = ORIGINAL['QUESTIONS'][0]
rest = ORIGINAL['QUESTIONS'][1:]
for name, rows in [('missing-row', ORIGINAL['QUESTIONS'][:-1]), ('duplicate-row', ORIGINAL['QUESTIONS'] + (first,)),
                   ('out-of-range', ((123, *first[1:]),) + rest), ('answer-not-option', ((first[0], 999, *first[2:]),) + rest),
                   ('short-options', ((first[0], first[1], first[2][:-1], first[3]),) + rest),
                   ('duplicate-options', ((first[0], first[1], (first[1],) * 4, first[3]),) + rest),
                   ('zero-option', ((first[0], first[1], (first[1], 0, 2, 3), first[3]),) + rest),
                   ('uppercase-digest', ((*first[:3], first[3].upper()),) + rest),
                   ('short-digest', ((*first[:3], first[3][:-1]),) + rest),
                   ('newline-digest', ((*first[:3], first[3] + '\n'),) + rest),
                   ('nonhex-digest', ((*first[:3], 'g' * 64),) + rest)]:
    index_case(name, dict(QUESTIONS=rows))
    index_case(name + '-stale-digest', dict(QUESTIONS=rows), False)
for annotation in ('QUARANTINED', 'USER_REVIEWED'):
    for name, values in [('empty-reason', {63901: ''}), ('null-reason', {63901: None}),
                         ('outside-range', {123: 'reason'}), ('numeric-sort', {103505: '後', 63901: '前'}),
                         ('unicode-reason', {63901: '<>&+ 😀\n\r\t\0\x1f'})]:
        changes = {annotation: values}
        if annotation == 'QUARANTINED':
            changes['USER_REVIEWED'] = {}
        index_case(annotation + '-' + name, changes)
index_case('overlap', dict(QUARANTINED={63906: 'blocked'}))
index_case('quarantined-only', dict(QUARANTINED={63901: 'blocked'}))
index_case('index-digest-tampered', dict(INDEX_SHA256='0' * 64), False)
for field in FIELDS[:6]:
    index_case('metadata-tampered-' + field, {field: ORIGINAL[field] + 'x'}, False)
# Reversing data order changes the digest but remains valid once rehashed.
index_case('reverse-data-order', dict(QUESTIONS=tuple(reversed(ORIGINAL['QUESTIONS']))))

# Production C# includes IDs/hashes/annotation reasons only, not the synthetic text.
quote = lambda value: json.dumps(value, ensure_ascii=False)
rows = '\n'.join(f'            new({qid}u, {answer}u, [{", ".join(str(v)+"u" for v in options)}], {quote(digest)}),'
                 for qid, answer, options, digest in ORIGINAL['QUESTIONS'])
def annotations(value):
    return 'ImmutableDictionary<uint, string>.Empty' + ''.join(f'.Add({qid}u, {quote(reason)})' for qid, reason in sorted(value.items()))
constants = ',\n        '.join(quote(ORIGINAL[field]) for field in FIELDS[:7])
(ROOT / 'dotnet/Lala.Core/Social/Ark/ArkCandidateData.cs').write_text('''// Generated by generate_ark_candidate_vectors.py from retained ark_candidate_data.py.
// No official question text or legacy resources. All 200 answers remain UNCONFIRMED.
using System.Collections.Immutable;
namespace Lala.Core.Social.Ark;
internal sealed partial record ArkCandidateData
{
    internal static ArkCandidateData BuiltIn { get; } = new(
        %s,
        [
%s
        ],
        %s,
        %s);
}
''' % (constants, rows, annotations(ORIGINAL['QUARANTINED']), annotations(ORIGINAL['USER_REVIEWED'])), encoding='utf-8', newline='\n')

sources = ['wlre/services/ark_candidates.py', 'wlre/services/ark_candidate_data.py', 'wlre/storage/ark_questions.py',
           'tests/test_ark_candidates.py', str(Path(__file__).relative_to(ROOT))]
source_hashes = {path: hashlib.sha256((ROOT / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for path in sources}
payload = json.dumps(dict(source_sha256=source_hashes, indices=indices, cases=cases, index_cases=index_cases),
                     ensure_ascii=False, separators=(',', ':'))
compressed = gzip_json_bytes(payload)
(HERE / 'Fixtures/ark-reviewed-candidates.json.gz').write_bytes(compressed)
(HERE / 'ArkCandidatePythonVectors.cs').write_text('''// Generated by generate_ark_candidate_vectors.py; actual retained Python, synthetic question text only.
namespace Lala.Core.Tests.Social.Ark.Candidates;
internal static class ArkCandidatePythonVectors
{
    internal static string Json => TestSupport.GzipJson.DecodeResource(
        "Lala.Core.Tests.Social.Ark.Candidates.Fixtures.ark-reviewed-candidates.json.gz",
        "%s", "%s");
}
''' % (hashlib.sha256(compressed).hexdigest(), hashlib.sha256(payload.encode()).hexdigest()), encoding='utf-8', newline='\n')
print(f'{len(cases)} resolution cases; {len(index_cases)} index cases; {len(payload.encode())} decoded bytes; {len(compressed)} compressed bytes')
