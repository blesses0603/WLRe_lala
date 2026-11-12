"""Synthetic bytes only. Execute retained decorated readers and actual build_catalog.

No network, activation, reviewed digest substitution, or official payload fixture.
The builder receives its real legacy ItemData parser with a supported explicit version.
"""
import ast
import base64
import hashlib
import json
from pathlib import Path
import random
import struct
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / 'dotnet/Lala.Core.Tests/TestSupport')]
from gzip_json_fixture import gzip_json_bytes
from wlre.services import parser_diagnostics as diagnostics
from wlre.services.instance_catalog import parse_dungeons, parse_cooperative_events, parse_stages
from wlre.services.expedition.data import parse_text_data
from wlre.services.world.itemdata_v1 import parse_itemdata
from wlre.services.world.instance_runtime import build_catalog

VERSION = '1286_2026_10_29_13_42_37_94'
pack = lambda fmt, *values: struct.pack('<' + fmt, *values)
table = lambda *rows: pack('i', len(rows)) + b''.join(rows)


def dungeon(id=7, kind=1, variant=1, scene=500, npc=0, awards=None, flags=(0x81, 0x81, 0x42, 0x42)):
    values = awards if awards is not None else [(10, 123, 5)] + [(0, 0, 0)] * 15
    assert len(values) == 16
    row = pack('HBBHIBBBHHHB', id, kind, variant, scene, 0xffffffff, 255, 254, 253, 65535, 65534, npc, 252)
    row += b''.join(pack('BII', *award) for award in values) + bytes(flags)
    assert len(row) == 168
    return row


def event(id=3, text=20, reward=(11, 65535, 4294967295)):
    row = pack('BIHHBHHH4H', id, text, 65535, 65534, 255, 65533, 65532, 65531, 0, 65535, 32768, 1)
    row += pack('BII', *reward)
    assert len(row) == 33
    return row


def stage(id=500, name=10, minimum=2, maximum=4):
    row = bytearray(range(76))
    struct.pack_into('<HHIH', row, 0, id, 0, name, 456)
    row[21] = maximum; row[23] = minimum
    return bytes(row)


def text(id, value):
    raw = value.encode('utf-16-le')
    return pack('IH', id, len(raw)) + raw


# Only load the independent synthetic constructor, not that generator's vector loops or patches.
source = ROOT / 'dotnet/Lala.Core.Tests/Catalogs/generate_catalog_vectors.py'
constructor = [node for node in ast.parse(source.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == 'item_record']
assert len(constructor) == 1
env = {'struct': struct}
exec(compile(ast.Module(body=constructor, type_ignores=[]), str(source), 'exec'), env)
items = table(env['item_record'](123)[0])
base = {'DungeonData_C': table(dungeon(), dungeon(7, 2, 2, npc=3), dungeon(7, 3, 3)),
        'CooperateEventData_C': table(event(), event(1)),
        'ScenesData_C': table(stage(), stage(501)),
        'TextData_C': table(text(10, '  官方場景😀\0  '), text(20, '協力事件'), text(30, 'unused')),
        'ItemData_C': items}


def materialize(raw):
    if isinstance(raw, bytes): return raw
    width = raw['width']; count = raw['count']
    row = dungeon() if width == 168 else event()
    return pack('i', count) + row * count


cases = []


def add(name, mode, raw=None, payloads=None, summary=False):
    run = diagnostics.DiagnosticRun('unused-in-memory-instance-oracle')
    actual = materialize(raw) if raw is not None else None
    inputs = dict(base if payloads is None else payloads) if mode == 'bind' else None
    metadata = None
    if inputs is not None:
        metadata = {'stages': parse_stages(inputs['ScenesData_C']),
                    'texts': parse_text_data(inputs['TextData_C']),
                    'item_ids': list(parse_itemdata(inputs['ItemData_C'], package_version=VERSION))}
    token = diagnostics._run.set(run)
    result = error = failure = None
    try:
        try:
            if mode == 'bind':
                result = build_catalog(inputs, 'synthetic-nonauthorizing-key', VERSION)
                # No provenance, key or readiness claims are part of the offline preview API.
                result = {'records': [{key: value for key, value in row.items() if key != 'catalog_key'}
                                      for row in result['records']],
                          'cooperative_events': result['cooperative_events'],
                          'declared_main_map_ids': sorted({row['map_id'] for row in result['records'] if row['kind'] == 1})}
            else:
                result = {'dungeon': parse_dungeons, 'cooperative': parse_cooperative_events}[mode](actual)
        except ValueError as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)}
            failure = getattr(exc, 'parser_diagnostic', None)
        if summary and result is not None:
            # Repeated maximum-size inputs: every field and row is checked against a single raw row.
            assert all(row == result[0] for row in result)
            result = {'count': len(result), 'row': result[0]}
        observations = list(run.events.values())
        if mode == 'bind':
            observations = [row for row in observations if row['schema'] in ('dungeon-v1', 'cooperate-v1')]
        cases.append(dict(name=name, mode=mode,
            raw=({'base64': base64.b64encode(raw).decode()} if isinstance(raw, bytes) else raw),
            inputs={key: base64.b64encode(inputs[key]).decode() for key in ('DungeonData_C', 'CooperateEventData_C')} if inputs is not None else None,
            metadata=metadata, summary=summary, expected=result, error=error,
            failure=failure, diagnostics=observations))
    finally:
        diagnostics._run.reset(token)


