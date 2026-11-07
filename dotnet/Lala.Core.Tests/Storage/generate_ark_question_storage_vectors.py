"""Deterministic differential scenarios executed against retained Python, synthetic temp DBs only."""
from pathlib import Path
import hashlib
import base64
import json
import random
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'TestSupport'))
from gzip_json_fixture import gzip_json_bytes
from wlre.storage import ark_questions as source

source.time.time = lambda: 12345
TOKEN = (True, 'a' * 64)
QUESTION = dict(question=20, text='題目', options=[21, 22, 23, 24], labels=['甲', '乙', '丙', '丁'])


def snapshot(path):
    with sqlite3.connect(path) as db:
        result = {}
        for table in ('questions', 'candidates', 'candidate_attempts'):
            rows = [list(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY catalog,role,fingerprint')]
            if table == 'questions':
                for row in rows:
                    row[3] = json.loads(row[3])
            result[table] = rows
        result['version'] = db.execute('PRAGMA user_version').fetchone()[0]
        return result


def run_scenario(index, operations):
    with tempfile.TemporaryDirectory(prefix='ark-parity-') as directory:
        path = Path(directory) / 'synthetic.sqlite3'
        output = []
        for operation in operations:
            name, answer, candidate = operation[:3]
            role = operation[3] if len(operation) > 3 else 1
            question = operation[4] if len(operation) > 4 else QUESTION
            catalog = operation[5] if len(operation) > 5 else TOKEN[1]
            store = source.QuestionStore(path)  # Reopen each operation, never a user DB/default path.
            args = ((True, catalog), role, question)
            if name in ('observe', 'quarantine'):
                result = getattr(store, name)(*args)
            elif name == 'record_candidate':
                result = store.record_candidate(*args, answer, 'reviewed-local', 'r1')
            elif name == 'record_candidate_attempt':
                result = store.record_candidate_attempt(*args, answer, allow_unregistered=candidate)
            elif name == 'reject':
                result = store.reject(*args, answer, candidate=candidate)
            else:
                result = getattr(store, name)(*args, answer)
            output.append(dict(operation=name, answer=answer, flag=candidate, role=str(role),
                               question=question, catalog=catalog, result=result, state=snapshot(path)))
        return dict(name=f'scenario-{index:03}', steps=output)


short = lambda name, answer=22, flag=False: (name, answer, flag)
scenarios = []
fixed = [
    [short('observe')],
    [short('confirm'), short('observe'), short('confirm', 23), short('confirm'), short('observe')],
    [short('record_candidate'), short('observe'), short('claim_candidate'), short('claim_candidate'), short('record_candidate'), short('confirm'), short('record_candidate')],
    [short('record_candidate'), short('reject', 21), short('record_candidate'), short('reject', 22, True), short('record_candidate_attempt'), short('confirm'), short('observe')],
    [short('record_candidate_attempt', 23, True), short('confirm'), short('observe')],
    [short('record_candidate_attempt', 23, True), short('record_candidate'), short('confirm'), short('observe')],
    [short('record_candidate'), short('claim_candidate'), short('record_candidate_attempt', 23, True), short('record_candidate'), short('confirm')],
]
for version in range(2):
    q = {**QUESTION, 'options': [24, 21, 23, 22], 'labels': ['丁', '甲', '丙', '乙']}
    fixed.append([short('confirm'), ('observe', 22, False, 1, q), ('observe', 22, False, 2),
                  ('observe', 22, False, 1, {**QUESTION, 'text': '另一題'}),
                  ('observe', 22, False, 1, QUESTION, 'b' * 64)])
for first in ('confirm', 'record_candidate', 'quarantine', 'record_candidate_attempt'):
    for second in ('confirm', 'record_candidate', 'reject', 'claim_candidate', 'record_candidate_attempt'):
        for answer in (22, 23):
            fixed.append([short(first, 22, True), short(second, answer, True), short('record_candidate'), short('observe')])
for operations in fixed:
    scenarios.append(run_scenario(len(scenarios), operations))
rng = random.Random(0xA7C2)
for index in range(100):
    operations = [short(rng.choice(('observe', 'confirm', 'record_candidate', 'claim_candidate',
                                   'record_candidate_attempt', 'reject', 'quarantine')), rng.choice((21, 22, 23, 24)), bool(rng.getrandbits(1)))
                  for _ in range(12)]
    scenarios.append(run_scenario(len(scenarios), operations))

identities = []
texts = ['題目', 'e\u0301', 'é', '\" \\ / \b \f \n \r \t \x00 \x1f \x7f', '😀𐀀\u2028\u2029\u0085', ' <>&+\ufeff ']
for index in range(100):
    ids = rng.sample(range(1, 2**32), 4)
    question = dict(question=rng.randrange(1, 2**32), text=texts[index % len(texts)], options=ids,
                    labels=[f'{texts[(index + n) % len(texts)]}{n}' for n in range(4)])
    role = rng.choice((1, 2**32, 2**128, 10**100, 2**256 + 123))
    catalog, role_hash, fingerprint, payload = source.identity(TOKEN, role, question)
    identities.append(dict(role=str(role), question=question, catalog=catalog, roleHash=role_hash,
                           fingerprint=fingerprint, payload=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))))

