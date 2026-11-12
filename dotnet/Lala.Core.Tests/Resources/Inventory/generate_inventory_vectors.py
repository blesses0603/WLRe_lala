#!/usr/bin/env python3
"""Real SQLite/full unchanged record_inventory oracle using owned synthetic bytes.

No network, .NET, game payload, installed-game path, or user database is used.
Only temporary SQLite files are opened. All production modules (including every
parser and OfficialCatalogIdentity) are imported normally, without patching.
The retained RuntimeCandidate fixture supplies the compact ten-table baseline;
existing generator function ASTs supply synthetic variants without running their
large loops. Sources normalize CRLF only, preserving bare CR. No source function
or import is rewritten. Cases marked source_accepts_strict_rejects intentionally
record source behavior, not parity for stricter C# integrity/schema/quota gates.

Fixture SQL parameters are scalars or {blob_ref: ID}; members are ordered and use
blob_ref plus optional data_kind (null/string/bytearray) for invalid-input tests.
Identity refs name real constructed identities, are null, or are 'wrong_type'.
Snapshots contain the six logical tables, ordered by their primary keys, with
raw BLOB SHA-256 and length instead of raw bytes. Missing tables are null.
C# discovery receives only scalar case IDs; blob allocation occurs at execution.
"""
from __future__ import annotations
import argparse
import ast
import base64
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from wlre.services.world.resource_database import record_inventory
from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision

PINNED_SOURCES = {
    'wlre/services/world/resource_database.py': '45c2203971c7224dd08932d1c8c2cb901c1332841ca036eee40bed4a843732be',
    'wlre/services/world/catalog_identity.py': 'a620f441f2f7c497316db47f7f77560f04f2e5d5773f8d292285c6988a9724f3',
    'wlre/services/world/itemdata_v1.py': '8ee7e6964e53c3f188ddf9ab761d14e58a238fb01397e4b82369779ca1b549d2',
    'wlre/services/world/smith_candidate.py': '90c0df102273c8d3d315da85a98d0608ab078acf451b6909f45f09e94fd93b6c',
    'wlre/services/world/preview_1275.py': 'd2d12df007bd9ecabe0bd66324f1791868be7158d7043b671e0731a757883214',
    'wlre/services/world/npc_talk.py': '09451b3d57fa9b7cba82121d98fde64d716fb5c914f3763509b96c3864eebc61',
    'wlre/services/expedition/data.py': '3d3c789c3b8496da415e0e88055211f68edc35e4f33c52acc6b7c3e92f31b80f',
    'wlre/services/instance_catalog.py': 'c51e76030b6f628e75ec559ee61f207f808e8f392dbed8d732d38282bfa9032e',
    'wlre/services/world/eve_v115.py': '42f4281499ea6804d589b9836d2c777aabd4450e328ae03e60cef1901edeb5bf',
    'wlre/network/wire.py': '5c435c362e14365d0bc62903eae17a4d0194b22a8f4966a476c14749da0a7392',
    'wlre/services/parser_diagnostics.py': 'bb9a850e5cbff7504462cc3f24f7a8d192dd0ca96207ea65e18c62c24ea9cbdc',
}
INPUT_FIXTURES = {
    'dotnet/Lala.Core.Tests/Resources/DatabaseMatch/Fixtures/database-match.json.gz': '2bbc575b94d9f87208a53cc0222b75e3f5004ccae4bf52ad95c00a04f5ac9e96',
    'dotnet/Lala.Core.Tests/Catalogs/RuntimeCandidate/Fixtures/runtime-candidate.json.gz': 'd9e7d7c81118b6643ed8dfc49335188fc92b140d5dc70152d60b7afd9ad02348',
}
TABLE_ORDER = ('versions', 'version_identities', 'resources', 'parsed_resource_rows', 'sync_state', 'version_parents')
SORT_COLUMNS = ('id', 'version_id', 'version_id,name', 'version_id,source,row_key', 'singleton', 'version_id')
DERIVED_TABLES = ('ItemData_C', 'SmithData_C', 'TalkData_C', 'TextData_C', 'ScenesData_C', 'Eve')
SOURCES_BY_TABLE = {
    'ItemData_C': ('items_v1',), 'SmithData_C': ('smith_v1',),
    'TalkData_C': ('talk_v1',), 'TextData_C': ('text_v1',),
    'ScenesData_C': ('scenes_v1',), 'Eve': ('eve_npc_v1', 'eve_interact_v1'),
}
SOURCE_INPUT = 'wlre/services/world/resource_database.py'
BUILDERS = set()
p = lambda fmt, *values: struct.pack('<' + fmt, *values)
table = lambda *rows: p('i', len(rows)) + b''.join(rows)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def normalized_source(path):
    return (ROOT / path).read_bytes().replace(b'\r\n', b'\n')


