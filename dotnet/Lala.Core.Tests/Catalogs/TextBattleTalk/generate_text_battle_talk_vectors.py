"""Retain actual decorated Python TextData and battle-quote behavior, using synthetic inputs.

Only layout NPC cases mock the module pin in a bounded patch context. Production cases
leave it untouched. No official assets, runtime/storage activation, downloads or report IO.
Large boundary cases retain deterministic input recipes and a full-result digest to avoid
multi-megabyte source/resource files; expected results always come from the Python parsers.
"""
from contextlib import nullcontext
import base64
import hashlib
import json
from pathlib import Path
import random
import struct
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'dotnet/Lala.Core.Tests/TestSupport'))
from gzip_json_fixture import gzip_json_bytes
from wlre.services import parser_diagnostics as diagnostics
from wlre.services.expedition import data as text_source
from wlre.services.world import npc_battle_catalog as npc_source

PIN = npc_source.KNOWN_SHA256
MAX_TEXT_BYTES = 16 * 1024 * 1024
u32 = lambda value: struct.pack('<I', value)
i32 = lambda value: struct.pack('<i', value)
row = lambda group=1, text=100, kind=4, parameter=1, duration=5: struct.pack('<HIBHB', group, text, kind, parameter, duration)
table = lambda *records: i32(len(records)) + b''.join(records)

def text(key, value):
    raw = value.encode('utf-16-le') if isinstance(value, str) else value
    return struct.pack('<IH', key, len(raw)) + raw


