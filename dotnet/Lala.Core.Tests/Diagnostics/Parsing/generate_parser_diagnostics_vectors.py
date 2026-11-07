"""Synthetic-only oracle for the bounded in-memory diagnostics port. No account/resource files."""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'dotnet/Lala.Core.Tests/TestSupport'))
from gzip_json_fixture import gzip_json_bytes
SOURCE = 'wlre/services/parser_diagnostics.py'
spec = importlib.util.spec_from_file_location('parser_diagnostics_oracle', ROOT / SOURCE)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
FIXED = datetime(2026, 11, 7, 1, 2, 3, tzinfo=timezone.utc)
class Clock:
    @staticmethod
    def now(_): return FIXED

def dump(value): return json.dumps(value, ensure_ascii=True, sort_keys=True).encode()
def b64(raw): return base64.b64encode(raw).decode()
def digest(raw): return {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
def baseline(**changes):
    return {'schema': 'schema-v1', 'selected_schema': 'profile-v1', 'inputs': {'raw': digest(b'synthetic')},
            'record_count': 2, 'identity': None, **changes}
def event(i=0, failed=False, **changes):
    row = {'parser': 'synthetic.parse_' + str(i), 'schema': 'schema-v1', 'status': 'failed' if failed else 'passed',
           'inputs': {'raw': digest(('synthetic-' + str(i)).encode())}}
    row.update({'error_type': 'ValueError', 'location': {}} if failed else {'record_count': 2, 'selected_schema': 'profile-v1'})
    row.update(changes)
    return row

vectors = []
def add(kind, name, data, expected): vectors.append({'kind': kind, 'name': name, 'data': data, 'expected': expected})

values = [None, True, False, -1, 0, 1, 2**31, 2**31+1, 2**63-1, 2**63, 1.0, '1', [], {}, 'secret/unsafe', '秘密']
for field in ('schema', 'selected_schema', 'record_count', 'identity', 'inputs'):
    for i, value in enumerate(values):
        row = baseline(**{field: value})
        add('baseline', f'{field}-{i}', row, p._valid_baseline(row))
for field in ('schema', 'selected_schema'):
    for i, value in enumerate(['a'*80, 'a'*81, '', 'a_b', 'a-b.1', 'x\n', 'é', '/', '000']):
        row = baseline(**{field: value}); add('baseline', f'{field}-labels-{i}', row, p._valid_baseline(row))
for count in (0, 1, 16, 17):
    row = baseline(inputs={f'raw_{i}': digest(bytes([i])) for i in range(count)})
    add('baseline', f'input-count-{count}', row, p._valid_baseline(row))
for i, name in enumerate(['raw', '_raw', 'A0', 'a'*64, 'a'*65, '0raw', 'raw.name', '', 'é', 'x\n']):
    row = baseline(inputs={name: digest(b'x')}); add('baseline', f'input-name-{i}', row, p._valid_baseline(row))
for field in ('size', 'sha256'):
    for i, value in enumerate(values + ['a'*64, 'A'*64, '0'*63, '0'*65]):
        row = baseline(inputs={'raw': {**digest(b'x'), field: value}})
        add('baseline', f'digest-{field}-{i}', row, p._valid_baseline(row))
for i, row in enumerate([baseline(extra='secret'), {k:v for k,v in baseline().items() if k != 'identity'},
                         baseline(identity='a'*64), baseline(inputs={'raw': {'size': 0, 'sha256': '0'*64, 'extra': 'secret'}})]):
    add('baseline', f'shape-{i}', row, p._valid_baseline(row))

for field in ('offset', 'record', 'expected', 'actual', 'expected_max', 'profile', 'field', 'constraint'):
    for i, value in enumerate(values + ['a'*64, 'a'*65, 'a-b', 'a_b', '--', '__', 'UPPER', 'lower_1']):
        initial = {'offset': 7, 'field': 'old', 'profile': 'old-v1', 'constraint': 'old'}
        token = p._cursor.set(dict(initial))
        try:
            p.checkpoint(**{field: value})
            add('checkpoint', f'{field}-{i}', {'initial': initial, 'changes': {field: value}}, dict(p._cursor.get()))
        finally: p._cursor.reset(token)
for i, (offset, size, available) in enumerate([(0,0,0), (-1,-1,-1), (2**63,2**80,2**90), (True,False,True), (1.0,2.0,3.0)]):
    token = p._cursor.set({'offset': 3, 'requested_bytes': 4})
    try:
        p.read_checkpoint(offset, size, available)
        add('read', f'read-{i}', {'initial': {'offset':3, 'requested_bytes':4}, 'offset':offset, 'size':size, 'available':available}, dict(p._cursor.get()))
    finally: p._cursor.reset(token)

def decode(value):
    if isinstance(value, dict):
        if '$tuple' in value: return tuple(decode(x) for x in value['$tuple'])
        if '$float' in value: return float(value['$float'])
        return {k:decode(v) for k,v in value.items()}
    if isinstance(value, list): return [decode(x) for x in value]
    return value
counts = [None, True, 9, 'secret', [], [1,2], {'$tuple': []}, {'$tuple':[0, [1,2,3]]},
          {'$tuple':[[], {'x':1}]}, {'tasks':{'a':1, 'b':2}}, {'records':[1,2]}, {'tasks':[], 'records':[1,2]},
          {'tasks':{'$tuple':[1,2]}, 'records':[1]}, {'status':'layout_unrecognized'}, {'status':'unsupported_table'}]
for field in ('record_count', 'task_count', 'asset_count', 'scene_count'):
    counts.extend([{field:value, 'tasks':[1,2,3]} for value in values + [-(2**80), 2**90, {'$float':'nan'}, {'$float':'inf'}]])
counts.extend([{'record_count':True, 'task_count':-2, 'asset_count':4}, {'record_count':0, 'task_count':9}, {'records':{'$tuple':[1,2]}}])
for i, value in enumerate(counts):
    decoded = decode(value)
    rejected = type(decoded) is dict and decoded.get('status') in ('layout_unrecognized','unsupported_table')
    add('count', f'count-{i}', value, {'count':p._result_count(decoded), 'rejected':rejected})


def run(name, actions, prior=b''):
    saved = {}
    with tempfile.TemporaryDirectory() as root:
        directory = Path(root) / 'parser_diagnostics'; directory.mkdir()
        if prior: (directory / 'last_success.json').write_bytes(prior)
        r = p.DiagnosticRun(root)
        for action in actions:
            if 'event' in action: r.record(action['event'])
            elif 'identity' in action: r.identity(action['identity'])
            elif 'coverage' in action:
                token = p._run.set(r)
                try: p.record_coverage(action['coverage'])
                finally: p._run.reset(token)
        def write(path, value):
            raw = dump(value)
            if len(raw) <= p.MAX_REPORT_BYTES: saved[path.name] = b64(raw)
        with patch.object(p, '_write', write), patch.object(p, 'datetime', Clock): r.save()
    add('run', name, {'actions':actions, 'prior':b64(prior)},
        {'latest':saved.get('latest.json'), 'baseline':saved.get('last_success.json')})

run('empty', [])
run('success', [{'event':event()}])
run('failure-sticky', [{'event':event(failed=True)}, {'event':event()}, {'event':event(failed=True, location={'offset':4})}])
run('replace-preserves-position', [{'event':event()}, {'event':event(1)}, {'event':event(record_count=4)}])
run('retain-failure', [{'event':event(failed=True)}] + [{'event':event(i)} for i in range(1,260)])
run('evict-oldest-failure', [{'event':event(i, True)} for i in range(140)])
run('identity-and-coverage', [{'identity':f'{i:064x}'} for i in range(12)] +
    [{'identity':'0'*64}, {'identity':'INVALID'}, {'event':event()}, {'coverage':{'items':'passed','scenes':'not_available'}},
     {'coverage':{'items':'not_available','scenes':'failed'}}, {'coverage':{'scenes':'passed','tasks':'passed'}}])
prior = dump({'parsers':{'synthetic.parse_0:default':baseline()}})
run('baseline-changed', [{'event':event(record_count=4, selected_schema='profile-v2')}], prior)
run('baseline-same', [{'event':event(inputs=baseline()['inputs'])}], prior)
run('baseline-empty-inputs', [{'event':event(inputs={})}], prior)
run('failure-preserves-baseline', [{'event':event(failed=True)}], prior)
run('compare-prior-not-current', [{'event':event(record_count=4)}, {'event':event(inputs={'raw':digest(b'different')}, record_count=5)}], prior)
run('variants', [{'event':event(variant=v)} for v in ('MainPackage','DataPackage','EventData.NewNpc','Scene_1.bytes')])
run('negative-count-baseline', [{'event':event(record_count=-1)}])
run('large-count-baseline', [{'event':event(record_count=2**90)}])
run('profile-underscore-baseline', [{'event':event(selected_schema='profile_' )}])
run('max-inputs-max-events', [{'event':event(i, inputs={f'raw_{j}':digest(bytes([j])) for j in range(16)})} for i in range(128)])
run('report-exact-limit', [{'event':event(i, inputs={f'raw_{j}':digest(bytes([j])) for j in range(16)})} for i in range(128)],
    dump({'parsers':{f'synthetic.parse_{i}:default':baseline(inputs={f'raw_{j}':digest(bytes([j])) for j in range(16)}) for i in range(128)}}))
raws = [b'', b'null', b'[]', b'{', b'{"parsers":[]}', b'{"parsers":{"unsafe/path":{"secret":"value"}}}',
        b'\xff', prior+b' junk',
        dump({'parsers':{'\ud800':baseline(), 'synthetic.parse_0:default':baseline()}}),
        dump({'parsers':{'synthetic.parse_0:default':baseline(inputs={'\ud800':digest(b'x')})}}),
        dump({'parsers':{'synthetic.parse_0:default':baseline(schema='\ud800')}}), b'{"ignored":NaN,"parsers":'+dump({'synthetic.parse_0:default':baseline()})+b'}',
        b'{"ignored":Infinity,"parsers":'+dump({'synthetic.parse_0:default':baseline()})+b'}',
        b'{"parsers":{"synthetic.parse_0:default":null,"synthetic.parse_0:default":'+dump(baseline())+b'}}',
        b'{"parsers":{"synthetic.parse_0:default":'+dump(baseline())+b',"synthetic.parse_0:default":null}}',
        b' '*(p.MAX_REPORT_BYTES-len(prior))+prior, b' '*(p.MAX_REPORT_BYTES-len(prior)+1)+prior]
raws.extend([b'{\"ignored\":'+token+b',\"parsers\":'+dump({'synthetic.parse_0:default':baseline()})+b'}' for token in (b'-NaN', b'1NaN', b'1Infinity', b'--Infinity', b'-Infinity')])
raws.extend([b'{\"ignored\":'+b'9'*n+b',\"parsers\":'+dump({'synthetic.parse_0:default':baseline()})+b'}' for n in (4300,4301)])
for encoding in ('utf-8-sig','utf-16','utf-16-le','utf-16-be','utf-32','utf-32-le','utf-32-be'): raws.append(prior.decode().encode(encoding))
for i, raw in enumerate(raws): run(f'malformed-or-encoded-{i}', [{'event':event()}], raw)
# All retained rows have exact schemas; malformed top-level fields never enter output.
run('baseline-key-filter-and-cap', [], dump({'parsers':{**{f'p{i}:default':baseline() for i in range(140)}, '../secret':baseline(), 'okay:default':{'secret':'never retained'}}}))

# Exercise the source decorator itself, including lazy result-byte fallback and swallowed nested failures.
for scenario in ('list', 'tuple', 'negative_count', 'rejected', 'failure', 'bytes_fallback', 'manifest', 'nested'):
    captured = {}
    def parse(raw=None):
        p.checkpoint(offset=3, field='header', profile='profile-v1')
        if scenario == 'failure': raise ValueError('SECRET_EXCEPTION_MESSAGE')
        if scenario == 'list': return [0, 0, 0]
        if scenario == 'tuple': return ({'metadata':'discarded'}, [1,2])
        if scenario == 'negative_count': return {'record_count':-7}
        if scenario == 'rejected': return {'status':'unsupported_table'}
        if scenario == 'bytes_fallback': return b'SYNTHETIC_RETURNED_BYTES'
        if scenario == 'manifest': return {'header':{'package_name':'MainPackage'}, 'asset_count':4}
        if scenario == 'nested':
            def child(raw):
                p.checkpoint(offset=8, field='child_header')
                raise ValueError('SECRET_CHILD_MESSAGE')
            child.__module__='synthetic'; child.__name__='child'
            try: p.diagnosed('child-v1')(child)(raw)
            except ValueError: pass
            return {'status':'layout_unrecognized'}
    parse.__module__='synthetic'; parse.__name__='parse_manifest' if scenario=='manifest' else 'parse'
    diagnosed = p.diagnosed('schema-v1')(parse)
    with tempfile.TemporaryDirectory() as root:
        run_value = p.DiagnosticRun(root)
        token = p._run.set(run_value)
        try:
            try: diagnosed(None if scenario == 'bytes_fallback' else b'SYNTHETIC_INPUT_BYTES')
            except ValueError: pass
        finally: p._run.reset(token)
        def write(path, value): captured[path.name] = b64(dump(value))
        with patch.object(p, '_write', write), patch.object(p, 'datetime', Clock): run_value.save()
    add('wrapped', scenario, {}, {'latest':captured['latest.json'], 'baseline':captured['last_success.json']})

raw = dump(vectors)
compressed = gzip_json_bytes(raw.decode('utf-8'))
assert len(compressed) < 500_000
fixtures = Path(__file__).with_name('Fixtures')
fixtures.mkdir(exist_ok=True)
(fixtures / 'diagnostics.json.gz').write_bytes(compressed)
compressed_hash = hashlib.sha256(compressed).hexdigest()
decoded_hash = hashlib.sha256(raw).hexdigest()
hash_value = hashlib.sha256((ROOT / SOURCE).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
output = Path(__file__).with_name('ParserDiagnosticPythonVectors.cs')
output.write_text('''// Generated by generate_parser_diagnostics_vectors.py. Synthetic input only.
using System.Text.Json.Nodes;
using Lala.Core.Tests.TestSupport;
namespace Lala.Core.Tests.Diagnostics.Parsing;
public static class ParserDiagnosticPythonVectors
{
    public const string SourceSha256 = "''' + hash_value + '''";
    public static IEnumerable<object[]> Cases()
    {
        string json = GzipJson.DecodeResource("Lala.Core.Tests.Diagnostics.Parsing.Fixtures.diagnostics.json.gz",
            "''' + compressed_hash + '''", "''' + decoded_hash + '''");
        foreach (var row in JsonNode.Parse(json)!.AsArray())
            yield return new object[] { row!["kind"]!.GetValue<string>(), row["name"]!.GetValue<string>(), row.ToJsonString() };
    }
}
''', encoding='utf-8')
print(f'{len(vectors)} vectors; {len(raw)} JSON bytes; {len(compressed)} gzip bytes; source {hash_value}')