for mode, basic, width in [('dungeon', table(dungeon(), dungeon(0, 3, 255)), 168),
                           ('cooperative', table(event(), event(0)), 33)]:
    add(mode + '-basic', mode, basic)
    add(mode + '-empty', mode, table())
    for cut in range(len(basic)):
        add(f'{mode}-truncated-{cut}', mode, basic[:cut])
    for count in [-2**31, -1, 1, 20000, 20001, 2**31-1]:
        add(f'{mode}-count-{count}', mode, pack('i', count))
    add(mode + '-trailing-byte', mode, basic + b'!')
    add(mode + '-declared-zero-with-row', mode, pack('i', 0) + basic[4:])
    add(mode + '-maximum-count', mode, {'width': width, 'count': 20000}, summary=True)
    add(mode + '-excess-count', mode, {'width': width, 'count': 20001})
    add(mode + '-duplicate-id', mode, table(basic[4:4+width], basic[4:4+width]))
for kind in [0, 1, 2, 3, 4, 127, 255]:
    add(f'dungeon-kind-{kind}', 'dungeon', table(dungeon(kind=kind)))
for cut in range(168):
    add(f'dungeon-invalid-kind-truncated-{cut}', 'dungeon', table(dungeon(kind=0))[:4+cut])
add('dungeon-kind-before-trailing', 'dungeon', table(dungeon(kind=0)) + b'!')
for flags in [(0, 0, 0, 0), (255, 255, 255, 255)] + [tuple(1 << bit if part == slot else 0 for part in range(4)) for slot in range(4) for bit in range(8)]:
    add('dungeon-flags-' + '-'.join(map(str, flags)), 'dungeon', table(dungeon(flags=flags)))
rng = random.Random(1683316)
for index in range(40):
    rows = []
    for _ in range(rng.randrange(1, 8)):
        row = bytearray(rng.randbytes(168)); row[2] = rng.randrange(1, 4); rows.append(bytes(row))
    add(f'dungeon-seeded-{index}', 'dungeon', table(*rows))
    add(f'cooperative-seeded-{index}', 'cooperative', table(*(rng.randbytes(33) for _ in range(rng.randrange(1, 8)))))


def bind(name, dungeons=None, events=None, stages=None, texts=None, item_data=None):
    changed = dict(base)
    for key, value in [('DungeonData_C', dungeons), ('CooperateEventData_C', events), ('ScenesData_C', stages), ('TextData_C', texts), ('ItemData_C', item_data)]:
        if value is not None: changed[key] = value
    add('bind-' + name, 'bind', payloads=changed)


