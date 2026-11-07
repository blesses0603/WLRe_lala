"""Retain actual decorated Python Smith/Stage parsers. Synthetic bytes only, no I/O activation."""
import base64
import hashlib
import json
from pathlib import Path
import random
import struct
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'dotnet/Lala.Core.Tests/TestSupport'))
from gzip_json_fixture import gzip_json_bytes
from wlre.services import parser_diagnostics as diagnostics
from wlre.services.world.preview_1275 import parse_smith_1275
from wlre.services.world.smith_candidate import parse_smith_candidate, parse_smith_records, mark_timed_recipes
from wlre.services.instance_catalog import parse_stages


def smith(item=123, material_count=5, time_id=0, value=1):
    raw = bytearray(33)
    struct.pack_into('<HHBHB', raw, 0, item, value * 257, value, value * 257, value)
    for slot in range(5):
        struct.pack_into('<HB', raw, 8 + slot * 3, 20 + slot, value)
    struct.pack_into('<BHBBHBBB', raw, 23, material_count, value * 257, value, value,
                     time_id, value, value, value)
    return bytes(raw)


def stage(key=456, value=1):
    raw = bytearray([value] * 76)
    struct.pack_into('<H', raw, 0, key)
    return bytes(raw)


def table(*rows):
    return struct.pack('<i', len(rows)) + b''.join(rows)


def candidate(key, row):
    return struct.pack('<H', key) + row


def materialize(spec):
    if isinstance(spec, bytes): return spec
    count = spec['count']
    kind = spec['kind']
    if kind == 'smith33-rows': return table(*(smith(i + 1) for i in range(count)))
    if kind == 'candidate-rows': return table(*(candidate(i + 1, smith()) for i in range(count)))
    if kind == 'reviewed-rows': return table(*(candidate(i + 1, smith(time_id=i % 2)) for i in range(count)))
    if kind == 'stage-rows': return table(*(stage(count - i) for i in range(count)))
    if kind == 'stage-repeat': return table(*(stage() for _ in range(count)))
    raise AssertionError(kind)


cases = []

