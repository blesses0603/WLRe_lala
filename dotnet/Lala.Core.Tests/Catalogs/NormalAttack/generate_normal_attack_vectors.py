"""Retained real-Python oracle for parse_npcs/build_catalog; synthetic bytes only.

Layout cases substitute module pins ONLY inside mock.patch contexts. Public rejection
cases run unmodified pins. No downloads, official assets, runtime activation or report IO.
"""
from contextlib import ExitStack
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
from wlre.services.world import normal_attack_catalog as source, itemdata_v1

NPC_PIN = source.NPC_SHA256
ITEM_PIN = itemdata_v1.ITEMDATA_1296_SHA256
u16 = lambda value: struct.pack('<H', value)
u32 = lambda value: struct.pack('<I', value)
text = lambda value: u16(len(value.encode('utf-16-le'))) + value.encode('utf-16-le')


def npc(ident=321, name='NPC私密名😀\0', other='別名\0', kind=1, body=2, attack=3, catch=0, fields=None):
    data = bytearray(bytes([0xa5]) * 203 if fields is None else fields)
    struct.pack_into('<H', data, 1, ident)
    data[26], data[27], data[106], data[114] = catch, body, kind, attack
    return text(name) + text(other) + data


def item(ident=100, kind=5, special=140, first=123, second=987, name='ITEM私密名😀'):
    # Independent synthetic packing in the retained ItemData field order, not expected decoding.
    data = bytearray(text(name) + bytes([kind]) + text(''))
    data += struct.pack('<4H', ident, 7, 8, 9) + bytes(8)
    data += struct.pack('<HBiHBi', 25, 2, first, 26, 3, second)
    data += bytes([3, 4, 0, special]) + bytes(64)
    data += struct.pack('<BBII', 1, 2, 17, 9) + bytes(1) + u16(7) + bytes(9)
    data += struct.pack('<6H', 10023, 1, 2, 3, 4, 5)
    data += u16(2) + b'\x00\xd8'  # The ignored description is skipped, not decoded.
    data += bytes([1, 2, 3]) + bytes(2) + bytes([4, 5]) + bytes(12 + 3)
    data += struct.pack('<3H', 0, 0, 0) + bytes(4 + 24 + 5)
    data += bytes([2]) + bytes(7 + 10 + 7) + b'\x12\x34'  # Reviewed 1296 tail.
    return bytes(data)


def table(*records):
    return u32(len(records)) + b''.join(records)


cases = []


def add(name, npc_raw, item_raw=None, public=False):
    # Invoke the actual decorated source, not a reimplementation of expected values.
    run = diagnostics.DiagnosticRun('unused-in-memory-oracle')
    token = diagnostics._run.set(run)
    result = error = None
    try:
        with ExitStack() as patches:
            if not public:
                patches.enter_context(patch.object(source, 'NPC_SHA256', hashlib.sha256(npc_raw).hexdigest()))
                if item_raw is not None:
                    patches.enter_context(patch.object(itemdata_v1, 'ITEMDATA_1296_SHA256', hashlib.sha256(item_raw).hexdigest()))
            try:
                result = source.parse_npcs(npc_raw) if item_raw is None else source.build_catalog(npc_raw, item_raw)
            except (ValueError, struct.error) as failure:
                error = {'type': type(failure).__name__, 'message': str(failure)}
        # NPC observations are ported; existing ItemDataParser observation hooks are not changed.
        npc_events = [event for event in run.events.values() if event['parser'].endswith('normal_attack_catalog.parse_npcs')]
        assert len(npc_events) <= 1
        cases.append(dict(name=name, mode=('npc' if item_raw is None else 'build') + ('-public' if public else '-layout'),
                          npc=base64.b64encode(npc_raw).decode(),
                          item=None if item_raw is None else base64.b64encode(item_raw).decode(),
                          expected=result, error=error, diagnostic=npc_events[0] if npc_events else None))
    finally:
        diagnostics._run.reset(token)
    assert source.NPC_SHA256 == NPC_PIN and itemdata_v1.ITEMDATA_1296_SHA256 == ITEM_PIN


