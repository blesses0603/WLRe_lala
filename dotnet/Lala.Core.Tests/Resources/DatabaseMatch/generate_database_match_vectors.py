#!/usr/bin/env python3
"""Retained pure database_matches_runtime oracle, using the unchanged Python AST.

No database file, filesystem probe, SQLite connection, network, game payload, or
installed-game path is used. Only the function's original try statement runs;
its outer Path/is_symlink/is_file preflight deliberately remains out of scope.
The scripted connection accepts precisely BEGIN and the two source SELECTs.

Identity is the real OfficialCatalogIdentity, built from valid synthetic version
metadata and SHA/CRC of tiny synthetic manifest bytes. No key/hash override is
used. Those same bytes permit C# to derive its existing ManifestIdentity.

Payloads test structural matching only, not binary table/schema validity. Large
payload recipes are materialized for actual Python execution and never embedded
as multi-megabyte JSON. Source pins normalize CRLF only, never bare CR.
"""
from __future__ import annotations

import argparse
import ast
import base64
import copy
from contextlib import closing
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from wlre.services.official_resource_sync import validate_snapshot
from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision

SOURCES = (
    'wlre/services/world/resource_database.py',
    'wlre/services/world/catalog_identity.py',
    'wlre/services/world/bundle_runtime_1275.py',
    'wlre/services/official_resource_sync.py',
)
ACTIVE_SQL = ('SELECT s.active_id,v.catalog_key,i.identity FROM sync_state s '
              'JOIN versions v ON v.id=s.active_id '
              'JOIN version_identities i ON i.version_id=v.id WHERE s.singleton=1')
RESOURCE_SQL = 'SELECT sha256,data FROM resources WHERE version_id=? AND name=?'
MAXIMUM_BYTES = 16 * 1024 * 1024
ACTIVE_ID = 41


def sha(data):
    return hashlib.sha256(data).hexdigest()


def crc(data):
    return (zlib.crc32(data) & 0xffffffff).to_bytes(4, 'little').hex()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def normalized_source(path):
    return (ROOT / path).read_bytes().replace(b'\r\n', b'\n')


def source_ast(path):
    return ast.parse(normalized_source(path).decode('utf-8'), filename=path)


# Literal extraction avoids importing the full runtime and its optional adapters.
TABLES = ast.literal_eval(next(node.value for node in source_ast(SOURCES[2]).body
    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
    and target.id == '_REQUIRED_TABLES' for target in node.targets)))
assert len(TABLES) == len(set(TABLES)) == 10

FUNCTION = next(node for node in source_ast(SOURCES[0]).body
                if isinstance(node, ast.FunctionDef) and node.name == 'database_matches_runtime')
TRY = next(node for node in FUNCTION.body if isinstance(node, ast.Try))
assert TRY.lineno == 321 and TRY.end_lineno == 344
WRAPPER = ast.parse('def extracted_database_matches_runtime(path, runtime):\n    pass').body[0]
WRAPPER.body = [copy.deepcopy(TRY)]
MODULE = ast.fix_missing_locations(ast.Module(body=[WRAPPER], type_ignores=[]))
# Pin that the compiled try body was neither rewritten nor replaced by a port.
assert ast.dump(WRAPPER.body[0], include_attributes=False) == ast.dump(TRY, include_attributes=False)
CODE = compile(MODULE, SOURCES[0], 'exec')

SNAPSHOT = validate_snapshot(dict(
    schema_version=1, origin='official_pc_version_endpoint', data_ver='1.3.21', exe_version='1.3.0',
    packages={'DataPackage': '1275_2026_01_02_03_04_05_06',
              'MainPackage': '1286_2026_02_03_04_05_06_07'},
    checked_at_utc='2026-01-02T03:04:05Z', assets_ready=False))
MANIFESTS = []
for package in ('DataPackage', 'MainPackage'):
    raw = ('synthetic-database-match-manifest/' + package + '\x00\u96ea').encode('utf-8')
    MANIFESTS.append(dict(package=package, package_version=SNAPSHOT['packages'][package],
        bytes_base64=base64.b64encode(raw).decode('ascii'), crc32_le=crc(raw), sha256=sha(raw)))
