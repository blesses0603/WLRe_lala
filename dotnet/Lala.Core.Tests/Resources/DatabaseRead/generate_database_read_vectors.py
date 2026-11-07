#!/usr/bin/env python3
"""Retain unchanged full Python matcher results over actual temporary SQLite files.

Only synthetic DatabaseMatch fixture inputs are used. This executes the complete
database_matches_runtime function, including real pathlib preflight, stdlib
SQLite read-only connection, BEGIN, joins, SELECTs and fetchone. The sole import
substitution supplies the source-literal _REQUIRED_TABLES without loading optional
runtime adapters. The function AST is never rewritten. Explicit reader_capture
expectations describe the deliberately stricter C# reader contract, not Python
parity: duplicates, views and non-integer active IDs can pass the original source.

Each case applies small SQL operation recipes to ten baseline synthetic rows.
Oversized data is materialized only in temporary files, never retained as giant
JSON. Source hashes normalize CRLF only; bare CR is preserved. No .NET, network,
production database, installed-game path, official authority or activation.
"""
from __future__ import annotations

import argparse
import ast
import base64
import builtins
import copy
from contextlib import closing
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from wlre.services.official_resource_sync import validate_snapshot
from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision

SOURCE = 'wlre/services/world/resource_database.py'
MATCH_FIXTURE = 'dotnet/Lala.Core.Tests/Resources/DatabaseMatch/Fixtures/database-match.json.gz'
MAXIMUM_BYTES = 16 * 1024 * 1024
ACTIVE_ID = 41


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def normalized_source(path):
    return (ROOT / path).read_bytes().replace(b'\r\n', b'\n')


# Reuse the retained synthetic identity and baseline, verifying both envelope pins.
MATCH_PACKED = (ROOT / MATCH_FIXTURE).read_bytes()
MATCH_DECODED = gzip.decompress(MATCH_PACKED)
MATCH_EVIDENCE = json.loads((ROOT / MATCH_FIXTURE).with_name('evidence.json').read_bytes())
assert sha(MATCH_PACKED) == MATCH_EVIDENCE['fixture']['compressed_sha256']
assert sha(MATCH_DECODED) == MATCH_EVIDENCE['fixture']['decoded_sha256']
MATCH = json.loads(MATCH_DECODED)
SOURCE_HASHES = {path: sha(normalized_source(path)) for path in MATCH['source_sha256']}
assert SOURCE_HASHES == MATCH['source_sha256'], 'Review source drift before reusing the synthetic fixture'

IDENTITY_INPUTS = copy.deepcopy(MATCH['identity_inputs'])
SNAPSHOT = validate_snapshot(IDENTITY_INPUTS['snapshot'])
for manifest in IDENTITY_INPUTS['manifests']:
    raw = base64.b64decode(manifest['bytes_base64'], validate=True)
    assert sha(raw) == manifest['sha256']
    assert (zlib.crc32(raw) & 0xffffffff).to_bytes(4, 'little').hex() == manifest['crc32_le']
IDENTITY = OfficialCatalogIdentity(SNAPSHOT['data_ver'], SNAPSHOT['exe_version'], tuple(
    PackageRevision(row['package'], row['package_version'], row['sha256'], row['crc32_le'])
    for row in IDENTITY_INPUTS['manifests']))
assert IDENTITY.key == IDENTITY_INPUTS['key']
assert canonical(IDENTITY.as_dict()) == IDENTITY_INPUTS['canonical_json']

runtime_ast = ast.parse(normalized_source('wlre/services/world/bundle_runtime_1275.py'))
TABLES = ast.literal_eval(next(node.value for node in runtime_ast.body
    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
    and target.id == '_REQUIRED_TABLES' for target in node.targets)))
assert list(TABLES) == MATCH['required_tables'] and len(TABLES) == len(set(TABLES)) == 10
source_ast = ast.parse(normalized_source(SOURCE), filename=SOURCE)
FUNCTION = next(node for node in source_ast.body
    if isinstance(node, ast.FunctionDef) and node.name == 'database_matches_runtime')
RETAINED_FUNCTION = copy.deepcopy(FUNCTION)
assert ast.dump(RETAINED_FUNCTION, include_attributes=True) == ast.dump(FUNCTION, include_attributes=True)
CODE = compile(ast.Module(body=[RETAINED_FUNCTION], type_ignores=[]), SOURCE, 'exec')


def controlled_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'wlre.services.world.bundle_runtime_1275':
        assert fromlist == ('_REQUIRED_TABLES',) and level == 0
        return SimpleNamespace(_REQUIRED_TABLES=TABLES)
    return builtins.__import__(name, globals, locals, fromlist, level)