base = table(npc())
item_base = table(item())
add('basic-reviewed-fields', base)
add('basic-catalog', base, item_base)
add('empty-names-allowed', table(npc(name='', other='')))
add('nul-only-names-allowed', table(npc(name='\0\0', other='\0')))
add('bom-and-interior-nul', table(npc(name='\ufeffA\0B', other='字😀')))
add('both-max-utf16', table(npc(name='字' * 4096, other='名' * 4096)))
add('surrogate-pairs-max-utf16', table(npc(name='😀' * 2048, other='')))
add('multiple-numeric-ids', table(*(npc(ident=i) for i in [65535, 1, 10, 2])))
for value in [0, 1, 2, 127, 128, 254, 255]:
    add(f'all-byte-values-{value}', table(npc(kind=value, body=value, attack=value, catch=value)))
for offset in range(203):
    record = bytearray(npc(name='', other=''))
    record[4 + offset] = 0xff
    add(f'fixed-field-offset-{offset}', table(bytes(record)))
for count in [0, 20001, 2**32 - 1]:
    add(f'invalid-npc-count-{count}', u32(count) + npc())
add('zero-npc-id', table(npc(ident=0)))
add('duplicate-npc-id', table(npc(), npc()))
add('late-duplicate-npc-id', table(npc(ident=1), npc(ident=2), npc(ident=1)))
add('trailing-npc-byte', base + b'!')
add('trailing-whole-npc-record', base + npc(ident=123))
for length in range(len(base)):
    add(f'truncated-npc-{length}', base[:length])
for which in ['name', 'other']:
    offset = 4 if which == 'name' else 4 + len(text('NPC私密名😀\0'))
    for length in [1, 3, 8193, 8194, 65535]:
        raw = bytearray(base)
        raw[offset:offset + 2] = u16(length)
        add(f'invalid-{which}-length-{length}', bytes(raw))
    for bad in [b'\x00\xd8', b'\x00\xdc', b'\x00\xd8\x00\x00']:
        field = u16(len(bad)) + bad
        record = field + text('') if which == 'name' else text('') + field
        add(f'invalid-{which}-unicode-{bad.hex()}', table(record + npc(name='', other='')[4:]))
rng = random.Random(1296)
for case in range(48):
    records = [npc(ident=i + 1, fields=rng.randbytes(203), kind=rng.randrange(256),
                   body=rng.randrange(256), attack=rng.randrange(256), catch=rng.randrange(256),
                   name='字😀' * rng.randrange(5), other='名' * rng.randrange(5)) for i in range(rng.randrange(1, 8))]
    add(f'seeded-npc-{case}', table(*records))
for value in [-2**31, -101, -100, -1, 0, 99, 100, 101, 2**31 - 1]:
    add(f'catch-net-first-attribute-{value}', base, table(item(first=value, second=-777)))
for special in [0, 1, 139, 140, 141, 255]:
    add(f'catch-net-special-{special}', base, table(item(special=special, first=123)))
add('mixed-items', base, table(item(ident=65535, special=140, kind=255, first=-2**31),
                              item(ident=1, special=139, kind=0), item(ident=8, special=140, first=2**31 - 1)))
for length in range(len(item_base)):
    add(f'truncated-item-{length}', base, item_base[:length])
for name, raw in [('empty-item-count', u32(0) + item()), ('excess-item-count', u32(20001) + item()),
                  ('zero-item-id', table(item(ident=0))), ('duplicate-item-id', table(item(), item())),
                  ('trailing-item-byte', item_base + b'!'), ('legacy-item-missing-tail', item_base[:-2])]:
    add(name, base, raw)
add('bad-npc-after-valid-item', table(npc(ident=0)), item_base)
add('item-before-npc-error-order', table(npc(ident=0)), table(item(ident=0)))
add('maximum-npc-count', table(*(npc(ident=i, name='', other='') for i in range(1, 20001))))
add('maximum-item-count', base, table(*(item(ident=i, name='A', special=140 if i % 4 == 0 else 1) for i in range(1, 20001))))
for name, raw in [('synthetic', base), ('empty', b''), ('malformed', u32(0)), ('trailing', base + b'!')]:
    add('public-npc-' + name, raw, public=True)
