"""Actual decorated Python adapter oracle; synthetic offline payloads only.

Raw byte recipes are specified below for bounded .NET test materialization.
Expected summary SHA-256 covers the entire ordered dataclass JSON result.
"""
import base64
import copy
import dataclasses
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
from wlre.services.world.catalog_adapters import SourceContract, parse_feature, parse_selected

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


def sample(iid=39852, price=125, name='蘋果'):
    enc=lambda s: s.encode('utf-16-le')
    namebytes=enc(name);kindbytes=enc('雜物')
    out=struct.pack('<H',len(namebytes))+namebytes+b'\x01'+struct.pack('<H',len(kindbytes))+kindbytes
    out+=struct.pack('<H',iid)
    out+=bytes(2+2+2+4*2+2*(2+1+4)+4+4*4*4)
    out+=struct.pack('<BBIIBH',0,10,price,55,2,16)
    out+=bytes(4+1+4+2+5*2)
    out+=struct.pack('<H',0)
    out+=bytes(3+2+1+1)
    out+=bytes(1+2+2+2+2+1+1+1)
    out+=bytes(1+1+1+2+2+2+2+2)
    out+=bytes(6*4)
    out+=bytes(2+2+1+1+1+1+1+1+2+1)
    out+=bytes(5*2)
    out+=bytes(1+2+2+2)
    return out


KEY = 'a' * 64
REV = 'future-reviewed-revision'
SCHEMAS = dict(npc='eve-npc-json-v1', shops='eve-interact-json-v1',
               crafting='smith-reviewed-v1', scenes='stage-new-76-v1', items='itemdata-v1')

def encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode()

def npc(index=0): return dict(index=index, npc_id=42, x=150, y=200)
def shop(index=0): return dict(index=index, form_kind=3, items=[dict(id=1, text_id=68, database_kind=2, kind=3)])
def doc(feature, scenes=None):
    if scenes is None: scenes = {'90': [(npc if feature == 'npc' else shop)()], '1': []}
    return dict(schema_version=1, source='EventData.NewNpc' if feature == 'npc' else 'EventData.NewInteract',
                scenes=scenes, record_count=sum(len(rows) for rows in scenes.values()))

