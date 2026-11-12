"""Actual retained doors_1275.py oracle on deterministic synthetic v115 bytes.

No mocks, user assets, source patching, saved diagnostics, network or activation.
Only CRLF is normalized for the reviewed source pins. Discovery passes scalar IDs;
compressed fixtures and detailed diagnostics load only when each test runs.
"""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'dotnet/Lala.Core.Tests/TestSupport'))
from gzip_json_fixture import gzip_json_bytes
from wlre.services import parser_diagnostics as diagnostics
from wlre.services.world import doors_1275 as source

PINS = {
    'wlre/services/world/doors_1275.py': '012862d1ec7cd7e7361aceaba2f3375ded192189a980956863e6e58035b93ba6',
    'wlre/services/parser_diagnostics.py': 'bb9a850e5cbff7504462cc3f24f7a8d192dd0ca96207ea65e18c62c24ea9cbdc',
}
for path, expected in PINS.items():
    assert hashlib.sha256((ROOT / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() == expected, path
assert source.SOURCE_SHA256 == 'f5fc56b1d6cf7c00dd20b2f35c04b4cbc60c92ccdb6085fbe465c7e6526745ad'
u16 = lambda value: struct.pack('<H', value)
u32 = lambda value: struct.pack('<I', value)
name = lambda value=b'': value.ljust(20, b'\0')[:20]


def common(label=b'Door', events=b'\x07', leads=b'', x=123, y=456):
    return name(label) + b'\xff' + u32(x) + u32(y) + bytes([len(events)]) + events + bytes([len(leads)]) + leads + b'\xfe'


def door(index=3, label=b'Door', events=b'\x07', leads=b'', maximum=False):
    value = 2**32-1 if maximum else 100
    return u16(index) + common(label, events, leads, value, value) + struct.pack('<IIBIIIII', value, value, 255, value, value, value, value, value)


def npc(index=5, moves=0, params=0):
    return u16(index) + common(b'ignored\xff', b'\x01\x02', b'\x03\x04') + bytes(7) + bytes([moves]) + bytes(moves*12) + bytes(13) + bytes([params]) + bytes(params*103) + bytes(38)


def parameter(*, signed=False, ident=1, main=1, kind=3, style=96, value=0):
    return struct.pack('<BBHHHB' + ('i' if signed else 'I') + 'BII', ident, main, kind, style, 65535, 255, value, 255, 2**32-1, 2**31)


def event(index=7, occur=2, label=b'Touch', blocks=None):
    if blocks is None:
        blocks = [(parameter(main=5, kind=30381, value=2**32-1), [parameter(signed=True, value=-2**31)])]
    return u16(index) + bytes([occur]) + name(label) + bytes([len(blocks)]) + b''.join(data + bytes([len(results)]) + b''.join(results) for data, results in blocks)


def convey(index=96, destination=58001, label=b'Convey', x=2**32-1, y=2**31, direction=255, links=65535):
    return struct.pack('<H20sHIIBH', index, name(label), destination, x, y, direction, links)


def group(links=2):
    return bytes(27) + u16(links) + bytes(3*links)


def scene(rows=None, model=99, version=115):
    if rows is None:
        rows = {1:[door()], 4:[event()], 6:[convey()]}
    output = u16(model) + u16(version)
    offsets = []
    for i in range(11):
        offsets.append(len(output))
        records = rows.get(i, [])
        output += u16(len(records)) + b''.join(records)
    return output + struct.pack('<11I', *offsets)


def container(scenes=None, order=None, gap=b'', tail=b''):
    if scenes is None: scenes = [(60000, scene())]
    offset = 12 + len(scenes)*12
    headers, output = [], b''
    for ident, payload in scenes:
        output += gap
        offset += len(gap)
        headers.append(struct.pack('<HHII', ident, 99, offset, len(payload)))
        output += payload
        offset += len(payload)
    if order is None: order = range(len(headers))
    return b'IGNORED!' + u32(len(headers)) + b''.join(headers[i] for i in order) + output + tail


def change(raw, at, value):
    return raw[:at] + value + raw[at+len(value):]


cases = []
def add(label, raw, operation='layout', divergence=None):
    run = diagnostics.DiagnosticRun('unused-in-memory-only')
    token = diagnostics._run.set(run)
    result, error = None, None
    try:
        try:
            parsed = source.parse_verified_doors(raw) if operation == 'layout' else source.parse_doors_1275(raw)
            result = parsed if divergence is None else {'source_scene_count': len(parsed)}
        except source.DoorSourceError as caught:
            assert divergence is None
            error = str(caught)
        observed = list(run.events.values())
        assert len(observed) == 1
    finally:
        diagnostics._run.reset(token)
    padding = len(raw) - len(raw.rstrip(b'\0'))
    if padding < 4096: padding = 0
    cases.append(dict(name=label, operation=operation, raw=base64.b64encode(raw[:-padding] if padding else raw).decode(),
                      zero_padding=padding, expected=result, error=error, diagnostic=observed[0], divergence=divergence))


base = container()
add('basic', base)
add('empty', container([(0, scene({}))]))
add('max-widths-and-zero-destination', container([(65535, scene({1:[door(65535, maximum=True, events=b'\xff')],
    4:[event(255, 255)], 6:[convey(destination=0)]}))]))
add('every-variable-preceding-section', container([(1, scene({0:[npc(moves=3, params=2)],
    1:[door(leads=bytes(range(255)))], 2:[u16(0)+common(events=bytes(range(255)), leads=bytes(range(255)))+bytes(10)],
    3:[u16(0)+common(leads=b'\x01\x02')+bytes(11)], 4:[event()], 5:[group(3)], 6:[convey()]}))]))
add('npc-zero-id-and-duplicate-indices-ignored', container([(1, scene({0:[npc(), npc()], 1:[door()]}))]))
add('max-npc-variable-counts', container([(1, scene({0:[npc(moves=255, params=255)], 1:[door()]}))]))
add('max-condition-count', container([(1, scene({1:[door()], 4:[event(blocks=[(parameter(ident=255), [])]*255)]}))]))
add('max-result-count', container([(1, scene({1:[door()], 4:[event(blocks=[(parameter(ident=255), [parameter(signed=True, ident=255)]*255)])], 6:[convey()]}))]))
add('max-scenes', container([(i, scene({})) for i in range(4096)]))
add('no-player-touch', container([(1, scene({1:[door()], 4:[event(occur=1)], 6:[convey()]}))]))
add('unreferenced-and-wide-event-ids', container([(1, scene({1:[door(events=b'\x07')], 4:[event(8), event(65535)], 6:[convey()]}))]))
add('duplicate-references-and-multiple-doors', container([(1, scene({1:[door(events=b'\x07\x08\x07'), door(4)],
    4:[event(), event(8)], 6:[convey()]}))]))
add('touch-with-no-conditions', container([(1, scene({1:[door()], 4:[event(blocks=[])]}))]))
add('touch-with-no-results', container([(1, scene({1:[door()], 4:[event(blocks=[(parameter(), [])])]}))]))
add('signed-results-and-unsigned-conditions', container([(1, scene({1:[door()], 4:[event(blocks=[
    (parameter(value=2**31), [parameter(signed=True, value=-2**31), parameter(signed=True, value=2**31-1)]),
    (parameter(value=2**32-1), [parameter(signed=True, value=-1)])])], 6:[convey()]}))]))
add('matching-and-missing-and-ignored-effects', container([(1, scene({1:[door()], 4:[event(blocks=[(parameter(), [
    parameter(signed=True, main=2), parameter(signed=True, kind=4), parameter(signed=True),
    parameter(signed=True, style=97), parameter(signed=True, style=97)])])], 6:[convey()]}))]))
add('missing-convey-only', container([(1, scene({1:[door()], 4:[event()]}))]))
add('all-conditional-targets-retained', container([(1, scene({1:[door()], 4:[event(blocks=[
    (parameter(value=4), [parameter(signed=True), parameter(signed=True, style=97)]),
    (parameter(value=5), [parameter(signed=True)])])], 6:[convey(), convey(97, destination=123)]}))]))
add('source-local-convey-id', container([(2, scene()), (1, scene({1:[door()], 4:[event()], 6:[convey(destination=42)]}))]))
add('header-order-retained', container([(100, scene()), (2, scene()), (10, scene())], order=[2,0,1]))
add('prefix-gaps-and-outside-tail-ignored', container(gap=b'GAP', tail=b'ignored tail'))
for label, text in [
    ('cp950', '往巨鯨島'.encode('cp950')), ('prefixed-cp950', bytes([8])+'往巨鯨島'.encode('cp950')),
    ('ascii-whitespace', b' \tGood\r\n '), ('python-extra-whitespace', b'\x1cGood\x1f'),
    ('cp950-ideographic-space', '　中文　'.encode('cp950')), ('invalid', b'\xff'),
    ('undefined-user-area', b'\x81\x40'), ('truncated-lead', b'\xa1'), ('wrong-trail', b'\xa1\x80'),
    ('empty', b''), ('space-only', b' \t '), ('control-interior', b'A\x01B'),
    ('nul-tail-ignored', b'Good\0\xff\xff'), ('prefix-only', b'\x01A'),
    ('prefix-mismatch', b'\x02A'), ('full-width-no-nul', b'A'*20),
    ('cp950-specials', bytes.fromhex('a145a14ea1c2a1e3a1f2a1f3a241a242')),
]:
    add('name-'+label, container([(1, scene({1:[door(label=text)], 4:[event(label=text)], 6:[convey(label=text)]}))]))
for label, rows in [
    ('door', {1:[door(),door()]}), ('event', {4:[event(),event()]}),
    ('ignored-event', {4:[event(65535,0),event(65535,0)]}), ('convey', {6:[convey(),convey()]}),
]: add('duplicate-'+label, container([(1, scene(rows))]))
add('duplicate-scene', container([(1,scene()),(1,scene())]))
overlap = container([(1,scene()),(2,scene())])
add('identical-overlap-is-source-valid', change(overlap, 28, u32(36)))
# The first malformed scene wins over a later malformed directory entry.
late = container([(1,scene(version=114)),(2,scene())])
add('scene-error-before-later-header-error', change(late, 28, u32(0)))
add('model-short-circuit-before-version-read', change(base, 14, u16(100)))
for version in [0,114,116,65535]: add('version-'+str(version), container([(1,scene(version=version))]))
for count in [0,4097,2**32-1]: add('scene-count-'+str(count), change(base,8,u32(count)))
for offset in [0,12,23,len(base),2**32-1]: add('scene-offset-'+str(offset), change(base,16,u32(offset)))
for size in [0,5,len(base),2**32-1]: add('scene-size-'+str(size), change(base,20,u32(size)))
empty = scene({})
for section in range(5):
    at = struct.unpack_from('<11I',empty,len(empty)-44)[section]
    add('oversized-section-'+str(section), container([(1,change(empty,at,u16(4097)))]))
for section in range(11):
    add('directory-'+str(section), container([(1,change(scene(),len(scene())-44+4*section,u32(0xffffffff)))]))
# Valid ordered pointers but incorrect consumed lengths, distinct source errors.
for section in [6,7]:
    raw=scene(); at=len(raw)-44+section*4; value=struct.unpack_from('<I',raw,at)[0]
    add('section-length-'+str(section),container([(1,change(raw,at,u32(value+1)))]))
# The door parser does not validate the suffix after the conveys.
add('unparsed-later-sections-opaque',container([(1,scene({1:[door()],4:[event()],6:[convey()],7:[b'\xffgarbage']}))]))
add('group-count-above-4096-allowed',container([(1,scene({5:[group(0)]*4097}))]))
add('group-maximum-links-allowed',container([(1,scene({5:[group(65535)]}))]))
add('convey-count-above-4096-allowed',container([(1,scene({6:[convey(i) for i in range(4097)]}))]))
full=container([(1,scene({0:[npc(moves=1,params=1)],1:[door()],2:[u16(1)+common()+bytes(10)],
    3:[u16(1)+common()+bytes(11)],4:[event()],5:[group(1)],6:[convey()]}))])
for length in range(len(full)-24):
    add('bounded-scene-truncated-'+str(length),change(full,20,u32(length)))
for length in range(len(base)):
    add('file-truncated-'+str(length),base[:length])
# Observe the otherwise hard-to-reach (<48) section-directory guard with a
# short scene that successfully reaches the end of the Event section.
short=u16(99)+u16(115)+bytes(10)
add('scene-missing-directory',container([(1,short)]))
for length in [32*1024*1024,32*1024*1024+1]:
    add('source-size-'+str(length),base+bytes(length-len(base)))
for label, raw in [('empty',b''),('synthetic',base),('short',b'unknown'),('oversized',bytes(32*1024*1024+1))]:
    add('pinned-rejects-'+label,raw,'pinned')
add('retained-unit-budget-safety-divergence',container([(1,scene({1:[door(i,events=bytes([7])*255) for i in range(1400)],4:[event(blocks=[])]}))]),divergence='retained-budget')

# Exhaust every possible one-byte and two-byte CP950 input without a huge JSON
# fixture. Prefix lengths make null/empty/multi-character results unambiguous.
codec = hashlib.sha256()
for size in [1,2]:
    for value in range(256**size):
        raw=value.to_bytes(size,'big')
        try:
            text=raw.decode('cp950').encode('utf-8')
            codec.update(len(text).to_bytes(2,'little')+text)
        except UnicodeDecodeError:
            codec.update(b'\xff\xff')

payload=json.dumps(cases,ensure_ascii=True,separators=(',',':'))
compressed=gzip_json_bytes(payload)
assert len(compressed)<500000
out=Path(__file__).with_name('Fixtures')/'eve-doors-1275.json.gz'
out.write_bytes(compressed)
case_lines='\n'.join(f'        yield return new object[] {{ "{row["name"]}", {i} }};' for i,row in enumerate(cases))
Path(__file__).with_name('EveDoorPythonVectors.cs').write_text('''// Generated by generate_eve_door_vectors.py; actual retained Python oracle.
using System.Text.Json;
using Lala.Core.Tests.TestSupport;
namespace Lala.Core.Tests.World.Eve;
public static class EveDoorPythonVectors
{
    public const int VectorCount = '''+str(len(cases))+''';
    public const string SourceSha256 = "'''+PINS['wlre/services/world/doors_1275.py']+'''";
    public const string DiagnosticsSha256 = "'''+PINS['wlre/services/parser_diagnostics.py']+'''";
    public const string CodecSha256 = "'''+codec.hexdigest()+'''";
    public static IEnumerable<object[]> Cases()
    {
'''+case_lines+'''
    }
    public static JsonElement ReadCase(int index) => Fixture.Value[index];
    private static readonly Lazy<JsonElement> Fixture = new(ReadFixture);
    private static JsonElement ReadFixture()
    {
        using var document = JsonDocument.Parse(GzipJson.DecodeResource(
            "Lala.Core.Tests.World.Eve.Fixtures.eve-doors-1275.json.gz",
            "'''+hashlib.sha256(compressed).hexdigest()+'''", "'''+hashlib.sha256(payload.encode()).hexdigest()+'''"));
        if (document.RootElement.GetArrayLength() != VectorCount) throw new InvalidDataException("Eve door fixture count mismatch");
        return document.RootElement.Clone();
    }
}
''',encoding='utf-8',newline='\n')
print(f'{len(cases)} vectors; {len(payload.encode())} JSON bytes; {len(compressed)} gzip bytes; CP950 digest {codec.hexdigest()}')