def read_fixture(path):
    raw = (ROOT / path).read_bytes()
    assert sha(raw) == INPUT_FIXTURES[path], 'Retained input fixture pin changed: ' + path
    return json.loads(gzip.decompress(raw))


def constructors(path, names, extra):
    BUILDERS.add(path)
    tree = ast.parse(normalized_source(path).decode('utf-8'), filename=path)
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == len(names)
    env = {'struct': struct, **extra}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), env)
    return env


def setup_inputs():
    identity_inputs = read_fixture(next(iter(INPUT_FIXTURES)))['identity_inputs']
    identities = {}
    real = {}
    for ref in ('A', 'B', 'C'):
        inputs = copy.deepcopy(identity_inputs)
        if ref != 'A':
            inputs['snapshot']['data_ver'] = '1.3.' + str(21 + ord(ref) - ord('A'))
        identity = OfficialCatalogIdentity(inputs['snapshot']['data_ver'], inputs['snapshot']['exe_version'], tuple(
            PackageRevision(row['package'], row['package_version'], row['sha256'], row['crc32_le'])
            for row in inputs['manifests']))
        inputs.pop('key', None)
        inputs['canonical_json'] = canonical(identity.as_dict())
        inputs['catalog_key'] = identity.key
        identities[ref] = inputs
        real[ref] = identity
    assert identities['A']['catalog_key'] == identity_inputs['key']
    retained = read_fixture(list(INPUT_FIXTURES)[1])
    baseline = next(row for row in retained if row['name'] == 'all-ten-duplicate-products')
    raw = {name: base64.b64decode(value, validate=True) for name, value in baseline['inputs'].items()}
    item = constructors('dotnet/Lala.Core.Tests/Catalogs/generate_catalog_vectors.py', ['item_record'], {})['item_record']
    required = constructors('dotnet/Lala.Core.Tests/Catalogs/RequiredTables/generate_required_table_vectors.py', ['talk', 'text'], {'p': p})
    eve = constructors('dotnet/Lala.Core.Tests/World/Eve/generate_eve_vectors.py', ['common', 'npc', 'interact', 'scene', 'container'], {'u16': lambda x: p('H', x), 'u32': lambda x: p('I', x)})
    runtime = constructors('dotnet/Lala.Core.Tests/Catalogs/RuntimeCandidate/generate_runtime_candidate_vectors.py', ['smith', 'stage'], {})
    varied = dict(raw)
    varied['ItemData_C'] = table(item(123, price=7)[0], item(2)[0], item(10)[0])
    varied['SmithData_C'] = table(p('H', 9) + runtime['smith'](time=3), p('H', 10) + runtime['smith'](), p('H', 1) + runtime['smith'](99))
    varied['TalkData_C'] = table(required['talk'](1, 'changed\r\n雪😀', 8), required['talk'](10, 'ten'), required['talk'](2, 'two'))
    varied['TextData_C'] = table(required['text'](10, 'changed\x00雪😀'), required['text'](2, 'two'), required['text'](100, 'hundred'))
    varied['ScenesData_C'] = table(runtime['stage'](500, 2), runtime['stage'](2), runtime['stage'](10))
    varied['Eve'] = eve['container']([(500, eve['scene']({0: [eve['npc'](3, ident=9002), eve['npc'](2)], 7: [eve['interact'](8, form=1), eve['interact'](10)]}, model=456)), (2, eve['scene']({0: [eve['npc'](10)], 7: [eve['interact'](2)]}, model=456))])
    empty_eve = eve['container']([(500, eve['scene']({}, model=456))])
    legacy_smith = table(runtime['smith']())
    return identities, real, raw, varied, empty_eve, legacy_smith