IDENTITY = OfficialCatalogIdentity(SNAPSHOT['data_ver'], SNAPSHOT['exe_version'], tuple(
    PackageRevision(row['package'], row['package_version'], row['sha256'], row['crc32_le'])
    for row in MANIFESTS))
IDENTITY_JSON = canonical(IDENTITY.as_dict())
assert sha(IDENTITY_JSON.encode('ascii')) == IDENTITY.key


def blob(data):
    return dict(kind='base64', value=base64.b64encode(data).decode('ascii'), size=len(data), sha256=sha(data))


def repeated(byte, length):
    raw = bytes([byte]) * length
    return dict(kind='repeat', byte=byte, length=length, size=length, sha256=sha(raw))


def materialize(spec):
    if spec is None:
        return None
    if spec['kind'] == 'base64':
        result = base64.b64decode(spec['value'], validate=True)
    elif spec['kind'] == 'repeat':
        result = bytes([spec['byte']]) * spec['length']
    else:
        raise AssertionError('Unknown payload recipe: ' + spec['kind'])
    assert len(result) == spec['size'] and sha(result) == spec['sha256']
    return result


BASE_ROWS = []
for index, name in enumerate(TABLES):
    raw = ('synthetic-table/' + name + '/\u96ea\x00').encode('utf-8') + bytes([index, 255])
    BASE_ROWS.append(dict(active_id=ACTIVE_ID, name=name + '.bytes', sha256=sha(raw), data=blob(raw)))
BASE_DIGESTS = [dict(name=name, sha256=row['sha256']) for name, row in zip(TABLES, BASE_ROWS)]


class InertPath:
    """No filesystem-backed object is ever passed to the extracted source."""
    def resolve(self):
        return self

    def as_uri(self):
        return 'memory://synthetic-database'


class ScriptedSqliteError(Exception):
    pass


class ScriptedConnection:
    def __init__(self, case):
        self.case = case
        self.queries = []
        self.closed = False
        self.begun = False
        self.rows = {(row['active_id'], row['name']): row for row in case['rows']}
        assert len(self.rows) == len(case['rows']), 'A database key cannot have duplicate resource rows'

    def execute(self, sql, parameters=()):
        assert not self.closed
        self.queries.append(dict(sql=sql, parameters=list(parameters)))
        if sql == 'BEGIN':
            assert not self.begun and not parameters
            self.begun = True
            value = None
        elif sql == ACTIVE_SQL:
            assert self.begun and not parameters
            value = self.case['active']
        elif sql == RESOURCE_SQL:
            assert self.begun and len(parameters) == 2
            row = self.rows.get(tuple(parameters))
            value = None if row is None else (row['sha256'], materialize(row['data']))
        else:
            raise AssertionError('Unexpected SQL: ' + sql)
        return SimpleNamespace(fetchone=lambda: value)

    def close(self):
        self.closed = True


def reference(case):
    db = ScriptedConnection(case)
    connects = []

    def sqlite_connect(target, **kwargs):
        assert target == 'memory://synthetic-database?mode=ro' and kwargs == {'uri': True}
        connects.append(target)
        return db

    env = dict(hashlib=hashlib, json=json, closing=closing, _REQUIRED_TABLES=TABLES,
               sqlite3=SimpleNamespace(connect=sqlite_connect, Error=ScriptedSqliteError))
    exec(CODE, env)
    entries = case['expected_digests']
    digests = None if entries is None else {row['name']: row['sha256'] for row in entries}
    if entries is not None:
        assert len(digests) == len(entries), 'Expected digests must have unique names'
    runtime = SimpleNamespace(catalog_identity=IDENTITY, source_sha256=digests)
    result = env['extracted_database_matches_runtime'](InertPath(), runtime)
    assert type(result) is bool
    assert db.closed == bool(connects)
    assert len(connects) <= 1
    return dict(matches=result, queries=db.queries)