ENV = dict(hashlib=hashlib, json=json, sqlite3=sqlite3, closing=closing,
           __builtins__={**vars(builtins), '__import__': controlled_import})
exec(CODE, ENV)
REFERENCE = ENV['database_matches_runtime']

SCHEMA_SQL = [
    'CREATE TABLE versions (id INTEGER PRIMARY KEY, catalog_key TEXT UNIQUE NOT NULL)',
    'CREATE TABLE version_identities (version_id INTEGER PRIMARY KEY, identity TEXT NOT NULL)',
    'CREATE TABLE resources (version_id INTEGER NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(version_id,name))',
    'CREATE TABLE sync_state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), active_id INTEGER NOT NULL)',
]
match_baseline = next(case for case in MATCH['cases'] if case['id'] == 'all-ten-match')
BASELINE = dict(active_id=ACTIVE_ID, catalog_key=IDENTITY.key,
    identity_json=IDENTITY_INPUTS['canonical_json'],
    rows=[{key: copy.deepcopy(row[key]) for key in ('name', 'sha256', 'data')}
          for row in match_baseline['rows']],
    expected_digests=copy.deepcopy(match_baseline['expected_digests']))
assert match_baseline['active'] == [ACTIVE_ID, BASELINE['catalog_key'], BASELINE['identity_json']]


def blob(raw):
    return dict(kind='base64', value=base64.b64encode(raw).decode('ascii'), size=len(raw), sha256=sha(raw))


def repeated(byte, length):
    return dict(kind='repeat', byte=byte, length=length, size=length, sha256=sha(bytes([byte]) * length))


def text_repeat(value, length):
    # length is a repetition count, not the resulting character or UTF-8 byte length.
    return dict(kind='repeat_text', value=value, length=length)


def materialize(value):
    if not isinstance(value, dict):
        return value
    if value['kind'] == 'repeat_text':
        return value['value'] * value['length']
    if value['kind'] == 'base64':
        raw = base64.b64decode(value['value'], validate=True)
    elif value['kind'] == 'repeat':
        raw = bytes([value['byte']]) * value['length']
    else:
        raise AssertionError('Unknown parameter recipe: ' + value['kind'])
    assert len(raw) == value['size'] and sha(raw) == value['sha256']
    return raw


def op(sql, *parameters):
    return dict(sql=sql, parameters=list(parameters))


def relaxed(table):
    # Removing affinity as well as constraints preserves deliberately wrong SQLite types.
    columns = {'versions': 'id,catalog_key', 'version_identities': 'version_id,identity',
               'resources': 'version_id,name,sha256,data', 'sync_state': 'singleton,active_id'}[table]
    return [op(f'ALTER TABLE {table} RENAME TO fixture_original'),
            op(f'CREATE TABLE {table} ({columns})'),
            op(f'INSERT INTO {table} SELECT {columns} FROM fixture_original'),
            op('DROP TABLE fixture_original')]


def set_column(table, column, value, *, relax=False, name=None):
    where = '' if name is None else ' WHERE name=$p1'
    args = (value,) if name is None else (value, name)
    return (relaxed(table) if relax else []) + [op(f'UPDATE {table} SET {column}=$p0' + where, *args)]