def make_blob(raw):
    return dict(kind='base64', value=base64.b64encode(raw).decode('ascii'), size=len(raw), sha256=sha(raw))


def materialize(blobs, ref):
    spec = blobs[ref]
    raw = base64.b64decode(spec['value'], validate=True) if spec['kind'] == 'base64' else bytes([spec['byte']]) * spec['length']
    assert len(raw) == spec['size'] and sha(raw) == spec['sha256']
    return raw


def operation(sql, *parameters):
    return dict(sql=sql, parameters=list(parameters))


def execute_sql(path, operations, blobs):
    if not operations:
        return
    with sqlite3.connect(path) as db:
        for op in operations:
            args = [materialize(blobs, value['blob_ref']) if isinstance(value, dict) else value for value in op['parameters']]
            db.execute(op['sql'], args)


def snapshot(path):
    result = {name: None for name in TABLE_ORDER}
    columns = []
    if path.exists():
        with sqlite3.connect(path) as db:
            db.row_factory = sqlite3.Row
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name, order in zip(TABLE_ORDER, SORT_COLUMNS):
                if name in names:
                    result[name] = []
                    for row in db.execute('SELECT * FROM ' + name + ' ORDER BY ' + order):
                        row = dict(row)
                        if name == 'resources':
                            raw = row.pop('data')
                            row['data_sha256'] = sha(raw) if isinstance(raw, bytes) else None
                            row['data_length'] = len(raw) if raw is not None else None
                            if not isinstance(raw, bytes):
                                row['data_type'] = 'null' if raw is None else type(raw).__name__
                        result[name].append(row)
            if 'sync_state' in names:
                columns = [row[1] for row in db.execute('PRAGMA table_info(sync_state)')]
    return dict(tables=result, sync_state_columns=columns)