def generate_cases():
    cases = []

    def add(name, mutate=None):
        case = dict(id=name, active=[ACTIVE_ID, IDENTITY.key, IDENTITY_JSON],
                    expected_digests=copy.deepcopy(BASE_DIGESTS), rows=copy.deepcopy(BASE_ROWS))
        if mutate:
            mutate(case)
        case['expected'] = reference(case)
        cases.append(case)
        return case

    def replace_data(case, index, spec, *, update_record=True, update_expected=True):
        case['rows'][index]['data'] = spec
        if update_record:
            case['rows'][index]['sha256'] = spec['sha256']
        if update_expected:
            case['expected_digests'][index]['sha256'] = spec['sha256']

    add('all-ten-match')
    add('expected-reverse-order', lambda c: c['expected_digests'].reverse())
    add('expected-rotate-order', lambda c: c.update(expected_digests=c['expected_digests'][4:] + c['expected_digests'][:4]))
    add('database-reverse-row-order', lambda c: c['rows'].reverse())
    add('active-id-zero', lambda c: (c['active'].__setitem__(0, 0), [r.update(active_id=0) for r in c['rows']]))
    add('active-id-negative', lambda c: (c['active'].__setitem__(0, -1), [r.update(active_id=-1) for r in c['rows']]))
    add('active-id-large', lambda c: (c['active'].__setitem__(0, 2**60 + 7), [r.update(active_id=2**60 + 7) for r in c['rows']]))
    add('expected-null', lambda c: c.update(expected_digests=None))
    add('expected-empty', lambda c: c.update(expected_digests=[]))
    add('expected-extra', lambda c: c['expected_digests'].append(dict(name='StageMapData_C', sha256='0' * 64)))
    add('expected-extra-empty-name', lambda c: c['expected_digests'].append(dict(name='', sha256='0' * 64)))
    add('expected-wrong-case', lambda c: c['expected_digests'][0].update(name='eve'))
    add('expected-suffixed-name', lambda c: c['expected_digests'][0].update(name='Eve.bytes'))
    add('expected-replace-required-with-extra', lambda c: c['expected_digests'][-1].update(name='StageMapData_C'))
    add('active-missing', lambda c: c.update(active=None))
    for name, value in [('stale-key', '0' * 64), ('uppercase-key', IDENTITY.key.upper()), ('null-key', None)]:
        add('active-' + name, lambda c, value=value: c['active'].__setitem__(1, value))
    for name, value in [
        ('null', None), ('empty', ''), ('malformed', '{not-json}'),
        ('truncated', IDENTITY_JSON[:-1]), ('whitespace', ' ' + IDENTITY_JSON),
        ('nonascii', '\u96ea'), ('nonascii-in-json', IDENTITY_JSON.replace('1.3.21', '\u96ea')),
        ('length-4096', 'x' * 4096), ('length-4097', 'x' * 4097),
        ('reformatted-equivalent-json', json.dumps(IDENTITY.as_dict(), ensure_ascii=True, indent=2)),
        ('reordered-equivalent-json', json.dumps(IDENTITY.as_dict(), ensure_ascii=True, separators=(',', ':'))),
        ('modified-version', IDENTITY_JSON.replace('1.3.21', '1.3.22')),
        ('json-array', '[]'), ('json-null', 'null'),
    ]:
        add('identity-' + name, lambda c, value=value: c['active'].__setitem__(2, value))
    add('stale-key-precedes-null-identity', lambda c: (c['active'].__setitem__(1, '0' * 64), c['active'].__setitem__(2, None)))
    add('ignored-extra-active-resource', lambda c: c['rows'].append(dict(active_id=ACTIVE_ID, name='StageMapData_C.bytes', sha256=None, data=None)))
    add('ignored-extra-stale-resource', lambda c: c['rows'].append(dict(active_id=ACTIVE_ID - 1, name='Eve.bytes', sha256=None, data=None)))
    add('ignored-extra-empty-resource-name', lambda c: c['rows'].append(dict(active_id=ACTIVE_ID, name='', sha256=None, data=None)))
    for index, table in enumerate(TABLES):
        add('expected-missing-' + table, lambda c, i=index: c['expected_digests'].pop(i))
        add('row-missing-' + table, lambda c, i=index: c['rows'].pop(i))
        add('row-null-' + table, lambda c, i=index: c['rows'][i].update(data=None))
        add('row-recorded-sha-mismatch-' + table, lambda c, i=index: c['rows'][i].update(sha256='0' * 64))
        add('runtime-expected-sha-mismatch-' + table, lambda c, i=index: c['expected_digests'][i].update(sha256='0' * 64))
        add('row-tampered-bytes-' + table, lambda c, i=index: replace_data(c, i, blob(b'tampered'), update_record=False, update_expected=False))
        add('row-stale-version-' + table, lambda c, i=index: c['rows'][i].update(active_id=ACTIVE_ID - 1))
    add('row-name-without-bytes-suffix', lambda c: c['rows'][0].update(name='Eve'))
    add('row-name-wrong-case', lambda c: c['rows'][0].update(name='eve.bytes'))
    add('row-recorded-sha-null', lambda c: c['rows'][0].update(sha256=None))
    add('runtime-expected-sha-null', lambda c: c['expected_digests'][0].update(sha256=None))
    add('recorded-and-expected-null', lambda c: (c['rows'][0].update(sha256=None), c['expected_digests'][0].update(sha256=None)))
    add('recorded-and-expected-uppercase-sha', lambda c: (c['rows'][0].update(sha256=c['rows'][0]['sha256'].upper()), c['expected_digests'][0].update(sha256=c['expected_digests'][0]['sha256'].upper())))
    add('recorded-and-expected-empty-sha', lambda c: (c['rows'][0].update(sha256=''), c['expected_digests'][0].update(sha256='')))
    for name, index, spec in [
        ('empty-first', 0, blob(b'')), ('empty-last', 9, blob(b'')),
        ('single-byte-first', 0, blob(b'\0')), ('single-byte-last', 9, blob(b'\xff')),
        ('max-minus-one', 0, repeated(0xa5, MAXIMUM_BYTES - 1)),
        ('max-exact', 0, repeated(0xa5, MAXIMUM_BYTES)),
        ('max-plus-one', 0, repeated(0xa5, MAXIMUM_BYTES + 1)),
        ('max-exact-last', 9, repeated(0x5a, MAXIMUM_BYTES)),
        ('max-plus-one-last', 9, repeated(0x5a, MAXIMUM_BYTES + 1)),
    ]:
        add('payload-' + name, lambda c, i=index, spec=spec: replace_data(c, i, spec))
    add('payload-max-hash-mismatch', lambda c: replace_data(c, 0, repeated(0xa5, MAXIMUM_BYTES), update_record=False, update_expected=False))
    add('first-failure-precedes-last', lambda c: (c['rows'][0].update(data=None), c['rows'][-1].update(data=None)))
    add('reversed-expected-first-failure', lambda c: (c['rows'][0].update(data=None), c['rows'][-1].update(data=None), c['expected_digests'].reverse()))
    add('missing-expected-precedes-missing-active', lambda c: (c['expected_digests'].pop(), c.update(active=None)))
    add('stale-identity-precedes-missing-rows', lambda c: (c['active'].__setitem__(1, '0' * 64), c.update(rows=[])))
    add('valid-identity-no-resource-rows', lambda c: c.update(rows=[]))
    assert len({c['id'] for c in cases}) == len(cases)
    return cases