def generate_cases():
    cases = []
    first, last = BASELINE['rows'][0]['name'], BASELINE['rows'][-1]['name']

    def add(name, operations=(), *, capture=True, python=False, overrides=None, note='', encoding=None):
        case = dict(id=name, operations=list(operations), expected_digest_overrides=overrides or {},
                    expected=dict(python_matches=python, reader_capture=capture,
                                  reader_matches=capture and python), note=note)
        if encoding is not None:
            case['database_encoding'] = encoding
        cases.append(case)

    add('all-ten-match', python=True)
    for encoding in ('UTF-16le', 'UTF-16be'):
        add('all-ten-match-' + encoding.lower(), python=True, encoding=encoding,
            note='Persisted SQLite text encoding differs from UTF-8; logical strings and BLOB payloads still match exactly.')
    add('missing-active-row', [op('DELETE FROM sync_state')], capture=False)
    add('missing-version-row', [op('DELETE FROM versions')], capture=False)
    add('missing-identity-row', [op('DELETE FROM version_identities')], capture=False)
    add('missing-resources-table', [op('DROP TABLE resources')], capture=False)
    add('missing-identity-table', [op('DROP TABLE version_identities')], capture=False)
    for label, name in [('first', first), ('last', last)]:
        add('missing-required-' + label, [op('DELETE FROM resources WHERE name=$p0', name)], capture=False)
    add('required-row-stale-version', [op('UPDATE resources SET version_id=40 WHERE name=$p0', first)], capture=False)
    add('ignored-optional-row', [op('INSERT INTO resources VALUES(41,$p0,$p1,$p2)',
        'Optional.bytes', 'deliberately-not-a-digest', blob(b'optional synthetic bytes'))], python=True)
    add('ignored-stale-duplicate-rows', relaxed('resources') + [
        op('INSERT INTO resources SELECT 40,name,sha256,data FROM resources WHERE version_id=41'),
        op('INSERT INTO resources SELECT 40,name,sha256,data FROM resources WHERE version_id=41')], python=True,
        note='Duplicate stale-version rows are outside the ten requested active slots.')
    add('active-stale-key', set_column('versions', 'catalog_key', '0' * 64))
    add('active-uppercase-key', set_column('versions', 'catalog_key', IDENTITY.key.upper()))
    for label, value in [('null', None), ('integer', 7), ('blob', blob(IDENTITY.key.encode('ascii'))),
                         ('oversize', text_repeat('x', 65))]:
        add('catalog-key-' + label, set_column('versions', 'catalog_key', value, relax=True), capture=False)
    for label, value, capture in [('null', None, False), ('empty', '', True), ('malformed', '{', True),
            ('integer', 7, False), ('blob', blob(BASELINE['identity_json'].encode('ascii')), False),
            ('oversize-characters', text_repeat('x', 4097), False), ('nonascii', '\u96ea', True)]:
        add('identity-' + label, set_column('version_identities', 'identity', value, relax=True), capture=capture)
    # Construct NUL text inside SQLite. Some providers truncate NUL-containing
    # string parameters, which would otherwise create a different test database.
    add('identity-embedded-nul-oversize', relaxed('version_identities') + [
        op('UPDATE version_identities SET identity=CAST(zeroblob(17000) AS TEXT)')], capture=False)
    add('required-name-wrong-case', [op('UPDATE resources SET name=$p0 WHERE name=$p1', first.lower(), first)], capture=False)
    for label, value, capture in [('null', None, False), ('integer', 7, False),
            ('blob', blob(BASELINE['rows'][0]['sha256'].encode('ascii')), False), ('empty', '', True),
            ('oversize', text_repeat('a', 65), False), ('uppercase', BASELINE['rows'][0]['sha256'].upper(), True)]:
        add('recorded-sha-' + label, set_column('resources', 'sha256', value, relax=True, name=first), capture=capture)
    for label, value in [('null', None), ('text', 'synthetic text, not a BLOB'), ('integer', 7), ('empty', blob(b''))]:
        add('payload-' + label, set_column('resources', 'data', value, relax=True, name=first), capture=False)
    for label, size, capture in [('maximum-exact', MAXIMUM_BYTES, True), ('maximum-plus-one', MAXIMUM_BYTES + 1, False)]:
        payload = repeated(0xa5, size)
        add('payload-' + label, [op('UPDATE resources SET data=$p0,sha256=$p1 WHERE name=$p2',
            payload, payload['sha256'], first)], capture=capture, python=capture,
            overrides={TABLES[0]: payload['sha256']})
    add('payload-tampered', set_column('resources', 'data', blob(b'tampered synthetic bytes'), name=first))
    add('recorded-sha-mismatch', set_column('resources', 'sha256', '0' * 64, name=first))
    for label, value in [('text', '41'), ('real', 41.0)]:
        add('active-id-' + label, set_column('sync_state', 'active_id', value, relax=True), capture=False, python=True,
            note='Python SQLite equality/fetchone accepts this non-integer active ID; reader requires SQLite integer storage.')
    for table in ('sync_state', 'versions', 'version_identities'):
        add('duplicate-' + table.replace('_', '-'), relaxed(table) + [op(f'INSERT INTO {table} SELECT * FROM {table}')],
            capture=False, python=True, note='Original Python fetchone accepts one valid joined row; reader rejects an ambiguous active join.')
    for label, name in [('first', first), ('last', last)]:
        add('duplicate-required-' + label, relaxed('resources') + [
            op('INSERT INTO resources SELECT * FROM resources WHERE name=$p0', name)], capture=False, python=True,
            note='Original Python fetchone accepts the first valid resource; reader rejects multiple matching rows.')
    for table in ('resources', 'version_identities'):
        add('view-' + table.replace('_', '-'), [op(f'ALTER TABLE {table} RENAME TO fixture_backing'),
            op(f'CREATE VIEW {table} AS SELECT * FROM fixture_backing')], capture=False, python=True,
            note='Original Python SELECT accepts a view; reader requires ordinary main-database tables.')
    add('schema-table-wrong-case', [op('ALTER TABLE resources RENAME TO fixture_backing'),
        op('ALTER TABLE fixture_backing RENAME TO RESOURCES')], capture=False, python=True,
        note='Original Python SQLite identifier lookup is case-insensitive; reader requires exact ordinary-table schema names.')
    assert len(cases) == 52 and len({case['id'] for case in cases}) == len(cases)
    return cases