def generate_cases(identities, real, raw, varied, empty_eve, legacy_smith):
    blobs = {name + '-base': make_blob(value) for name, value in raw.items()}
    blobs.update({name + '-varied': make_blob(value) for name, value in varied.items()})
    blobs.update({'empty': make_blob(b''), 'zero-count': make_blob(table()), 'invalid': make_blob(b'bad'),
                  'opaque': make_blob(b'owned-opaque\x00\xff\xe9'), 'opaque-other': make_blob(b'owned-other'),
                  'Eve-empty': make_blob(empty_eve), 'Smith-legacy': make_blob(legacy_smith)})
    def repeat_blob(ref, length):
        blobs[ref] = dict(kind='repeat', byte=165, length=length, size=length, sha256=sha(bytes([165]) * length))
    repeat_blob('max-exact', 16 * 1024 * 1024)
    repeat_blob('max-plus-one', 16 * 1024 * 1024 + 1)
    cases = []
    def members(values=None, suffix='base'):
        return [dict(name='tables/' + name + '.bytes', blob_ref=name + '-' + suffix) for name in (values if values is not None else raw)]
    def call(ref='A', inputs=None, *, identity=True, sql=(), key=None):
        return dict(catalog_key=key or identities[ref]['catalog_key'], identity_ref=ref if identity else None,
                    members=copy.deepcopy(members() if inputs is None else inputs), preCallSQL=list(sql))
    def add(ident, calls, *, initial=(), policy='parity', note=None):
        row = dict(id=ident, policy=policy, initialSetup=list(initial), calls=calls)
        if note: row['note'] = note
        cases.append(row)
    def one(name, ref):
        return [dict(name='tables/' + name + '.bytes', blob_ref=ref)]
    all_base = members()
    all_varied = members(suffix='varied')
    add('all-ten-seven-derived-views', [call()])
    add('same-version-repeat-no-op', [call(), call()])
    add('version-switch-A-B-B-A', [call(), call('B', all_varied), call('B', all_varied), call()])
    add('version-switch-A-B-C-A-B', [call(), call('B', all_varied), call('C'), call(), call('B', all_varied)])
    add('same-version-partial-addition-and-omission', [call(inputs=members(['ItemData_C', 'TextData_C'])), call(inputs=members(['SmithData_C'])), call(inputs=members(['ItemData_C']))])
    add('cross-version-partial-addition-and-omission', [call(inputs=members(['ItemData_C', 'TextData_C'])), call('B', members(['ItemData_C', 'SmithData_C'], 'varied')), call('B', members(['TextData_C'], 'varied'))])
    add('raw-only-four-runtime-tables', [call(inputs=members(['AdventureData_C', 'AdventureLvData_C', 'NpcData_C', 'NpcCareerData_C']))])
    add('raw-only-unknown-table', [call(inputs=one('Unknown', 'opaque')), call('B', one('Unknown', 'opaque-other'))])
    add('raw-empty-unknown-table', [call(inputs=one('Unknown', 'empty'))])
    add('optional-identity-none-then-added', [call(identity=False), call(identity=False), call()])
    add('optional-identity-none-preserves-saved', [call(), call(identity=False)])
    add('optional-identity-none-switches', [call(identity=False), call('B', all_varied, identity=False), call(identity=False)])
    add('identity-key-mismatch', [call(key=identities['B']['catalog_key'])])
    wrong_identity = call(); wrong_identity['identity_ref'] = 'wrong_type'
    add('identity-wrong-type', [wrong_identity])
    add('no-members', [call(inputs=[])])
    ignored = [dict(name=name, blob_ref='invalid', data_kind='null') for name in ('Tables/a.bytes', 'table/a.bytes', 'tables\\a.bytes', '/tables/a.bytes', 'tables/a.BYTES', 'tables/a.bytes.bak', 'notes.txt')]
    add('all-members-filtered', [call(inputs=ignored)])
    add('ignored-invalid-data-before-valid-table', [call(inputs=ignored + members(['ItemData_C']))])
    add('valid-nested-posix-basename', [call(inputs=[dict(name='tables/nested/ItemData_C.bytes', blob_ref='ItemData_C-base')])])
    add('posix-dot-and-dotdot-name-components', [call(inputs=[dict(name='tables/../nested/./Unknown.bytes', blob_ref='opaque')])])
    add('duplicate-posix-basename', [call(inputs=[dict(name='tables/a/ItemData_C.bytes', blob_ref='ItemData_C-base'), dict(name='tables/b/ItemData_C.bytes', blob_ref='ItemData_C-base')])])
    add('duplicate-basename-before-invalid-data', [call(inputs=[dict(name='tables/ItemData_C.bytes', blob_ref='ItemData_C-base'), dict(name='tables/nested/ItemData_C.bytes', blob_ref='invalid', data_kind='null')])])
    for kind in ('null', 'string', 'bytearray'):
        add('selected-data-not-bytes-' + kind, [call(inputs=[dict(name='tables/a.bytes', blob_ref='opaque', data_kind=kind)])])
    add('raw-name-case-distinction', [call(inputs=one('opaque', 'opaque') + one('Opaque', 'opaque-other'))])
    for name in DERIVED_TABLES:
        selected = one(name, name + '-base')
        invalid = one(name, 'invalid')
        empty = one(name, 'empty')
        zero = one(name, 'Eve-empty' if name == 'Eve' else 'zero-count')
        add('current-parse-failure-' + name, [call(inputs=invalid)])
        add('present-empty-bytes-' + name, [call(inputs=empty)])
        add('zero-record-table-' + name, [call(inputs=zero)])
        add('prior-parse-failure-' + name, [call(inputs=invalid), call('B', selected)])
        add('prior-missing-table-' + name, [call(inputs=one('Unknown', 'opaque')), call('B', selected)])
        add('prior-present-empty-bytes-' + name, [call(inputs=empty), call('B', selected)])
        add('prior-zero-record-table-' + name, [call(inputs=zero), call('B', selected)])
        add('valid-to-zero-record-table-' + name, [call(inputs=selected), call('B', zero)])
        add('valid-to-current-parse-failure-' + name, [call(inputs=selected), call('B', invalid)])
        add('current-parse-failure-repeat-' + name, [call(inputs=invalid), call(inputs=invalid)])
        add('missing-current-derived-' + name, [call(inputs=selected), call('B', one('Unknown', 'opaque'))])
        add('parsed-rows-diff-' + name, [call(inputs=selected), call('B', one(name, name + '-varied'))])
    add('smith-legacy-33-byte-rows', [call(inputs=one('SmithData_C', 'Smith-legacy'))])
    add('all-current-derived-parse-failures', [call(inputs=[dict(name='tables/' + name + '.bytes', blob_ref='invalid') for name in DERIVED_TABLES])])
    add('all-prior-derived-parse-failures', [call(inputs=[dict(name='tables/' + name + '.bytes', blob_ref='invalid') for name in DERIVED_TABLES]), call('B')])
    add('stored-identity-collision', [call(), call(sql=[operation("UPDATE version_identities SET identity='{}' WHERE version_id=1")])])
    add('stored-identity-byte-exact-whitespace-collision', [call(), call(sql=[operation('UPDATE version_identities SET identity=? WHERE version_id=1', identities['A']['canonical_json'] + ' ')])])
    add('same-version-raw-collision', [call(), call(inputs=all_varied)])
    add('recorded-sha-collision-with-unchanged-raw', [call(), call(sql=[operation("UPDATE resources SET sha256=? WHERE version_id=1 AND name='Eve.bytes'", '0' * 64)])])
    add('raw-collision-rolls-back-new-table', [call(), call(inputs=one('New', 'opaque') + all_varied)])
    for name, sources in SOURCES_BY_TABLE.items():
        for source in sources:
            add('stored-derived-collision-' + source, [call(), call(sql=[operation('UPDATE parsed_resource_rows SET data=? WHERE version_id=1 AND source=?', '{}', source)])])
    late_setup = [operation('INSERT INTO versions(id,catalog_key) VALUES (2,?)', identities['B']['catalog_key']),
                  operation('INSERT INTO parsed_resource_rows VALUES (2,?,?,?)', 'eve_interact_v1', '500:8', '{}')]
    add('late-derived-collision-rolls-back-entire-attempt', [call(), call('B', all_varied + one('New', 'opaque'), sql=late_setup)],
        note='The pre-call version and collision row intentionally survive. New identity, raw/derived rows, active/previous state, and parent insertion must all roll back.')
    add('late-raw-collision-rolls-back-state-and-parent', [call(), call('B', all_varied), call(), call('B', one('New', 'opaque') + all_base, sql=[operation('DELETE FROM version_parents WHERE version_id=2')])])
    add('parent-fallback-with-missing-previous', [call(), call('B', all_varied), call('B', all_varied, sql=[operation('UPDATE sync_state SET previous_id=NULL WHERE singleton=1')])])
    add('parent-fallback-with-missing-sync-state', [call(), call('B', all_varied), call('B', all_varied, sql=[operation('DELETE FROM sync_state')])])
    add('self-previous-does-not-become-previous', [call(), call(sql=[operation('UPDATE sync_state SET previous_id=active_id')])])
    add('null-parent-fallback', [call(), call(sql=[operation('INSERT INTO version_parents VALUES (1,NULL)'), operation('DELETE FROM sync_state')])])
    add('self-parent-does-not-become-previous', [call(), call(sql=[operation('INSERT INTO version_parents VALUES (1,1)'), operation('UPDATE sync_state SET previous_id=NULL')])])
    add('legacy-sync-state-previous-id-evolution', [call()], initial=[operation('CREATE TABLE sync_state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), active_id INTEGER NOT NULL)')])
    add('legacy-active-state-evolution', [call('B', all_varied)], initial=[
        operation('CREATE TABLE versions (id INTEGER PRIMARY KEY, catalog_key TEXT UNIQUE NOT NULL)'),
        operation('INSERT INTO versions(id,catalog_key) VALUES (1,?)', identities['A']['catalog_key']),
        operation('CREATE TABLE sync_state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), active_id INTEGER NOT NULL)'),
        operation('INSERT INTO sync_state VALUES (1,1)')])
    # Deliberate strict-port divergences, never asserted as successful C# parity.
    strict = 'source_accepts_strict_rejects'
    add('tampered-raw-matching-recorded-sha', [call(), call(sql=[operation("UPDATE resources SET data=? WHERE version_id=1 AND name='Eve.bytes'", {'blob_ref': 'invalid'})])], policy=strict,
        note='Source skips a stored raw row when its recorded SHA matches incoming bytes; strict port must hash actual stored bytes and reject.')
    add('tampered-prior-raw-matching-recorded-sha', [call(), call('B', all_varied, sql=[operation("UPDATE resources SET data=? WHERE version_id=1 AND name='TextData_C.bytes'", {'blob_ref': 'invalid'})])], policy=strict,
        note='Source reports previous parse_failed without validating the stored raw digest; strict port rejects corrupt prior bytes.')
    add('unexpected-trigger-mutates-state', [call(), call('B', all_varied, sql=[operation('CREATE TRIGGER inventory_poison AFTER INSERT ON resources BEGIN UPDATE sync_state SET previous_id=999; END')])], policy=strict,
        note='Source executes triggers; strict schema gate must reject the unexpected trigger before mutating any table.')
    add('unexpected-versions-schema', [call()], initial=[operation('CREATE TABLE versions (id INTEGER PRIMARY KEY, catalog_key TEXT UNIQUE NOT NULL, injected TEXT)')], policy=strict,
        note='Source accepts extra schema columns; strict port rejects a table definition outside its six-table contract.')
    add('unexpected-index-schema', [call(), call(sql=[operation('CREATE INDEX unexpected_resources_index ON resources(name)')])], policy=strict,
        note='Source accepts an extra persistent index; strict schema admission is intentionally narrower.')
    add('raw-payload-maximum-exact', [call(inputs=one('Opaque', 'max-exact'))])
    add('raw-payload-over-maximum', [call(inputs=one('Opaque', 'max-plus-one'))], policy=strict,
        note='Source has no raw inventory payload quota; strict port rejects a raw payload above 16 MiB.')
    add('identity-none-arbitrary-catalog-key', [call(inputs=one('Opaque', 'opaque'), identity=False, key='not-a-catalog-digest')],
        note='Source-compatible input accepts arbitrary bounded catalog keys when identity is absent.')
    add('empty-table-basename', [call(inputs=[dict(name='tables/.bytes', blob_ref='opaque')])],
        note='The POSIX basename is .bytes, a nonempty resource name accepted by the source-compatible port.')
    # POSIX-only separators, including on hosts where backslash separates paths.
    add('posix-literal-backslash-distinct-from-separator', [call(inputs=[
        dict(name=r'tables/a\Item.bytes', blob_ref='opaque'),
        dict(name='tables/a/Item.bytes', blob_ref='opaque-other')])])
    add('posix-repeated-slashes-and-dot-components', [call(inputs=[
        dict(name='tables///./nested//./ItemData_C.bytes', blob_ref='ItemData_C-base'),
        dict(name='tables//././TextData_C.bytes', blob_ref='TextData_C-base')])])
    add('posix-duplicate-after-repeated-slashes', [call(inputs=[
        dict(name='tables///nested//ItemData_C.bytes', blob_ref='ItemData_C-base'),
        dict(name='tables//./other///ItemData_C.bytes', blob_ref='ItemData_C-base')])])
    add('posix-literal-backslash-basename-duplicate', [call(inputs=[
        dict(name=r'tables/nested/a\Item.bytes', blob_ref='opaque'),
        dict(name=r'tables/a\Item.bytes', blob_ref='opaque')])])
    assert len({case['id'] for case in cases}) == len(cases)
    with tempfile.TemporaryDirectory(prefix='lala-inventory-oracle-') as directory:
        for index, case in enumerate(cases):
            path = Path(directory) / (str(index) + '.sqlite3')
            execute_sql(path, case['initialSetup'], blobs)
            for step in case['calls']:
                execute_sql(path, step['preCallSQL'], blobs)
                before = snapshot(path)
                payloads = {}
                for member in step['members']:
                    data = materialize(blobs, member['blob_ref'])
                    kind = member.get('data_kind')
                    if kind == 'null': data = None
                    elif kind == 'string': data = data.decode('latin1')
                    elif kind == 'bytearray': data = bytearray(data)
                    payloads[member['name']] = data
                ref = step['identity_ref']
                identity = real[ref] if ref in real else ({} if ref == 'wrong_type' else None)
                report = error = None
                try:
                    report = record_inventory(path, step['catalog_key'], payloads, identity=identity)
                except Exception as exc:
                    error = dict(type=type(exc).__name__, message=str(exc))
                after = snapshot(path)
                step['expected'] = dict(report=report, error=error, snapshot=after, unchanged=before == after)
                if error and before['tables']['versions'] is not None:
                    assert before == after, (case['id'], 'Failure mutated existing logical state')
    baseline = cases[0]['calls'][0]['expected']
    assert baseline['error'] is None
    report = baseline['report']
    assert report['item_rows']['status'] == report['smith_rows']['status'] == 'parsed'
    assert set(report['other_rows']) == {'talk_v1', 'text_v1', 'scenes_v1', 'eve_npc_v1', 'eve_interact_v1'}
    assert all(row['status'] == 'parsed' for row in report['other_rows'].values())
    for case in cases:
        if case['policy'] == 'source_accepts_strict_rejects':
            assert case['calls'][-1]['expected']['error'] is None, case['id']
        for step in case['calls']:
            for row in step['expected']['snapshot']['tables']['parsed_resource_rows'] or []:
                assert row['data'] == canonical(json.loads(row['data'])), (case['id'], row['source'])
    return blobs, cases