bind('basic')
bind('empty', dungeons=table())
bind('empty-events', dungeons=table(dungeon()), events=table())
bind('zero-event', events=table(event(0)))
bind('duplicate-event', events=table(event(), event()))
bind('zero-dungeon', dungeons=table(dungeon(id=0)))
bind('duplicate-composite', dungeons=table(dungeon(), dungeon()))
bind('different-variants', dungeons=table(dungeon(), dungeon(variant=2, scene=501)))
bind('same-id-different-kind-rejected', dungeons=table(dungeon(), dungeon(kind=3)))
bind('missing-scene', dungeons=table(dungeon(scene=999)))
bind('duplicate-main-map', dungeons=table(dungeon(), dungeon(id=8)))
bind('same-nonmain-map-allowed', dungeons=table(dungeon(kind=3), dungeon(id=8, kind=3)))
bind('named-missing-event', dungeons=table(dungeon(kind=2, variant=2, npc=255)))
bind('named-npc-does-not-wrap-to-byte', dungeons=table(dungeon(kind=2, variant=2, npc=259)))
bind('variant-one-nonzero-missing-event', dungeons=table(dungeon(kind=2, variant=1, npc=255)))
bind('unused-event-missing-name-allowed', dungeons=table(dungeon()), events=table(event(text=999)))
bind('event-name-overrides-scene', dungeons=table(dungeon(kind=2, variant=3, npc=3)))
bind('missing-name', texts=table(text(30, 'unrelated')))
bind('event-name-no-fallback', texts=table(text(10, 'scene only')))
for value, label in [('', 'empty'), (' \t\r\n', 'ascii'), ('\x1c\x1d\x1e\x1f', 'separators'),
                      ('\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000', 'unicode'),
                      ('\0', 'nul'), ('\ufeff', 'bom'), ('\u200b', 'zero-width'), ('  name😀\0  ', 'preserved')]:
    bind('name-' + label, dungeons=table(dungeon()), texts=table(text(10, value)))
for kind, variant, npc in [(1, 0, 0), (1, 255, 3), (2, 0, 0), (2, 1, 0), (2, 1, 3), (2, 2, 3), (2, 3, 0), (3, 2, 3)]:
    for minimum, maximum in [(0, 0), (0, 4), (1, 1), (1, 8), (2, 4), (2, 1), (8, 9), (255, 255)]:
        bind(f'support-{kind}-{variant}-{npc}-{minimum}-{maximum}',
             dungeons=table(dungeon(kind=kind, variant=variant, npc=npc)),
             stages=table(stage(minimum=minimum, maximum=maximum)))
for slot in [0, 7, 8, 15]:
    for award in [(0, 0, 0), (0, 1, 0), (0, 0, 1), (10, 123, 0), (11, 123, 4294967295), (10, 999, 1), (11, 999, 1), (255, 999, 0)]:
        awards = [(0, 0, 0)] * 16; awards[slot] = award
        bind(f'award-{slot+1}-{award[0]}-{award[1]}-{award[2]}', dungeons=table(dungeon(awards=awards)))
bind('follower-reward-not-item-validated', events=table(event(reward=(10, 999999, 1))))
bind('follower-empty-reward-preserved', events=table(event(reward=(0, 999999, 1))))
bind('cooperative-parser-before-dungeon', dungeons=b'', events=b'')
bind('event-identity-before-dungeon-parser', dungeons=b'', events=table(event(0)))
bind('all-dungeons-parse-before-first-binding', dungeons=table(dungeon(id=0), dungeon(kind=0)))
bind('composite-before-stage', dungeons=table(dungeon(id=0, scene=999)))
bind('stage-before-named-event', dungeons=table(dungeon(kind=2, variant=2, npc=255, scene=999)))
bind('event-before-name', dungeons=table(dungeon(kind=2, variant=2, npc=255)), texts=table(text(30, 'none')))
bind('name-before-members', dungeons=table(dungeon()), texts=table(text(30, 'none')), stages=table(stage(minimum=5, maximum=2)))
bind('members-before-awards', dungeons=table(dungeon(awards=[(0, 1, 0)] * 16)), stages=table(stage(minimum=5, maximum=2)))