def create_database(path, case):
    with closing(sqlite3.connect(path)) as db, db:
        encoding = case.get('database_encoding', 'UTF-8')
        assert encoding in ('UTF-8', 'UTF-16le', 'UTF-16be')
        # SQLite fixes the file encoding when its first table is created.
        db.execute("PRAGMA main.encoding='" + encoding + "'")
        for sql in SCHEMA_SQL:
            db.execute(sql)
        db.execute('INSERT INTO versions VALUES (?,?)', (ACTIVE_ID, BASELINE['catalog_key']))
        db.execute('INSERT INTO version_identities VALUES (?,?)', (ACTIVE_ID, BASELINE['identity_json']))
        db.execute('INSERT INTO sync_state VALUES (1,?)', (ACTIVE_ID,))
        for row in BASELINE['rows']:
            db.execute('INSERT INTO resources VALUES (?,?,?,?)',
                       (ACTIVE_ID, row['name'], row['sha256'], materialize(row['data'])))
        for operation in case['operations']:
            db.execute(operation['sql'], {f'p{index}': materialize(value)
                       for index, value in enumerate(operation['parameters'])})


def execute_reference(case):
    with tempfile.TemporaryDirectory(prefix='lala-database-read-') as directory:
        path = Path(directory) / 'synthetic.sqlite3'
        create_database(path, case)
        assert path.is_file() and not path.is_symlink()
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            assert db.execute('PRAGMA main.encoding').fetchone() == (case.get('database_encoding', 'UTF-8'),)
        before = sha(path.read_bytes())
        digests = {row['name']: row['sha256'] for row in BASELINE['expected_digests']}
        digests.update(case['expected_digest_overrides'])
        runtime = SimpleNamespace(catalog_identity=IDENTITY, source_sha256=digests)
        result = REFERENCE(path, runtime)
        assert type(result) is bool and result == case['expected']['python_matches'], (case['id'], result)
        assert sha(path.read_bytes()) == before, 'Read-only source changed a temporary fixture database'
        # The only result attributed to Python is the result of its actual full function.
        case['expected']['python_matches'] = result


def compressed(raw):
    stream = io.BytesIO()
    with gzip.GzipFile(filename='', fileobj=stream, mode='wb', mtime=0, compresslevel=9) as handle:
        handle.write(raw)
    return stream.getvalue()


def csharp(cases, packed, decoded):
    ids = '\n'.join('        yield return new object[] { ' + json.dumps(case['id']) + ' };' for case in cases)
    return f'''// Generated by generate_database_read_vectors.py. Real SQLite and unchanged full Python source.
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace Lala.Core.Tests.Resources;

public static class DatabaseReadPythonVectors
{{
    public const string CompressedSha256 = "{sha(packed)}";
    public const string DecodedSha256 = "{sha(decoded)}";
    public const int CaseCount = {len(cases)};
    private static readonly Lazy<JsonDocument> Document = new(Load);
    public static JsonElement Root => Document.Value.RootElement;
    public static JsonElement Case(string id) => Root.GetProperty("cases").EnumerateArray()
        .Single(row => row.GetProperty("id").GetString() == id);

    // Scalar IDs only: discovery never inflates fixtures or materializes payloads.
    public static IEnumerable<object[]> Cases()
    {{
{ids}
    }}

    private static JsonDocument Load()
    {{
        using Stream stream = typeof(DatabaseReadPythonVectors).Assembly.GetManifestResourceStream(
            "Lala.Core.Tests.Resources.DatabaseRead.Fixtures.database-read.json.gz")
            ?? throw new InvalidOperationException("Missing retained database-read Python fixture.");
        using var packed = new MemoryStream();
        stream.CopyTo(packed);
        byte[] compressed = packed.ToArray();
        if (Convert.ToHexStringLower(SHA256.HashData(compressed)) != CompressedSha256)
            throw new InvalidOperationException("Database-read compressed fixture hash mismatch.");
        using var input = new MemoryStream(compressed, writable: false);
        using var gzip = new GZipStream(input, CompressionMode.Decompress);
        using var output = new MemoryStream();
        gzip.CopyTo(output);
        byte[] decoded = output.ToArray();
        if (Convert.ToHexStringLower(SHA256.HashData(decoded)) != DecodedSha256)
            throw new InvalidOperationException("Database-read decoded fixture hash mismatch.");
        return JsonDocument.Parse(decoded);
    }}
}}
'''.encode('utf-8')