def compressed(decoded):
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=0, compresslevel=9) as output:
        output.write(decoded)
    return stream.getvalue()


def csharp(cases, packed, decoded):
    ids = '\n'.join('        yield return new object[] { ' + json.dumps(case['id']) + ' };' for case in cases)
    return f'''// Generated by generate_inventory_vectors.py. Full unchanged Python + real SQLite oracle.
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace Lala.Core.Tests.Resources;

public static class InventoryPythonVectors
{{
    public const string CompressedSha256 = "{sha(packed)}";
    public const string DecodedSha256 = "{sha(decoded)}";
    public const int CaseCount = {len(cases)};
    private static readonly Lazy<JsonDocument> Document = new(Load);
    public static JsonElement Root => Document.Value.RootElement;
    public static JsonElement Case(string id) => Root.GetProperty("cases").EnumerateArray()
        .Single(row => row.GetProperty("id").GetString() == id);

    // Discovery returns scalar IDs only; document and blob recipes remain lazy.
    public static IEnumerable<object[]> Cases()
    {{
{ids}
    }}

    private static JsonDocument Load()
    {{
        using Stream stream = typeof(InventoryPythonVectors).Assembly.GetManifestResourceStream(
            "Lala.Core.Tests.Resources.Inventory.Fixtures.inventory.json.gz")
            ?? throw new InvalidOperationException("Missing retained inventory Python fixture.");
        using var packed = new MemoryStream();
        stream.CopyTo(packed);
        byte[] compressed = packed.ToArray();
        if (Convert.ToHexStringLower(SHA256.HashData(compressed)) != CompressedSha256)
            throw new InvalidOperationException("Inventory compressed fixture hash mismatch.");
        using var input = new MemoryStream(compressed, writable: false);
        using var gzip = new GZipStream(input, CompressionMode.Decompress);
        using var output = new MemoryStream();
        gzip.CopyTo(output);
        byte[] decoded = output.ToArray();
        if (Convert.ToHexStringLower(SHA256.HashData(decoded)) != DecodedSha256)
            throw new InvalidOperationException("Inventory decoded fixture hash mismatch.");
        return JsonDocument.Parse(decoded);
    }}
}}
'''.encode('utf-8')