for name, npcs, items in [('synthetic', base, item_base), ('both-empty', b'', b''),
                          ('malformed-npc', b'', item_base), ('malformed-item', base, b'')]:
    add('public-build-' + name, npcs, items, public=True)

# Keep gzip artifacts and generated C# below the repository's 500000-byte file boundary.
groups, current, current_size = [], [], 0
for row in cases:
    size = len(json.dumps(row, ensure_ascii=True, separators=(',', ':')))
    if current and (current_size + size > 1_000_000 or len(current) >= 128):
        groups.append(current)
        current, current_size = [], 0
    current.append(row)
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
    name = f'normal-attack-{index:02}.json.gz'
    (output / name).write_bytes(packed)
    references.append((name, hashlib.sha256(packed).hexdigest(), hashlib.sha256(payload.encode()).hexdigest()))
sources = ['wlre/services/world/normal_attack_catalog.py', 'wlre/services/world/itemdata_v1.py',
           'wlre/services/world/item_stack_rules.py', 'wlre/services/parser_diagnostics.py']
lines = ['// Generated by generate_normal_attack_vectors.py. Synthetic real-Python oracle only.',
         'using System.Text.Json;', 'using Lala.Core.Tests.TestSupport;',
         'namespace Lala.Core.Tests.Catalogs.NormalAttack;', 'public static class NormalAttackPythonVectors', '{',
         f'    public const int VectorCount = {len(cases)};',
         f'    public const string NpcPin = "{NPC_PIN}";', f'    public const string ItemPin = "{ITEM_PIN}";',
         '    public static IEnumerable<object[]> Sources()', '    {']
for path in sources:
    digest = hashlib.sha256((ROOT / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    lines.append(f'        yield return new object[] {{ "{path}", "{digest}" }};')
assert len({row['name'] for row in cases}) == len(cases)
lines += ['    }',
          '    // Only bounded identifiers enter xUnit discovery/display names; payloads stay out of theory arguments.',
          '    private static readonly (string Name, int Fixture, int Row)[] CaseIndex =', '    [']
for fixture_index, rows in enumerate(groups):
    for row_index, row in enumerate(rows):
        assert 0 < len(row['name']) <= 80 and row['name'].isascii()
        lines.append(f'        ({json.dumps(row["name"])}, {fixture_index}, {row_index}),')
lines += ['    ];', '    public static IEnumerable<object[]> Cases()', '    {',
          '        foreach (var row in CaseIndex)',
          '            yield return new object[] { row.Name, row.Fixture, row.Row };', '    }',
          '', '    // Private, immutable detached roots live for this test assembly. Each resource is',
          '    // verified/decompressed at most once, on demand, including concurrent lookups.',
          '    private static readonly Lazy<JsonElement>[] Fixtures =', '    [']
for name, packed_hash, payload_hash in references:
    lines.append(f'        new(() => LoadFixture("{name}", "{packed_hash}", "{payload_hash}")),')
lines += ['    ];', '    public static JsonElement ReadCase(int fixture, int row) => Fixtures[fixture].Value[row];',
          '    internal static int FixtureCaseCount => Fixtures.Sum(fixture => fixture.Value.GetArrayLength());',
          '    public static JsonElement FindCase(string name)', '    {',
          '        var row = CaseIndex.First(entry => entry.Name == name);',
          '        return ReadCase(row.Fixture, row.Row);', '    }',
          '    private static JsonElement LoadFixture(string name, string compressedHash, string decodedHash)', '    {',
          '        using var document = JsonDocument.Parse(GzipJson.DecodeResource(',
          '            "Lala.Core.Tests.Catalogs.NormalAttack.Fixtures." + name, compressedHash, decodedHash));',
          '        return document.RootElement.Clone();', '    }', '}']
Path(__file__).with_name('NormalAttackPythonVectors.cs').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
print(f'{len(cases)} real-Python vectors; {len(groups)} deterministic gzip resources; fixed pins restored')