def artifacts():
    cases = generate_cases()
    for case in cases:
        execute_reference(case)
    output = dict(schema_version=1,
        scope='Real temporary SQLite reads and structural matching only; no official authority or runtime admission.',
        source_sha256=SOURCE_HASHES,
        extracted_source=dict(path=SOURCE, function=FUNCTION.name, first_line=FUNCTION.lineno,
            last_line=FUNCTION.end_lineno, ast_sha256=sha(ast.dump(FUNCTION, include_attributes=False).encode('utf-8')),
            includes_filesystem_preflight=True, includes_function_imports=True, body_rewritten=False),
        identity_inputs=IDENTITY_INPUTS, required_tables=list(TABLES), maximum_payload_bytes=MAXIMUM_BYTES,
        schema_sql=SCHEMA_SQL, baseline=BASELINE, cases=cases)
    decoded = (canonical(output) + '\n').encode('utf-8')
    packed = compressed(decoded)
    divergences = [case['id'] for case in cases
                   if case['expected']['python_matches'] != case['expected']['reader_matches']]
    evidence = dict(schema_version=1, case_count=len(cases),
        verified_database_encodings=sorted({case.get('database_encoding', 'UTF-8') for case in cases}),
        python_matching_cases=sum(case['expected']['python_matches'] for case in cases),
        reader_capture_cases=sum(case['expected']['reader_capture'] for case in cases),
        reader_matching_cases=sum(case['expected']['reader_matches'] for case in cases),
        intentional_reader_stricter_cases=divergences, source_sha256=SOURCE_HASHES,
        generator_sha256=sha(Path(__file__).read_bytes().replace(b'\r\n', b'\n')),
        source_line_endings='CRLF normalized to LF only; bare CR is preserved',
        synthetic_input=dict(path=MATCH_FIXTURE, compressed_sha256=sha(MATCH_PACKED), decoded_sha256=sha(MATCH_DECODED)),
        fixture=dict(name='database-read.json.gz', compressed_bytes=len(packed), compressed_sha256=sha(packed),
                     decoded_bytes=len(decoded), decoded_sha256=sha(decoded)),
        oracle='Unchanged complete database_matches_runtime AST; actual pathlib and stdlib sqlite3 temporary files, read-only URI and transaction; real OfficialCatalogIdentity.',
        controlled_import='Only bundle_runtime_1275._REQUIRED_TABLES is supplied from its source literal; no function statements or globals are ported.',
        reader_expectations='Explicit C# reader contract expectations, not outputs of the Python function or proof of parity. reader_matches requires successful capture and the actual Python matching result.',
        checks=['Full source executed once for every case', 'All original Python booleans verified',
                'Persisted SQLite encoding verified through a separate read-only connection for every case',
                'Temporary database content unchanged after every read-only source call',
                'Temporary directories and SQLite files removed after each case',
                'Compact operation recipes; 16 MiB boundary values are not embedded in JSON'],
        excluded=['official manifest authenticity', 'binary table schema validity', 'runtime activation',
                  'C# execution', 'provider dishonest-behavior emulation', 'concurrent writer interleavings'])
    return {
        HERE / 'Fixtures/database-read.json.gz': packed,
        HERE / 'Fixtures/evidence.json': (json.dumps(evidence, ensure_ascii=True, sort_keys=True, indent=2) + '\n').encode(),
        HERE / 'DatabaseReadPythonVectors.cs': csharp(cases, packed, decoded),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Execute all temporary SQLite cases and require exact retained artifacts.')
    args = parser.parse_args()
    result = artifacts()
    if args.check:
        for path, expected in result.items():
            if not path.exists() or path.read_bytes() != expected:
                raise SystemExit('Database-read fixture differs; regenerate and review: ' + str(path.relative_to(ROOT)))
        print('Database-read real-SQLite Python fixtures are current; compressed and decoded bytes match exactly.')
    else:
        for path, data in result.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            print(str(path.relative_to(ROOT)) + ': ' + str(len(data)) + ' bytes')


if __name__ == '__main__':
    main()