def add(name, mode, raw, summary=False):
    actual = materialize(raw)
    run = diagnostics.DiagnosticRun('unused-in-memory-oracle')
    token = diagnostics._run.set(run)
    result = error = failure = None
    try:
        try:
            result = {'smith33': parse_smith_1275, 'candidate': parse_smith_candidate,
                      'reviewed': parse_smith_records, 'stage': parse_stages,
                      'mark33': lambda data: mark_timed_recipes(list(parse_smith_1275(data).values()))}[mode](actual)
        except (ValueError, struct.error) as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)}
            failure = getattr(exc, 'parser_diagnostic', None)
        if summary and result is not None:
            # Covers every returned field and ordered key/row, not only the endpoints.
            digest = hashlib.sha256(json.dumps(result, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
            result = {'count': len(result), 'sha256': digest}
        cases.append(dict(name=name, mode=mode,
                          raw={'base64': base64.b64encode(raw).decode()} if isinstance(raw, bytes) else raw,
                          summary=summary, expected=result, error=error, failure=failure,
                          diagnostics=list(run.events.values())))
    finally:
        diagnostics._run.reset(token)


basic33 = table(smith(90, time_id=0, value=10), smith(1, time_id=65535, value=255))
basic35 = table(candidate(90, smith(123)), candidate(1, smith(123, time_id=1078)))
basic76 = table(stage(90, 20), stage(0, 255))
for mode, raw in [('smith33', basic33), ('candidate', basic35), ('reviewed', basic33), ('stage', basic76)]:
    add(mode + '-basic', mode, raw)
    add(mode + '-empty', mode, table())
    for cut in range(len(raw)):
        add(f'{mode}-truncated-{cut}', mode, raw[:cut])
    for count in [-2**31, -1, 1, 20000, 20001, 2**31 - 1]:
        add(f'{mode}-count-{count}', mode, struct.pack('<i', count))
    add(mode + '-trailing-byte', mode, raw + b'!')
    add(mode + '-declared-zero-with-row', mode, struct.pack('<i', 0) + raw[4:])
add('reviewed-35-basic', 'reviewed', basic35)
for cut in range(len(basic35)):
    add(f'reviewed-35-truncated-{cut}', 'reviewed', basic35[:cut])
for item in [0, 1, 65535]:
    for mode in ['smith33', 'reviewed']:
        add(f'{mode}-item-{item}', mode, table(smith(item)))
for value in [0, 1, 127, 128, 254, 255]:
    add(f'smith33-fields-{value}', 'smith33', table(smith(value= value)))
    add(f'stage-fields-{value}', 'stage', table(stage(65535, value)))
for count in [0, 1, 4, 5, 6, 255]:
    for mode in ['smith33', 'reviewed']:
        add(f'{mode}-material-count-{count}', mode, table(smith(material_count=count)))
    add(f'candidate-material-count-{count}', 'candidate', table(candidate(7, smith(material_count=count))))
for mode in ['smith33', 'reviewed']:
    add(mode + '-duplicate-item', mode, table(smith(), smith()))
    add(mode + '-late-zero-item', mode, table(smith(), smith(0)))
    add(mode + '-source-order', mode, table(*(smith(key) for key in [65535, 90, 1, 65534])))
for mode in ['candidate', 'reviewed']:
    add(mode + '-duplicate-key', mode, table(candidate(3, smith()), candidate(3, smith(0))))
    add(mode + '-zero-key', mode, table(candidate(0, smith(0))))
    add(mode + '-late-zero-key', mode, table(candidate(3, smith()), candidate(0, smith())))
    add(mode + '-zero-item', mode, table(candidate(3, smith(0))))
    add(mode + '-late-zero-item-35', mode, table(candidate(3, smith()), candidate(5, smith(0))))
    add(mode + '-duplicate-item-allowed', mode, basic35)
    add(mode + '-key-source-order', mode, table(*(candidate(key, smith()) for key in [65535, 90, 1, 65534])))
for slot in range(5):
    raw = bytearray(smith(material_count=0)); struct.pack_into('<H', raw, 8 + slot * 3, 0)
    add(f'smith33-zero-material-slot-{slot}', 'smith33', table(raw))
    raw = bytearray(smith()); struct.pack_into('<HB', raw, 8 + slot * 3, 65535, 0)
    add(f'smith33-zero-material-amount-{slot}', 'smith33', table(raw))
raw = bytearray(smith()); raw[8:23] = bytes(15)
add('smith33-all-materials-zero', 'smith33', table(raw))
raw = bytearray(smith()); raw[8:23] = struct.pack('<HB', 23, 0) * 5
add('smith33-duplicate-materials-kept', 'smith33', table(raw))
for value in [0, 1, 65535]:
    for mode in ['mark33', 'reviewed']:
        add(f'{mode}-time-{value}', mode, table(smith(time_id=value)))
add('mark33-empty', 'mark33', table())
add('stage-source-order', 'stage', table(*(stage(key) for key in [65535, 90, 0, 1, 65534])))
add('stage-duplicate', 'stage', table(stage(), stage()))
add('stage-late-duplicate', 'stage', table(stage(0), stage(), stage(0)))
for cut in range(76):
    add(f'stage-duplicate-truncated-{cut}', 'stage', struct.pack('<i', 2) + stage() + stage()[:cut])
add('stage-duplicate-before-trailing', 'stage', table(stage(), stage()) + b'!')
add('stage-count-before-trailing', 'stage', {'kind': 'stage-repeat', 'count': 20001})
# Boundary recipes avoid retaining large JSON DOMs. Full Python result hashes retain all fields/order.
add('smith33-maximum-count', 'smith33', {'kind': 'smith33-rows', 'count': 20000}, summary=True)
add('candidate-maximum-count', 'candidate', {'kind': 'candidate-rows', 'count': 20000}, summary=True)
add('reviewed-maximum-count', 'reviewed', {'kind': 'reviewed-rows', 'count': 20000}, summary=True)
add('stage-maximum-count', 'stage', {'kind': 'stage-rows', 'count': 20000}, summary=True)
add('smith33-excess-count', 'smith33', {'kind': 'smith33-rows', 'count': 20001})
add('candidate-excess-count', 'candidate', {'kind': 'candidate-rows', 'count': 20001})
add('reviewed-excess-count', 'reviewed', {'kind': 'candidate-rows', 'count': 20001})
# Seeded row values exercise all retained fields and all intentionally ignored Stage bytes.
rng = random.Random(12753576)
for index in range(40):
    keys = rng.sample(range(1, 65536), rng.randrange(1, 12))
    rows33 = []
    for key in keys:
        row = bytearray(rng.randbytes(33)); struct.pack_into('<H', row, 0, key); row[23] = rng.randrange(6)
        rows33.append(bytes(row))
    add(f'seeded-smith33-{index}', 'smith33', table(*rows33))
    add(f'seeded-reviewed35-{index}', 'reviewed', table(*(candidate(key, row) for key, row in zip(keys, rows33))))
    rows76 = []
    for key in keys:
        row = bytearray(rng.randbytes(76)); struct.pack_into('<H', row, 0, key); rows76.append(bytes(row))
    add(f'seeded-stage-{index}', 'stage', table(*rows76))

# Discovery index contains bounded scalar arguments, never data or JsonElement.
groups, current, current_size = [], [], 0
for case in cases:
    size = len(json.dumps(case, ensure_ascii=True, separators=(',', ':')))
    if current and (current_size + size > 1_000_000 or len(current) >= 100):
        groups.append(current); current, current_size = [], 0
    current.append(case); current_size += size
if current: groups.append(current)
output = Path(__file__).with_name('Fixtures'); output.mkdir(exist_ok=True)
references = []
for index, rows in enumerate(groups):
    payload = json.dumps(rows, ensure_ascii=True, separators=(',', ':')).encode()
    packed = gzip_json_bytes(payload.decode())
    assert len(packed) <= 500_000, (index, len(packed))
    assert len(payload) <= 32 * 1024 * 1024
    name = f'smith-stage-{index:02}.json.gz'; (output / name).write_bytes(packed)
    references.append((name, hashlib.sha256(packed).hexdigest(), hashlib.sha256(payload).hexdigest()))
sources = ['wlre/services/world/preview_1275.py', 'wlre/services/world/smith_candidate.py',
           'wlre/services/instance_catalog.py', 'wlre/network/wire.py', 'wlre/services/parser_diagnostics.py']
lines = ['// Generated by generate_smith_stage_vectors.py. Actual decorated Python oracle.',
         'using System.Text.Json;', 'using Lala.Core.Tests.TestSupport;',
         'namespace Lala.Core.Tests.Catalogs.SmithStage;', 'public static class SmithStagePythonVectors', '{',
         f'    public const int VectorCount = {len(cases)};',
         '    public static IEnumerable<object[]> Sources()', '    {']
for path in sources:
    digest = hashlib.sha256((ROOT / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    lines.append(f'        yield return new object[] {{ "{path}", "{digest}" }};')
assert len({case['name'] for case in cases}) == len(cases)
lines += ['    }', '    private static readonly (string Name, int Fixture, int Row)[] CaseIndex =', '    [']
for fixture_index, rows in enumerate(groups):
    for row_index, case in enumerate(rows):
        assert 0 < len(case['name']) <= 80 and case['name'].isascii()
        lines.append(f'        ({json.dumps(case["name"])}, {fixture_index}, {row_index}),')
lines += ['    ];', '    public static IEnumerable<object[]> Cases()', '    {',
          '        foreach (var row in CaseIndex)',
          '            yield return new object[] { row.Name, row.Fixture, row.Row };',
          '    }', '    private static readonly Lazy<JsonElement>[] Fixtures =', '    [']
for name, packed_hash, payload_hash in references:
    lines.append(f'        new(() => LoadFixture("{name}", "{packed_hash}", "{payload_hash}")),')
lines += ['    ];', '    public static JsonElement ReadCase(int fixture, int row) => Fixtures[fixture].Value[row];',
          '    internal static int FixtureCaseCount => Fixtures.Sum(fixture => fixture.Value.GetArrayLength());',
          '    public static JsonElement FindCase(string name)', '    {',
          '        var row = CaseIndex.First(entry => entry.Name == name);', '        return ReadCase(row.Fixture, row.Row);', '    }',
          '    private static JsonElement LoadFixture(string name, string compressedHash, string decodedHash)', '    {',
          '        using var document = JsonDocument.Parse(GzipJson.DecodeResource(',
          '            "Lala.Core.Tests.Catalogs.SmithStage.Fixtures." + name, compressedHash, decodedHash));',
          '        return document.RootElement.Clone();', '    }', '}']
Path(__file__).with_name('SmithStagePythonVectors.cs').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
print(f'{len(cases)} actual decorated Python vectors; {len(groups)} deterministic resources')
