"""Deterministic offline synthetic fixtures evaluated by retained eve_v115.py itself.

No resource loading, diagnostics persistence, networking, activation, or Python patching.
Only this test directory is written. Duplicate-scene oracle findings are explicitly
marked as a C# fail-closed divergence, never counted as Python parity.
"""
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
from wlre.services.world.eve_v115 import derive_eve_index, derive_eve_indexes, EveDecodeError

u16 = lambda value: struct.pack('<H', value)
u32 = lambda value: struct.pack('<I', value)
NPC = 'EventData.NewNpc'
INTERACT = 'EventData.NewInteract'
NAMES = ['npc', 'door', 'mine', 'goods', 'event', 'group', 'convey', 'interact', 'battle', 'lead_event', 'lead_group']


def common(x=20, y=42, events=b'\x07', leads=b'', name=bytes(20)):
    return name + b'\xff' + u32(x) + u32(y) + bytes([len(events)]) + events + bytes([len(leads)]) + leads + b'\xfe'


def npc(index=3, ident=9001, x=20, y=42, events=b'\x07', leads=b'', moves=0, parameters=0):
    return u16(index) + common(x, y, events, leads) + u32(ident) + bytes(3) + bytes([moves]) + bytes(moves * 12) + bytes(13) + bytes([parameters]) + bytes(parameters * 103) + bytes(38)


def interact(index=8, form=3, link=1, items=((1, 3874, 2, 3),)):
    return u16(index) + bytes(20) + bytes([form]) + u16(link) + bytes([len(items)]) + b''.join(struct.pack('<BHBB', *item) for item in items)


def event(blocks=(0, 2)):
    return bytes(23) + bytes([len(blocks)]) + b''.join(bytes(22) + bytes([children]) + bytes(22 * children) for children in blocks)


def group(count=2):
    return bytes(27) + u16(count) + bytes(count * 3)


def battle(count1=2, count2=3):
    return u16(1) + common(events=bytes(range(3)), leads=bytes(range(4))) + bytes(4) + bytes([count1]) + bytes(3 * count1) + bytes([count2]) + bytes(3 * count2) + b'\0'


def scene(rows=None, version=115, model=123):
    if rows is None:
        rows = {0: [npc()], 7: [interact()]}
    data = u16(model) + u16(version)
    offsets = []
    for section in range(11):
        offsets.append(len(data))
        records = rows.get(section, [])
        data += u16(len(records)) + b''.join(records)
    return data + struct.pack('<11I', *offsets)


def container(scenes=None, header_order=None, gap=b'', tail=b''):
    if scenes is None:
        scenes = [(500, scene())]
    offset = 12 + 12 * len(scenes)
    headers = []
    data = b''
    for ident, payload in scenes:
        data += gap
        offset += len(gap)
        headers.append(struct.pack('<HHII', ident, 456, offset, len(payload)))
        data += payload
        offset += len(payload)
    if header_order is None:
        header_order = range(len(headers))
    return b'IGNORED!' + u32(len(headers)) + b''.join(headers[i] for i in header_order) + data + tail


def change(data, offset, value):
    return data[:offset] + value + data[offset + len(value):]


def expected(raw, source):
    try:
        result = derive_eve_indexes(raw) if source is None else {source: derive_eve_index(raw, source)}
        return dict(documents={key: value.decode('utf-8') for key, value in result.items()}, error=None)
    except EveDecodeError as error:
        return dict(documents=None, error=str(error))


cases = []


def add(name, raw, selections=(None, NPC, INTERACT), divergence=False):
    for source in selections:
        padding = len(raw) - len(raw.rstrip(b'\0'))
        if padding < 4096:
            padding = 0
        stored = raw[:-padding] if padding else raw
        cases.append(dict(name=name, source=source, raw=base64.b64encode(stored).decode('ascii'),
                          zero_padding=padding, divergence=divergence, **expected(raw, source)))


base = container()
add('basic', base)
add('all-empty', container([(0, scene({}))]))
all_rows = {0: [npc(moves=2, parameters=3, events=bytes(range(255)), leads=bytes(range(255)))],
            1: [u16(1) + common() + bytes(29)], 2: [u16(1) + common() + bytes(10)],
            3: [u16(1) + common() + bytes(11)], 4: [event()], 5: [group()],
            6: [bytes(35)], 7: [interact()], 8: [battle()], 9: [event((1, 0, 3))], 10: [group(4)]}