def compressed(data):
    stream = io.BytesIO()
    with gzip.GzipFile(filename='', fileobj=stream, mode='wb', mtime=0, compresslevel=9) as handle:
        handle.write(data)
    return stream.getvalue()


def csharp(cases, packed, decoded):
    ids = '\n'.join('        yield return new object[] { ' + json.dumps(case['id']) + ' };' for case in cases)
    return f'''// Generated by generate_database_match_vectors.py. Synthetic pure Python structural oracle.
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace Lala.Core.Tests.Resources;

public static class DatabaseMatchPythonVectors
{{
    public const string CompressedSha256 = "{sha(packed)}";
    public const string DecodedSha256 = "{sha(decoded)}";
    public const int CaseCount = {len(cases)};
    private static readonly Lazy<JsonDocument> Document = new(Load);
    public static JsonElement Root => Document.Value.RootElement;
    public static JsonElement Case(string id) => Root.GetProperty("cases").EnumerateArray()
        .Single(row => row.GetProperty("id").GetString() == id);

    // Scalar IDs only: xUnit discovery does not inflate or construct fixture payloads.
    public static IEnumerable<object[]> Cases()
    {{
{ids}
    }}

    private static JsonDocument Load()
    {{
        using Stream stream = typeof(DatabaseMatchPythonVectors).Assembly.GetManifestResourceStream(
            "Lala.Core.Tests.Resources.DatabaseMatch.Fixtures.database-match.json.gz")
            ?? throw new InvalidOperationException("Missing retained database-match Python fixture.");
        using var packed = new MemoryStream();
        stream.CopyTo(packed);
        byte[] compressed = packed.ToArray();
        if (Convert.ToHexStringLower(SHA256.HashData(compressed)) != CompressedSha256)
            throw new InvalidOperationException("Database-match compressed fixture hash mismatch.");
        using var input = new MemoryStream(compressed, writable: false);
        using var gzip = new GZipStream(input, CompressionMode.Decompress);
        using var output = new MemoryStream();
        gzip.CopyTo(output);
        byte[] decoded = output.ToArray();
        if (Convert.ToHexStringLower(SHA256.HashData(decoded)) != DecodedSha256)
            throw new InvalidOperationException("Database-match decoded fixture hash mismatch.");
        return JsonDocument.Parse(decoded);
    }}
}}
'''.encode('utf-8')