def materialize(spec):
    if 'base64' in spec: return base64.b64decode(spec['base64'])
    count, kind = spec['count'], spec['kind']
    if kind == 'repeat-byte': return bytes([spec['value']]) * count
    if kind == 'smith33-rows': return table(*(smith(i + 1) for i in range(count)))
    if kind == 'smith35-rows': return table(*(candidate(i + 1, smith(time_id=i % 2)) for i in range(count)))
    if kind == 'stage-rows': return table(*(stage(count - i) for i in range(count)))
    if kind == 'item-rows': return table(*(sample(i + 1, name='A') for i in range(count)))
    if kind in ('npc-rows', 'shop-rows'):
        feature = 'npc' if kind == 'npc-rows' else 'shops'
        row = npc if feature == 'npc' else shop
        scenes = {str(start // 4096): [row(i) for i in range(min(4096, count-start))]
                  for start in range(0, count, 4096)}
        return encoded(doc(feature, scenes))
    raise AssertionError(kind)

def rawspec(raw): return {'base64': base64.b64encode(raw).decode()} if type(raw) is bytes else raw

def contract(feature, raw, **changes):
    result = dict(feature=feature, source_name=feature + '.bytes', schema_id=SCHEMAS[feature],
                  expected_sha256=hashlib.sha256(materialize(rawspec(raw))).hexdigest(),
                  package='DataPackage', package_version=REV)
    result.update(changes)
    return result

cases = []
def add(name, mode, args, summary=False):
    run = diagnostics.DiagnosticRun('unused-in-memory-oracle')
    token = diagnostics._run.set(run)
    result = error = failure = None
    try:
        try:
            if mode == 'contract': result = dataclasses.asdict(SourceContract(**args))
            elif mode == 'feature':
                a = copy.deepcopy(args)
                a['contract'] = SourceContract(**a['contract']) if type(a['contract']) is dict else a['contract']
                a['raw'] = materialize(a['raw']) if type(a['raw']) is dict else a['raw']
                if a.pop('raw_type', None) == 'bytearray': a['raw'] = bytearray(a['raw'])
                result = dataclasses.asdict(parse_feature(**a))
            else:
                a = copy.deepcopy(args)
                if type(a['contracts']) is dict:
                    a['contracts'] = {k: SourceContract(**v) if type(v) is dict else v for k, v in a['contracts'].items()}
                if type(a['source_payloads']) is dict:
                    a['source_payloads'] = {k: materialize(v) for k, v in a['source_payloads'].items()}
                result = {k: dataclasses.asdict(v) for k, v in parse_selected(**a).items()}
        except Exception as exc:
            error = dict(type=type(exc).__name__, message=str(exc))
            failure = getattr(exc, 'parser_diagnostic', None)
        if summary and result is not None:
            result = dict(record_count=result['record_count'], sha256=hashlib.sha256(encoded(result)).hexdigest())
        cases.append(dict(name=name, mode=mode, args=args, summary=summary, expected=result,
                          error=error, failure=failure, diagnostics=list(run.events.values())))
    finally: diagnostics._run.reset(token)

def feature(name, kind, raw, summary=False, schema=None, **changes):
    a = dict(catalog_key=KEY, package_versions={'DataPackage': REV},
             contract=contract(kind, raw, **({'schema_id': schema} if schema else {})), raw=rawspec(raw))
    a.update(changes)
    add(name, 'feature', a, summary)

basic = dict(npc=encoded(doc('npc')), shops=encoded(doc('shops')),
             crafting=table(smith(90), smith(1, time_id=65535)),
             scenes=table(stage(90), stage(0, 255)), items=table(sample(90), sample(1, name='A\x00')))
for kind, raw in basic.items(): feature(kind + '-basic', kind, raw)

# Constructor validation is retained independently from decorated entry points.
base = contract('npc', basic['npc'])
add('contract-valid', 'contract', base)
for field, values in {
    'feature': ['', 'NPC', 'unknown', None],
    'schema_id': ['', 'eve-interact-json-v1', 'eve-npc-json-v2', None],
    'source_name': ['', '.', '..', '../x', 'a/b', 'a\\b', None, 'x'*121, 'x'*120, ' ', '資源.bytes', 'a\x00b'],
    'expected_sha256': ['', 'A'*64, 'a'*63, 'a'*65, 'g'*64, 'a'*64+'\n', None],
    'package': ['', 'datapackage', 'MainPackage', None],
    'package_version': ['', None, 'v'*101, 'v'*100, ' ', '未來版本'],
}.items():
    for i, value in enumerate(values): add(f'contract-{field}-{i}', 'contract', {**base, field:value})
for kind, schema in SCHEMAS.items():
    add('contract-schema-'+kind, 'contract', contract(kind, basic[kind]))
for schema in ['smith-new-33-v1', 'smith-new-35-v1']:
    add('contract-'+schema, 'contract', contract('crafting', basic['crafting'], schema_id=schema))
for i, key in enumerate(['', 'A'*64, 'a'*63, 'a'*65, 'g'*64, 'a'*64+'\n', None]):
    feature(f'key-{i}', 'npc', basic['npc'], catalog_key=key)
for i, versions in enumerate([{}, {'MainPackage':REV}, {'DataPackage':'other'}, {'DataPackage':None}, None]):
    feature(f'versions-{i}', 'npc', basic['npc'], package_versions=versions)
feature('version-main-package', 'npc', basic['npc'], contract={**base,'package':'MainPackage'}, package_versions={'MainPackage':REV})
feature('contract-null', 'npc', basic['npc'], contract=None)
feature('hash-mismatch', 'npc', basic['npc'], contract={**base,'expected_sha256':'0'*64})
feature('raw-empty', 'npc', b'')
# Python-only non-bytes calls are not parity vectors for a span-based API.
for count in [16777216, 16777217]: feature(f'raw-size-{count}', 'npc', {'kind':'repeat-byte','count':count,'value':32})

# Derived JSON schema, exact integer checks, retained arbitrary fields and source order.
for kind in ['npc','shops']:
    for i, raw in enumerate([b'\xff', b'{', b'', b'[]', b'null', b'1', b'"text"', b'\xef\xbb\xbf{}']):
        feature(f'{kind}-json-invalid-{i}',kind,raw)
    for field, values in {'schema_version':[None,0,2,True,1.0,'1'], 'source':[None,'wrong'],
                          'scenes':[None], 'record_count':[None,True,1.0,'1',-1,2]}.items():
        for i,value in enumerate(values):
            d=doc(kind);d[field]=value;feature(f'{kind}-doc-{field}-{i}',kind,encoded(d))
    for field in ['schema_version','source','scenes','record_count']:
        d=doc(kind);del d[field];feature(f'{kind}-missing-{field}',kind,encoded(d))
    for i,key in enumerate(['0','65535','65536','-1','01','+1',' 1','1 ','١','１','²','','1.0']):
        feature(f'{kind}-scene-key-{i}',kind,encoded(doc(kind,{key:[]})))
    for i,rows in enumerate([None,{},1,'rows']):
        d=doc(kind);d['scenes']['90']=rows;feature(f'{kind}-scene-list-{i}',kind,encoded(d))
    for i,row in enumerate([None,[],1,'row']): feature(f'{kind}-row-type-{i}',kind,encoded(doc(kind,{'1':[row]})))
    fields = ['index','npc_id','x','y'] if kind=='npc' else ['index','form_kind']
    for field in fields:
        for i,value in enumerate([None,True,1.0,'1',-1,0,1,65535,65536,4294967295,4294967296]):
            d=doc(kind);d['scenes']['90'][0][field]=value
            feature(f'{kind}-row-{field}-{i}',kind,encoded(d))
        d=doc(kind);del d['scenes']['90'][0][field];feature(f'{kind}-row-missing-{field}',kind,encoded(d))
    row=(npc if kind=='npc' else shop)()
    feature(kind+'-duplicate-event',kind,encoded(doc(kind,{'1':[row,row]})))
    feature(kind+'-same-index-different-scenes',kind,encoded(doc(kind,{'90':[row],'1':[row]})))
    d=doc(kind);d['scenes']['90'][0]['extra']={'text':'雪😀','null':None,'nested':[True,1.25,{'z':2,'a':1}],'large':123456789012345678901234567890}
    d['extra']={'ignored':True};feature(kind+'-extra-fields',kind,encoded(d))
    feature(kind+'-empty-scenes',kind,encoded(doc(kind,{})))
    for count in [4096,4097]: feature(f'{kind}-scene-row-limit-{count}',kind,encoded(doc(kind,{'1':[(npc if kind=='npc' else shop)(i) for i in range(count)]})),summary=count==4096)
    for count in [20000,20001]: feature(f'{kind}-maximum-rows-{count}',kind,{'kind':'npc-rows' if kind=='npc' else 'shop-rows','count':count},summary=count==20000)
# Duplicate properties retain first insertion position and last value, including scenes.
feature('npc-duplicate-properties','npc',b'{"schema_version":2,"schema_version":true,"source":"EventData.NewNpc","scenes":{"90":[],"1":[],"90":[{"index":4,"npc_id":1,"x":0,"y":1,"x":9}]},"record_count":1}')
for i, items in enumerate([None,{},1,[],[None],[[]],[1]]):
    d=doc('shops');d['scenes']['90'][0]['items']=items;feature(f'shops-items-type-{i}','shops',encoded(d))
for form in [1,2,3,4,255]:
    d=doc('shops');d['scenes']['90'][0]['form_kind']=form;feature(f'shops-form-{form}','shops',encoded(d))
for field in ['id','text_id','database_kind','kind']:
    for i,value in enumerate([None,True,1.0,'1',-1,0,255,256,65535,65536]):
        d=doc('shops');d['scenes']['90'][0]['items'][0][field]=value;feature(f'shops-item-{field}-{i}','shops',encoded(d))
    d=doc('shops');del d['scenes']['90'][0]['items'][0][field];feature(f'shops-item-missing-{field}','shops',encoded(d))
for count in [255,256]:
    d=doc('shops');d['scenes']['90'][0]['items']*=count;feature(f'shops-item-count-{count}','shops',encoded(d))
d=doc('shops');d['scenes']['90'][0]['items'][0]['extra']={'b':False,'s':'店'};feature('shops-item-extra','shops',encoded(d))

# Exact binary framing and nested source diagnostic propagation.
for schema,size in [('smith-new-33-v1',33),('smith-new-35-v1',35),('smith-reviewed-v1',33),('stage-new-76-v1',76)]:
    kind='scenes' if size==76 else 'crafting'
    raw=table(stage(1)) if size==76 else table(candidate(1,smith())) if size==35 else table(smith())
    feature(schema+'-valid',kind,raw,schema=schema)
    feature(schema+'-empty',kind,table(),schema=schema)
    for cut in range(len(raw)): feature(f'{schema}-cut-{cut}',kind,raw[:cut],schema=schema)
    feature(schema+'-trailing',kind,raw+b'!',schema=schema)
    for count in [-2147483648,-1,1,20000,20001,2147483647]: feature(f'{schema}-count-{count}',kind,struct.pack('<i',count),schema=schema)
feature('reviewed35-marked-array','crafting',table(candidate(90,smith()),candidate(1,smith(time_id=17))))
feature('reviewed33-unmarked-map','crafting',basic['crafting'])
for schema in ['smith-reviewed-v1','smith-new-33-v1']:
    for suffix,raw in [('zero',table(smith(0))),('duplicate',table(smith(),smith())),('material',table(smith(material_count=6)))]:
        feature(schema+'-nested-'+suffix,'crafting',raw,schema=schema)
for suffix,raw in [('zero-key',table(candidate(0,smith()))),('duplicate-key',table(candidate(1,smith()),candidate(1,smith()))),('zero-item',table(candidate(1,smith(0))))]:
    for schema in ['smith-reviewed-v1','smith-new-35-v1']: feature(schema+'-nested-'+suffix,'crafting',raw,schema=schema)
feature('stage-duplicate-count-mismatch','scenes',table(stage(1),stage(1)))
for suffix,raw in [('empty',table()),('zero-item',table(sample(0))),('duplicate',table(sample(1),sample(1))),('truncated',basic['items'][:-1]),('trailing',basic['items']+b'!'),('bad-unicode',struct.pack('<iH',1,3)+b'abc')]:
    feature('items-nested-'+suffix,'items',raw)
for schema,kind,recipe in [('smith-new-33-v1','crafting','smith33-rows'),('smith-reviewed-v1','crafting','smith35-rows'),('stage-new-76-v1','scenes','stage-rows'),('itemdata-v1','items','item-rows')]:
    feature(schema+'-maximum-count',kind,{'kind':recipe,'count':20000},summary=True,schema=schema)

# Atomic selection always uses FEATURES order even when input mappings are reversed.
selected=dict(catalog_key=KEY,package_versions={'DataPackage':REV},
              contracts={k:contract(k,raw) for k,raw in reversed(list(basic.items()))},
              source_payloads={k+'.bytes':rawspec(raw) for k,raw in reversed(list(basic.items()))})
add('selected-all-five','selected',selected)
for kind in basic:
    a=copy.deepcopy(selected);del a['contracts'][kind];add('selected-missing-contract-'+kind,'selected',a)
    a=copy.deepcopy(selected);del a['source_payloads'][kind+'.bytes'];add('selected-missing-source-'+kind,'selected',a)
    a=copy.deepcopy(selected);a['contracts'][kind]=None;add('selected-null-contract-'+kind,'selected',a)
    a=copy.deepcopy(selected);a['contracts'][kind]=contract('npc' if kind!='npc' else 'shops',basic[kind]);add('selected-wrong-feature-'+kind,'selected',a)
    a=copy.deepcopy(selected);a['contracts'][kind]['expected_sha256']='0'*64;add('selected-bad-hash-'+kind,'selected',a)
for field in ['contracts','source_payloads']:
    for i,value in enumerate([None,{}]):
        a=copy.deepcopy(selected);a[field]=value;add(f'selected-{field}-type-{i}','selected',a)
a=copy.deepcopy(selected);a['contracts']['extra']=base;add('selected-extra-contract','selected',a)
a=copy.deepcopy(selected);a['source_payloads']['extra']={'base64':'IQ=='};add('selected-extra-source-ignored','selected',a)
a=copy.deepcopy(selected);a['catalog_key']='bad';add('selected-invalid-key','selected',a)
a=copy.deepcopy(selected);a['package_versions']={};add('selected-invalid-revision','selected',a)
a=copy.deepcopy(selected);raw=basic['items'][:-1];a['source_payloads']['items.bytes']=rawspec(raw);a['contracts']['items']=contract('items',raw);add('selected-late-items-nested-failure','selected',a)

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
    name = f'source-adapters-{index:02}.json.gz'; (output / name).write_bytes(packed)
    references.append((name, hashlib.sha256(packed).hexdigest(), hashlib.sha256(payload).hexdigest()))
sources = ['wlre/services/world/catalog_adapters.py', 'wlre/services/world/itemdata_v1.py',
           'wlre/services/world/preview_1275.py', 'wlre/services/world/smith_candidate.py',
           'wlre/services/instance_catalog.py', 'wlre/network/wire.py', 'wlre/services/parser_diagnostics.py']
lines = ['// Generated by generate_source_adapter_vectors.py. Actual decorated Python oracle.',
         'using System.Text.Json;', 'using Lala.Core.Tests.TestSupport;',
         'namespace Lala.Core.Tests.Catalogs.SourceAdapters;', 'public static class SourceAdapterPythonVectors', '{',
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
          '            "Lala.Core.Tests.Catalogs.SourceAdapters.Fixtures." + name, compressedHash, decodedHash));',
          '        return document.RootElement.Clone();', '    }', '}']
Path(__file__).with_name('SourceAdapterPythonVectors.cs').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
print(f'{len(cases)} actual decorated Python vectors; {len(groups)} deterministic resources')