# Boundary identities are generated by Python too, not merely round-tripped in C#.
for scalar in ('😀', '\x00'):
    for role in (1, 10**4299):
        question = dict(question=2**32 - 1, text=scalar * 32768,
                        options=[21, 22, 23, 24], labels=[scalar * 32768] * 4)
        catalog, role_hash, fingerprint, payload_value = source.identity(TOKEN, role, question)
        identities.append(dict(role=str(role), question=question, catalog=catalog, roleHash=role_hash,
                               fingerprint=fingerprint, payload=json.dumps(payload_value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))))

legacy_databases = []
for version in (0, 1, 2):
    with tempfile.TemporaryDirectory(prefix='ark-legacy-parity-') as directory:
        path = Path(directory) / 'synthetic.sqlite3'
        store = source.QuestionStore(path)
        store.confirm(TOKEN, 2**100, QUESTION, 22)
        store.record_candidate(TOKEN, 2**100, QUESTION, 22, 'reviewed-local', 'r1')
        store.claim_candidate(TOKEN, 2**100, QUESTION, 22)
        with sqlite3.connect(path) as db:
            if version < 2:
                db.execute('DROP TABLE candidates')
            db.execute('DROP TABLE candidate_attempts')
            db.execute(f'PRAGMA user_version={version}')
            db.commit()
        legacy_databases.append(dict(version=version, role=str(2**100), bytes=base64.b64encode(path.read_bytes()).decode()))

payload = json.dumps(dict(legacyDatabases=legacy_databases, sourceSha256=hashlib.sha256((ROOT / 'wlre/storage/ark_questions.py').read_bytes()).hexdigest(),
                         identities=identities, scenarios=scenarios), ensure_ascii=False, separators=(',', ':'))
compressed = gzip_json_bytes(payload)
fixtures = Path(__file__).parent / 'Fixtures'
fixtures.mkdir(exist_ok=True)
(fixtures / 'ark-question-storage.json.gz').write_bytes(compressed)
(Path(__file__).parent / 'ArkQuestionStorageVectors.cs').write_text('''// Generated by generate_ark_question_storage_vectors.py; retained Python executed on synthetic temporary DBs.
namespace Lala.Core.Tests.Storage;
internal static class ArkQuestionStorageVectors
{
    internal static string Json => TestSupport.GzipJson.DecodeResource(
        "Lala.Core.Tests.Storage.Fixtures.ark-question-storage.json.gz",
        "%s",
        "%s");
}
''' % (hashlib.sha256(compressed).hexdigest(), hashlib.sha256(payload.encode()).hexdigest()))
print(f'{len(identities)} identities; {len(scenarios)} scenarios; {sum(len(s["steps"]) for s in scenarios)} operations; {len(compressed)} compressed bytes')