def materialize(spec):
    if isinstance(spec, bytes):
        return spec
    kind = spec['kind']
    if kind == 'empty-records':
        return i32(spec['count']) + b''.join(struct.pack('<IH', i, 0) for i in range(spec['count']))
    if kind == 'zeros':
        return bytes(spec['size'])
    if kind == 'maximum-size':
        available = MAX_TEXT_BYTES - 4
        records = []
        while available:
            size = min(65534, available - 6)
            assert size >= 0 and size % 2 == 0
            records.append(text(len(records), '字' * (size // 2)))
            available -= size + 6
        return table(*records)
    raise AssertionError(kind)


def describe(spec):
    return {'base64': base64.b64encode(spec).decode()} if isinstance(spec, bytes) else spec


def summarize_text(result):
    digest = hashlib.sha256()
    # Every key and every UTF-16 code unit, in source order, participates in this digest.
    for key, value in result.items():
        raw = value.encode('utf-16-le')
        digest.update(struct.pack('<II', key, len(raw)))
        digest.update(raw)
    keys = list(result)
    return dict(count=len(result), keys_sha256=hashlib.sha256(b''.join(u32(key) for key in keys)).hexdigest(),
                values_sha256=digest.hexdigest(), first_key=keys[0], last_key=keys[-1])


cases = []

def add(name, mode, raw, text_raw=None, summary=False):
    actual = materialize(raw)
    current_text = None if text_raw is None else materialize(text_raw)
    run = diagnostics.DiagnosticRun('unused-in-memory-oracle')
    token = diagnostics._run.set(run)
    result = error = failure = None
    try:
        with (patch.object(npc_source, 'KNOWN_SHA256', hashlib.sha256(actual).hexdigest())
              if mode.endswith('-layout') else nullcontext()):
            try:
                if mode == 'text':
                    result = text_source.parse_text_data(actual)
                elif mode.startswith('parse-'):
                    result = npc_source.parse_known_battle_talk(actual)
                else:
                    result = npc_source.build_catalog(actual, current_text)
            except (ValueError, struct.error) as exc:
                error = {'type': type(exc).__name__, 'message': str(exc)}
                failure = getattr(exc, 'parser_diagnostic', None)
        if result is not None:
            result = (summarize_text(result) if summary else result) if mode == 'text' else [
                {'group': group, 'rows': rows} for group, rows in result.items()]
        cases.append(dict(name=name, mode=mode, raw=describe(raw),
                          text=None if text_raw is None else describe(text_raw), summary=summary,
                          expected=result, error=error, failure=failure, diagnostics=list(run.events.values())))
    finally:
        diagnostics._run.reset(token)
    assert npc_source.KNOWN_SHA256 == PIN


basic_text = table(text(100, '台詞私密甲😀\0'), text(101, '台詞私密乙'))
basic_npc = table(row(), row(text=101, kind=3, parameter=50))
add('text-basic', 'text', basic_text)
for name, value in [('empty', ''), ('nul-only', '\0\0'), ('embedded-nul', '甲\0乙\0'),
                    ('bom', '\ufeff甲\ufffe'), ('non-bmp', '𠀀😀'), ('ascii', 'abc'), ('newline', 'a\r\nb'),
                    ('over-old-8192-limit', '字' * 4097), ('maximum-even-length', '字' * 32767),
                    ('maximum-surrogate-pairs', '😀' * 16383 + '甲')]:
    add('text-' + name, 'text', table(text(0, value)))
add('text-key-maximum', 'text', table(text(2**32 - 1, '最大')))
add('text-key-source-order', 'text', table(*(text(key, str(key)) for key in [2**32 - 1, 0, 91, 2])))
for count in [-2**31, -1, 0, 1, 1000000, 1000001, 2**31-1]:
    add('text-count-' + str(count), 'text', i32(count) + b'!')
for cut in range(len(basic_text)):
    add(f'text-truncated-{cut}', 'text', basic_text[:cut])
for cut in range(len(basic_npc)):
    add(f'npc-truncated-{cut}', 'parse-layout', basic_npc[:cut])
for size in [1, 3, 65533, 65535]:
    add(f'text-odd-length-{size}', 'text', i32(1) + struct.pack('<IH', 7, size) + b'A')
for bad in [b'\x00\xd8', b'\x00\xdc', b'\x00\xd8\x00\x00', b'\x00\xdc\x00\xd8']:
    add('text-invalid-unicode-' + bad.hex(), 'text', table(text(1, bad)))
add('text-duplicate-key', 'text', table(text(9, '甲'), text(9, '乙')))
add('text-late-duplicate-key-zero', 'text', table(text(0, ''), text(1, '乙'), text(0, '丙')))
add('text-duplicate-before-read', 'text', table(text(1, '甲'), struct.pack('<IH', 1, 65534)))
add('text-trailing-byte', 'text', basic_text + b'!')
add('text-trailing-record', 'text', basic_text + text(99, '額外'))
add('text-maximum-count', 'text', {'kind': 'empty-records', 'count': 1000000}, summary=True)
add('text-maximum-size', 'text', {'kind': 'maximum-size'}, summary=True)
add('text-oversized', 'text', {'kind': 'zeros', 'size': MAX_TEXT_BYTES + 1})
add('text-maximum-size-invalid-count', 'text', {'kind': 'zeros', 'size': MAX_TEXT_BYTES})
add('npc-basic', 'parse-layout', basic_npc)
add('npc-source-order', 'parse-layout', table(row(90, 9), row(1, 8), row(90, 7), row(65535, 6), row(1, 5)))
add('npc-duplicate-rows-allowed', 'parse-layout', table(row(), row()))
for group in [0, 1, 255, 256, 65535]:
    add(f'npc-group-{group}', 'parse-layout', table(row(group=group)))
for text_id in [0, 1, 65535, 65536, 2**32 - 1]:
    add(f'npc-text-id-{text_id}', 'parse-layout', table(row(text=text_id)))
for value in [0, 1, 127, 128, 254, 255]:
    add(f'npc-byte-values-{value}', 'parse-layout', table(row(kind=value, duration=value)))
for value in [0, 1, 255, 256, 65535]:
    add(f'npc-parameter-{value}', 'parse-layout', table(row(parameter=value)))
for count in [0, 1, 2, 20000, 20001, 2**32 - 1]:
    add(f'npc-count-mismatch-{count}', 'parse-layout', u32(count) + row())
for count in [254, 255, 256]:
    add(f'npc-rows-per-group-{count}', 'parse-layout', table(*(row(text=i + 1) for i in range(count))))
add('npc-many-groups-255-rows', 'parse-layout', table(*(row(group=i // 255 + 1, text=i + 1) for i in range(20000))))
add('npc-maximum-distinct-groups', 'parse-layout', table(*(row(group=i + 1, text=i + 1) for i in range(20000))))
add('npc-excess-record-count', 'parse-layout', table(*(row(group=i // 255 + 1, text=i + 1) for i in range(20001))))
add('npc-trailing-byte', 'parse-layout', basic_npc + b'!')
add('npc-trailing-row', 'parse-layout', basic_npc + row())
add('npc-late-zero-group', 'parse-layout', table(row(), row(group=0)))
add('npc-late-zero-text', 'parse-layout', table(row(), row(text=0)))
add('build-basic', 'build-layout', basic_npc, basic_text)
add('build-empty-text-valid', 'build-layout', basic_npc, table(text(100, ''), text(101, '\0')))
add('build-missing-reference', 'build-layout', basic_npc, table(text(100, '甲')))
add('build-unrelated-text-valid', 'build-layout', basic_npc, table(text(999, '額外'), text(101, '乙'), text(100, '甲')))
add('build-npc-before-text-failure', 'build-layout', table(row(group=0)), b'')
add('build-text-before-missing-reference', 'build-layout', table(row(text=999)), table(text(100, b'\x00\xd8')))
for cut in range(len(basic_text)):
    add(f'build-text-truncated-{cut}', 'build-layout', basic_npc, basic_text[:cut])
for name, raw in [('synthetic', basic_npc), ('empty', b''), ('malformed', u32(0)), ('trailing', basic_npc + b'!')]:
    add('public-parse-' + name, 'parse-public', raw)
    add('public-build-' + name, 'build-public', raw, b'')
rng = random.Random(1296)
for case in range(48):
    keys = rng.sample(range(1, 1000), rng.randint(1, 10))
    text_records = [text(key, rng.choice(['', '\0', '字😀', '\ufeff甲\0'])) for key in keys]
    rng.shuffle(text_records)
    npc_records = [row(rng.randint(1, 10), rng.choice(keys), rng.randrange(256), rng.randrange(65536), rng.randrange(256))
                   for _ in range(rng.randint(1, 24))]
    add(f'seeded-text-{case}', 'text', table(*text_records))
    add(f'seeded-build-{case}', 'build-layout', table(*npc_records), table(*text_records))

# Compressed resources and generated C# remain below the repository's 500000-byte file cap.
groups, current, current_size = [], [], 0
for case in cases:
    size = len(json.dumps(case, ensure_ascii=True, separators=(',', ':')))
    if current and (current_size + size > 1_000_000 or len(current) >= 100):
        groups.append(current)
        current, current_size = [], 0
    current.append(case)
    current_size += size
if current:
    groups.append(current)
output = Path(__file__).with_name('Fixtures')
output.mkdir(exist_ok=True)
references = []
for index, rows in enumerate(groups):
    payload = json.dumps(rows, ensure_ascii=True, separators=(',', ':'))
    packed = gzip_json_bytes(payload)
    assert len(packed) <= 500_000
    assert len(payload.encode()) <= 32 * 1024 * 1024
    name = f'text-battle-talk-{index:02}.json.gz'
    (output / name).write_bytes(packed)
    references.append((name, hashlib.sha256(packed).hexdigest(), hashlib.sha256(payload.encode()).hexdigest()))
sources = ['wlre/services/expedition/data.py', 'wlre/services/world/npc_battle_catalog.py',
           'wlre/network/wire.py', 'wlre/services/parser_diagnostics.py']
lines = ['// Generated by generate_text_battle_talk_vectors.py. Actual decorated Python oracle.',
         'using System.Text.Json;', 'using Lala.Core.Tests.TestSupport;',
         'namespace Lala.Core.Tests.Catalogs.TextBattleTalk;', 'public static class TextBattleTalkPythonVectors', '{',
         f'    public const int VectorCount = {len(cases)};', f'    public const string NpcPin = "{PIN}";',
         '    public static IEnumerable<object[]> Sources()', '    {']
for path in sources:
    digest = hashlib.sha256((ROOT / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    lines.append(f'        yield return new object[] {{ "{path}", "{digest}" }};')
assert len({case['name'] for case in cases}) == len(cases)
lines += ['    }', '    // Discovery receives short scalar IDs only, never JsonElement, payloads or errors.',
          '    private static readonly (string Name, int Fixture, int Row)[] CaseIndex =', '    [']
for fixture_index, rows in enumerate(groups):
    for row_index, case in enumerate(rows):
        assert 0 < len(case['name']) <= 80 and case['name'].isascii()
        lines.append(f'        ({json.dumps(case["name"])}, {fixture_index}, {row_index}),')
lines += ['    ];', '    public static IEnumerable<object[]> Cases()', '    {',
          '        foreach (var row in CaseIndex)', '            yield return new object[] { row.Name, row.Fixture, row.Row };',
          '    }', '    private static readonly Lazy<JsonElement>[] Fixtures =', '    [']
for name, packed_hash, payload_hash in references:
    lines.append(f'        new(() => LoadFixture("{name}", "{packed_hash}", "{payload_hash}")),')
lines += ['    ];', '    public static JsonElement ReadCase(int fixture, int row) => Fixtures[fixture].Value[row];',
          '    internal static int FixtureCaseCount => Fixtures.Sum(fixture => fixture.Value.GetArrayLength());',
          '    public static JsonElement FindCase(string name)', '    {',
          '        var row = CaseIndex.First(entry => entry.Name == name);', '        return ReadCase(row.Fixture, row.Row);', '    }',
          '    private static JsonElement LoadFixture(string name, string compressedHash, string decodedHash)', '    {',
          '        using var document = JsonDocument.Parse(GzipJson.DecodeResource(',
          '            "Lala.Core.Tests.Catalogs.TextBattleTalk.Fixtures." + name, compressedHash, decodedHash));',
          '        return document.RootElement.Clone();', '    }', '}']
Path(__file__).with_name('TextBattleTalkPythonVectors.cs').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
print(f'{len(cases)} actual decorated Python vectors; {len(groups)} deterministic resources; fixed pin restored')