def artifacts():
    cases = generate_cases()
    source_hashes = {path: sha(normalized_source(path)) for path in SOURCES}
    output = dict(schema_version=1,
        scope='Pure structural matching only; excludes filesystem preflight, real SQLite I/O, runtime activation, and table schema validation.',
        source_sha256=source_hashes,
        extracted_source=dict(path=SOURCES[0], function=FUNCTION.name, first_line=TRY.lineno,
            last_line=TRY.end_lineno, ast_sha256=sha(ast.dump(TRY, include_attributes=False).encode('utf-8'))),
        identity_inputs=dict(snapshot=SNAPSHOT, manifests=MANIFESTS, canonical_json=IDENTITY_JSON, key=IDENTITY.key),
        required_tables=list(TABLES), maximum_payload_bytes=MAXIMUM_BYTES, cases=cases)
    decoded = (canonical(output) + '\n').encode('utf-8')
    packed = compressed(decoded)
    evidence = dict(schema_version=1, case_count=len(cases), matching_cases=sum(c['expected']['matches'] for c in cases),
        source_sha256=source_hashes, generator_sha256=sha(Path(__file__).read_bytes().replace(b'\r\n', b'\n')),
        source_line_endings='CRLF normalized to LF only; bare CR is preserved',
        fixture=dict(name='database-match.json.gz', compressed_bytes=len(packed), compressed_sha256=sha(packed),
                     decoded_bytes=len(decoded), decoded_sha256=sha(decoded)),
        oracle='Unchanged AST try statement from database_matches_runtime; inert path and exact-query scripted connection; real OfficialCatalogIdentity.',
        excluded=['filesystem preflight', 'SQLite I/O', 'SQL transaction implementation', 'official manifest authenticity', 'table schema validity', 'runtime activation'])
    return {
        HERE / 'Fixtures/database-match.json.gz': packed,
        HERE / 'Fixtures/evidence.json': (json.dumps(evidence, ensure_ascii=True, sort_keys=True, indent=2) + '\n').encode(),
        HERE / 'DatabaseMatchPythonVectors.cs': csharp(cases, packed, decoded),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Regenerate in memory and require exact retained artifacts.')
    args = parser.parse_args()
    result = artifacts()
    if args.check:
        for path, expected in result.items():
            if not path.exists() or path.read_bytes() != expected:
                raise SystemExit('Database-match fixture differs; regenerate and review: ' + str(path.relative_to(ROOT)))
        print('Database-match Python fixtures are current; compressed and decoded bytes match exactly.')
    else:
        for path, data in result.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            print(str(path.relative_to(ROOT)) + ': ' + str(len(data)) + ' bytes')


if __name__ == '__main__':
    main()