full = container([(65535, scene(all_rows))])
add('every-section-variable-arrays', full)
add('max-field-widths', container([(65535, scene({
    0: [npc(index=65535, ident=2**32-1, x=2**32-1, y=2**32-1, events=bytes(range(255)), leads=bytes(range(255)), moves=255, parameters=255)],
    7: [interact(index=65535, link=65535, items=[(255, 65535, 255, 255)] * 255)]}))]))
add('zero-index-coordinates-event-item', container([(0, scene({0: [npc(index=0, x=0, y=0, events=b'')], 7: [interact(index=0, form=1, link=0, items=[(0, 0, 0, 0)] * 2)]}))]))
add('unsorted-header-byte-numeric-lexical-order', container([(100, scene()), (2, scene()), (10, scene()), (1, scene())], [2, 0, 3, 1]))
add('opaque-prefix-gaps-tail-model-mismatch', container(gap=b'gap', tail=b'outside-any-scene'))
for form in [0, 4, 255]:
    add(f'invalid-form-{form}', container([(500, scene({7: [interact(form=form)]}))]))
add('invalid-npc-id', container([(500, scene({0: [npc(ident=0)]}))]))
add('duplicate-npc-index', container([(500, scene({0: [npc(), npc()]}))]))
add('duplicate-interaction-index', container([(500, scene({7: [interact(), interact()]}))]))
add('same-index-cross-scene', container([(1, scene()), (2, scene())]))
add('late-malformed-scene', container([(1, scene()), (2, scene(version=116))]))
add('max-skipped-nested-counts', container([(1, scene({4: [event((255,) * 255)], 5: [group(65535)], 8: [battle(255, 255)], 9: [event((255,) * 255)], 10: [group(65535)]}))]), selections=(None,))
add('duplicate-scene-override-source-bug', container([(1, scene()), (1, scene({0: [npc(ident=17), npc(index=4)]}))]), divergence=True)
for version in [0, 114, 116, 65535]:
    add(f'unsupported-version-{version}', container([(1, scene(version=version))]))
for count in [0, 4097, 2**32-1]:
    add(f'bad-scene-count-{count}', change(base, 8, u32(count)))
for offset in [0, 12, 23, len(base), 2**32-1]:
    add(f'bad-scene-offset-{offset}', change(base, 16, u32(offset)))
for size in [0, 5, len(base), 2**32-1]:
    add(f'bad-scene-size-{size}', change(base, 20, u32(size)))
for section in range(11):
    payload = scene({})
    pos = struct.unpack_from('<11I', payload, len(payload)-44)[section]
    add(f'oversized-count-{NAMES[section]}', container([(1, change(payload, pos, u16(4097)))]))
    add(f'corrupted-offset-table-{NAMES[section]}', container([(1, change(payload, len(payload)-44+4*section, u32(2**32-1)))]))
# Full-scene internal truncation, with corrected declared size, exercises actual per-read boundaries.
# Keep the discarded bytes outside the scene: acceptance must never borrow from adjacent segments.
for length in range(len(full)-24):
    add(f'every-section-truncated-{length}', change(full, 20, u32(length)), selections=(None,))
for length in range(len(base)):
    add(f'file-truncated-{length}', base[:length], selections=(None,))
for length in [0, 1, 4, 43, 45, 46]:
    add(f'offset-table-length-{length}', container([(1, scene({})[:-44] + bytes(length))]))
for tail in [bytes(2), b'\0\1']:
    add('scene-suffix-' + tail.hex(), container([(1, scene() + tail)]))
multi = container([(1, scene()), (2, scene())])
add('overlap', change(multi, 28, u32(36)))
add('unknown-selected-source', base, selections=('Other', '', 'EventData.NewNpc\n'))
add('invalid-length-before-source-validation', b'', selections=('Other',))
for size in [16*1024*1024, 16*1024*1024+1]:
    add(f'max-source-bytes-{size}', base + bytes(size-len(base)), selections=(None,))
add('maximum-scenes', container([(i, scene({})) for i in range(4096)]), selections=(None,))
for section, builder in [(0, npc), (7, interact)]:
    for count in [4096, 4097]:
        add(f'rows-per-type-{section}-{count}', container([(1, scene({section: [builder(index=i) for i in range(count)]}))]), selections=(None,))
    # Totals are independent and checked after the whole scene, just as the source does.
    for total in [20000, 20001]:
        remaining = total
        scenes = []
        while remaining:
            count = min(4096, remaining)
            scenes.append((len(scenes)+1, scene({section: [builder(index=i) for i in range(count)]})))
            remaining -= count
        add(f'total-selected-records-{section}-{total}', container(scenes))