groups, current, size = [], [], 0
for case in cases:
    amount = len(json.dumps(case, ensure_ascii=True, separators=(',', ':')))
    if current and (size + amount > 1_000_000 or len(current) >= 100):
        groups.append(current); current = []; size = 0
    current.append(case); size += amount
if current: groups.append(current)
output = Path(__file__).with_name('Fixtures'); output.mkdir(exist_ok=True)
references = []
for index, rows in enumerate(groups):
    payload = json.dumps(rows, ensure_ascii=True, separators=(',', ':')).encode()
    compressed = gzip_json_bytes(payload.decode())
    assert len(compressed) <= 500_000 and len(payload) <= 32 * 1024 * 1024
    name = f'instance-{index:02}.json.gz'; (output / name).write_bytes(compressed)
    references.append((name, hashlib.sha256(compressed).hexdigest(), hashlib.sha256(payload).hexdigest()))
sources = ['wlre/services/instance_catalog.py', 'wlre/services/world/instance_runtime.py',
           'wlre/network/wire.py', 'wlre/services/parser_diagnostics.py',
           'wlre/services/world/itemdata_v1.py', 'wlre/services/expedition/data.py',
           'dotnet/Lala.Core.Tests/Catalogs/generate_catalog_vectors.py']
lines = ['// Generated by generate_instance_vectors.py. Actual Python readers and builder, synthetic bytes only.',
         'using System.Text.Json;', 'using Lala.Core.Tests.TestSupport;',
         'namespace Lala.Core.Tests.Catalogs.Instance;', 'public static class InstancePythonVectors', '{',
         f'    public const int VectorCount = {len(cases)};',
         '    public static IEnumerable<object[]> Sources()', '    {']
for path in sources:
    digest = hashlib.sha256((ROOT / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    lines.append(f'        yield return new object[] {{ "{path}", "{digest}" }};')
assert len({case['name'] for case in cases}) == len(cases)
lines += ['    }', '    private static readonly (string Name, int Fixture, int Row)[] CaseIndex =', '    [']
for fixture, rows in enumerate(groups):
    for index, case in enumerate(rows):
        assert 0 < len(case['name']) <= 80 and case['name'].isascii()
        lines.append(f'        ({json.dumps(case["name"])}, {fixture}, {index}),')
lines += ['    ];', '    public static IEnumerable<object[]> Cases()', '    {',
          '        foreach (var row in CaseIndex) yield return new object[] { row.Name, row.Fixture, row.Row };',
          '    }', '    private static readonly Lazy<JsonElement>[] Fixtures =', '    [']
for name, compressed, decoded in references:
    lines.append(f'        new(() => LoadFixture("{name}", "{compressed}", "{decoded}")),')
lines += ['    ];', '    public static JsonElement ReadCase(int fixture, int row) => Fixtures[fixture].Value[row];',
          '    internal static int FixtureCaseCount => Fixtures.Sum(fixture => fixture.Value.GetArrayLength());',
          '    public static JsonElement FindCase(string name)', '    {',
          '        var row = CaseIndex.First(entry => entry.Name == name); return ReadCase(row.Fixture, row.Row);', '    }',
          '    private static JsonElement LoadFixture(string name, string compressedHash, string decodedHash)', '    {',
          '        using var document = JsonDocument.Parse(GzipJson.DecodeResource(',
          '            "Lala.Core.Tests.Catalogs.Instance.Fixtures." + name, compressedHash, decodedHash));',
          '        return document.RootElement.Clone();', '    }', '}']
Path(__file__).with_name('InstancePythonVectors.cs').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
print(f'{len(cases)} actual Python vectors; {len(groups)} deterministic fixture resources')