def artifacts():
    for path, expected in PINNED_SOURCES.items():
        assert sha(normalized_source(path)) == expected, 'Source pin changed: ' + path
    identities, real, raw, varied, empty_eve, legacy_smith = setup_inputs()
    blobs, cases = generate_cases(identities, real, raw, varied, empty_eve, legacy_smith)
    node = next(n for n in ast.parse(normalized_source(SOURCE_INPUT)).body if isinstance(n, ast.FunctionDef) and n.name == 'record_inventory')
    function = dict(path=SOURCE_INPUT, name=node.name, first_line=node.lineno, last_line=node.end_lineno,
                    ast_sha256=sha(ast.dump(node, include_attributes=False).encode('utf-8')),
                    execution='Full unchanged function imported normally, using real stdlib sqlite3 and actual parser imports.')
    source_hashes = dict(PINNED_SOURCES)
    source_hashes.update({path: sha(normalized_source(path)) for path in sorted(BUILDERS)})
    output = dict(schema_version=1, scope=__doc__, source_sha256=source_hashes, input_fixture_sha256=INPUT_FIXTURES,
                  executed_source=function, table_order=list(TABLE_ORDER), identities=identities, blobs=blobs, cases=cases)
    decoded = (canonical(output) + '\n').encode('utf-8')
    packed = compressed(decoded)
    calls = [step for case in cases for step in case['calls']]
    evidence = dict(schema_version=1, case_count=len(cases), call_count=len(calls),
        successful_source_calls=sum(step['expected']['error'] is None for step in calls),
        source_error_calls=sum(step['expected']['error'] is not None for step in calls),
        strict_divergence_cases=[case['id'] for case in cases if case['policy'] != 'parity'],
        source_sha256=source_hashes, input_fixture_sha256=INPUT_FIXTURES,
        generator_sha256=sha(Path(__file__).read_bytes().replace(b'\r\n', b'\n')),
        source_line_endings='CRLF normalized to LF only; bare CR is preserved', executed_source=function,
        fixture=dict(name='inventory.json.gz', compressed_bytes=len(packed), compressed_sha256=sha(packed),
                     decoded_bytes=len(decoded), decoded_sha256=sha(decoded)),
        oracle='Full unchanged record_inventory, real SQLite temporary files, real parsers and OfficialCatalogIdentity; no parser/SQL/source substitution.',
        excluded=['official provenance or game payload validation', '.NET execution', 'network', 'user databases', 'runtime activation'])
    return {HERE / 'Fixtures/inventory.json.gz': packed,
            HERE / 'Fixtures/evidence.json': (json.dumps(evidence, ensure_ascii=True, sort_keys=True, indent=2) + '\n').encode('utf-8'),
            HERE / 'InventoryPythonVectors.cs': csharp(cases, packed, decoded)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Execute all real SQLite transcripts and require exact retained artifacts.')
    args = parser.parse_args()
    for path, data in artifacts().items():
        if args.check:
            if not path.exists() or path.read_bytes() != data:
                raise SystemExit('Inventory fixture differs; regenerate and review: ' + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            print(str(path.relative_to(ROOT)) + ': ' + str(len(data)) + ' bytes')
    if args.check:
        print('Inventory Python/real SQLite fixtures are current; compressed and decoded bytes match exactly.')


if __name__ == '__main__':
    main()