# Both selected totals reach the independent cap simultaneously.
add('both-independent-exact-limit', container([(i + 1, scene({0: [npc(index=j) for j in range(4000)], 7: [interact(index=j) for j in range(4000)]})) for i in range(5)]), selections=(None,))
# Small seeded records exercise preservation without reimplementing expected decoding.
rng = random.Random(115)
for case in range(50):
    rows = {0: [npc(index=i, ident=rng.randrange(1, 2**32), x=rng.randrange(2**32), y=rng.randrange(2**32),
                    events=rng.randbytes(rng.randrange(15)), leads=rng.randbytes(rng.randrange(10)), moves=rng.randrange(4), parameters=rng.randrange(4)) for i in range(rng.randrange(8))],
            7: [interact(index=i, form=rng.randrange(1, 4), link=rng.randrange(65536),
                         items=[(rng.randrange(256), rng.randrange(65536), rng.randrange(256), rng.randrange(256)) for _ in range(rng.randrange(12))]) for i in range(rng.randrange(8))]}
    add(f'seeded-{case}', container([(rng.randrange(65536), scene(rows))]), selections=(None,))

source_path = ROOT / 'wlre/services/world/eve_v115.py'
source_bytes = source_path.read_bytes()
# Byte-level hashes preserve checkout line endings instead of read_text newline normalization.
source_hash = hashlib.sha256(source_bytes).hexdigest()
crlf_hash = hashlib.sha256(source_bytes.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')).hexdigest()
output_dir = Path(__file__).parent
# Bound JSON groups; large individual limit cases remain intact for exact-byte comparisons.
parts = []
current = []
current_size = 0
for row in cases:
    row_size = len(json.dumps(row, ensure_ascii=True, separators=(',', ':')))
    if current and (current_size + row_size > 1_000_000 or len(current) >= 64):
        parts.append(current)
        current = []
        current_size = 0
    current.append(row)
    current_size += row_size
if current:
    parts.append(current)
main = f'''// Generated offline by generate_eve_vectors.py. Actual retained Python oracle.
using System.Text.Json;
namespace Lala.Core.Tests.World.Eve;
public static class EvePythonVectors
{{
    public const string SourceSha256 = "{source_hash}";
    public const string SourceCrlfSha256 = "{crlf_hash}";
    public const int VectorCount = {len(cases)};
    public const int ResourceCount = {len(parts)};
    public static IEnumerable<object[]> Cases()
    {{
'''
fixture_dir = output_dir / 'Fixtures'
fixture_dir.mkdir(exist_ok=True)
methods = []
for number, rows in enumerate(parts, 1):
    payload = json.dumps(rows, ensure_ascii=True, separators=(',', ':'))
    compressed = gzip_json_bytes(payload)
    assert len(compressed) <= 500_000
    filename = f'eve-v115-{number:03}.json.gz'
    (fixture_dir / filename).write_bytes(compressed)
    compressed_hash = hashlib.sha256(compressed).hexdigest()
    decoded_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    methods.append(f'    private static string Part{number:03}() => Lala.Core.Tests.TestSupport.GzipJson.DecodeResource("Lala.Core.Tests.World.Eve.Fixtures.{filename}", "{compressed_hash}", "{decoded_hash}");')
    # Only small identifiers enter xUnit discovery/results; fixture JSON stays private.
    for row_index, row in enumerate(rows):
        assert len(row['name']) <= 80
        main += f'        yield return new object[] {{ {json.dumps(row["name"])}, {number - 1}, {row_index} }};\n'
main += '''    }
    public static JsonElement ReadCase(int fixtureIndex, int rowIndex) => Fixtures[fixtureIndex].Value[rowIndex];

    // One detached, immutable document per verified resource, loaded only when a test needs it.
    private static readonly Lazy<JsonElement>[] Fixtures =
    [
''' + ''.join(f'        new(() => ReadFixture(Part{number:03})),\n' for number in range(1, len(parts) + 1)) + '''    ];
    private static JsonElement ReadFixture(Func<string> read)
    {
        using var document = JsonDocument.Parse(read());
        return document.RootElement.Clone();
    }
''' + '\n'.join(methods) + '\n}\n'
(output_dir / 'EvePythonVectors.cs').write_text(main, encoding='utf-8', newline='\n')
print(f'{len(cases)} vectors, {len(parts)} deterministic gzip resources. Current bytes {source_hash}; CRLF bytes {crlf_hash}')
