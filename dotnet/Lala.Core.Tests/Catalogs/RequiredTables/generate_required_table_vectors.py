"""Actual decorated parser oracles; no runtime activation, pins, network or report IO.

Composition is adapted offline composition: executes the exact AST name-binding block
from bundle_runtime_1275.py with supplied parsed sources, not full runtime parity.
Only source-binding statements are extracted: runtime admission/hash/count checks
are excluded. Retained Python revision/source_kind describe that source block, not
Core trust. Core intentionally omits revision and trusted source_kind: C# compares
tasks/levels/npcs/source_sha256 and asserts supplied_offline_tables plus false
admission/readiness flags separately.
Large accepted counts use recipes and full ordered typed-binary result digests.
"""
import ast
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / 'dotnet/Lala.Core.Tests/TestSupport')]
from gzip_json_fixture import gzip_json_bytes
from wlre.services import parser_diagnostics as diagnostics
from wlre.services.expedition import data
from wlre.services.world.npc_talk import parse_talk_data

p = lambda fmt, *v: struct.pack('<' + fmt, *v)
table = lambda *rows: p('i', len(rows)) + b''.join(rows)
def talk(sid=1, value='甲😀\0\0', voice=65535):
    raw = value.encode('utf-16-le') if isinstance(value, str) else value
    return p('HH', sid, len(raw)) + raw + bytes(range(5)) + p('H', voice) + bytes(range(28))
def task(sid=1, minutes=65535, faith=100, maximum=True):
    v = 0xffffffff if maximum else 0
    return (p('H B I B I I H B H 3H', sid, 255 if maximum else 0, 20, 255 if maximum else 0,
              10, v, minutes, faith, 65535 if maximum else 0, 0, 1, 65535)
        + b''.join(p('4H', i, 65535-i, i+256, 65535-i) for i in range(4))
        + p('I', v) + b''.join(p('BII', i*127, v-i if maximum else i, i) for i in range(3))
        + p('H B I I i', 65535, 255, v, v, -2147483648 if maximum else 2147483647))
def level(sid=0, teams=7, reduction=1000):
    return p('B I I B B H B B', sid, 0xffffffff, 0, teams, 255, reduction, 255, 255)
def npc(sid=1, name='甲😀', second='乙', element=255, kind=255):
    def name_bytes(value):
        raw = value.encode('utf-16-le') if isinstance(value, str) else value
        return p('H', len(raw)) + raw
    fields = bytearray((i % 256 for i in range(203)))
    struct.pack_into('<H', fields, 1, sid)
    fields[74], fields[106] = element, kind
    return name_bytes(name) + name_bytes(second) + fields
def career(original=0, sid=1):
    return p('3H', 65535, original, sid) + bytes(range(11))
def text(key, value):
    raw = value.encode('utf-16-le') if isinstance(value, str) else value
    return p('IH', key, len(raw)) + raw

def materialize(spec):
    if isinstance(spec, bytes): return spec
    kind = spec['kind']
    if kind == 'zeros': return bytes(spec['size'])
    count = spec['count']
    constructors = {'talk-count': lambda i: talk(i, '', i), 'task-count': lambda i: task(i+1),
        'level-count': lambda i: level(i), 'npc-count': lambda i: npc(i+1, '', ''),
        'career-count': lambda i: career(i, i),
        'npc-over-composition-cap': lambda i: npc(i+1, '字'*32767, '字'*32767)}
    return p('i', count) + b''.join(constructors[kind](i) for i in range(count))
def describe(spec):
    return {'base64': base64.b64encode(spec).decode()} if isinstance(spec, bytes) else spec

def digest_result(value):
    digest = hashlib.sha256()
    def emit(v):
        if v is None: digest.update(b'n')
        elif isinstance(v, bool): digest.update(b't' if v else b'f')
        elif isinstance(v, int): digest.update(b'i'+p('q', v))
        elif isinstance(v, str):
            raw = v.encode('utf-8'); digest.update(b's'+p('I', len(raw))+raw)
        elif isinstance(v, list):
            digest.update(b'l'+p('I', len(v)))
            for item in v: emit(item)
        elif isinstance(v, dict):
            digest.update(b'd'+p('I', len(v)))
            for key, item in v.items(): emit(str(key)); emit(item)
        else: raise TypeError(type(v))
    emit(value)
    return {'sha256': digest.hexdigest(), 'count': len(value.get('tasks', value))}

runtime_path = ROOT / 'wlre/services/world/bundle_runtime_1275.py'
runtime_ast = ast.parse(runtime_path.read_text(encoding='utf-8'))
# Locate by semantic anchors, retaining the exact statements, not hand-copied logic.
blocks = [node.body for node in ast.walk(runtime_ast) if isinstance(node, ast.Try)]
composition = None
for body in blocks:
    for index, node in enumerate(body):
        if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'stage' and isinstance(node.value, ast.Constant)
                and node.value.value == 'TextData_C／遠征名稱'):
            composition = body[index+1:index+4]
assert composition and len(composition) == 3
assert isinstance(composition[0], ast.Assign) and isinstance(composition[1], ast.For)
assert isinstance(composition[2], ast.Assign) and composition[2].targets[0].id == 'expedition'
composition_code = compile(ast.Module(body=composition, type_ignores=[]), str(runtime_path), 'exec')
class BundleRuntimeUnavailable(ValueError): pass

cases = []
def add(name, mode, inputs, summary=False, dynamic=False):
    actual = {key: materialize(value) for key, value in inputs.items()}
    run = diagnostics.DiagnosticRun('unused-in-memory-oracle')
    token = diagnostics._run.set(run)
    result = error = failure = None
    try:
        try:
            if mode == 'talk': result = parse_talk_data(actual['raw'])
            elif mode == 'catalog': result = data.parse_catalog(actual['tasks'], actual['levels'])
            elif mode == 'npcs': result = data.parse_npcs(actual['npc'], actual['career'])
            elif mode == 'attach':
                result = data.attach_names(data.parse_catalog(actual['tasks'], actual['levels']), actual['text'])
            elif mode == 'compose':
                talks = parse_talk_data(actual['talk'])
                texts = data.parse_text_data(actual['text'])
                expedition = data.parse_catalog(actual['tasks'], actual['levels'])
                npcs = data.parse_npcs(actual['npc'], actual['career'])
                sources = {'NpcData_C': actual['npc'], 'NpcCareerData_C': actual['career']}
                env = dict(expedition=expedition, expedition_npcs=npcs, sources=sources, texts=texts,
                    dynamic=dynamic, revision=1300 if dynamic else 1275, hashlib=hashlib,
                    BundleRuntimeUnavailable=BundleRuntimeUnavailable)
                exec(composition_code, env)
                result = dict(talks=talks, texts=texts, expedition=env['expedition'])
            else: raise AssertionError(mode)
        except Exception as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)}
            failure = getattr(exc, 'parser_diagnostic', None)
        if summary and result is not None: result = digest_result(result)
        cases.append(dict(id=len(cases), name=name, mode=mode, inputs={k:describe(v) for k,v in inputs.items()},
            summary=summary, dynamic=dynamic, expected=result, error=error, failure=failure,
            diagnostics=list(run.events.values())))
    finally: diagnostics._run.reset(token)

base = dict(talk=table(talk()), text=table(text(10,'任務'),text(20,'地區')), tasks=table(task()),
    levels=table(level()), npc=table(npc()), career=table(career()))
for mode, keys in [('talk',['raw']),('catalog',['tasks','levels']),('npcs',['npc','career']),
                   ('attach',['tasks','levels','text']),('compose',list(base))]:
    inputs = {'raw':base['talk']} if mode == 'talk' else {k:base[k] for k in keys}
    add(mode+'-basic',mode,inputs)
    for key in keys:
        for cut in range(len(inputs[key])): add(f'{mode}-{key}-cut-{cut}',mode,{**inputs,key:inputs[key][:cut]})
        add(f'{mode}-{key}-tail',mode,{**inputs,key:inputs[key]+b'!'})
for count in [-2147483648,-1,0,1,2,254,255,256,65535,65536,65537,2147483647]:
    add(f'talk-count-{count}','talk',{'raw':p('i',count)+talk()})
    for key in ['tasks','levels']:
        add(f'catalog-{key}-count-{count}','catalog',{k:(p('i',count)+base[k][4:] if k==key else base[k]) for k in ['tasks','levels']})
    for key in ['npc','career']:
        add(f'npcs-{key}-count-{count}','npcs',{k:(p('i',count)+base[k][4:] if k==key else base[k]) for k in ['npc','career']})
for name, raw in [('duplicate',table(talk(),talk())),('order',table(talk(65535),talk(0),talk(1))),
    ('empty',table(talk(value=''))),('trim-nul',table(talk(value='a\0\0'))),('internal-nul',table(talk(value='a\0b'))),
    ('whitespace',table(talk(value='\r\n\t'))),('control',table(talk(value='\x1f'))),
    ('surrogate',table(talk(value=b'\x00\xd8'))),('low-surrogate',table(talk(value=b'\x00\xdc'))),
    ('odd',table(talk(value=b'a'))),('maximum-text',table(talk(value='字'*16384))),
    ('oversize-text',table(talk(value='字'*16385)))]: add('talk-'+name,'talk',{'raw':raw})
for value in [0,1,31,32,127,128,65535]: add(f'talk-voice-{value}','talk',{'raw':table(talk(voice=value))})
add('talk-max-count','talk',{'raw':{'kind':'talk-count','count':65536}},True)
add('talk-max-bytes','talk',{'raw':{'kind':'zeros','size':16*1024*1024}})
add('talk-over-bytes','talk',{'raw':{'kind':'zeros','size':16*1024*1024+1}})
for name, raw in [('zero-id',table(task(0))),('zero-minutes',table(task(minutes=0))),('faith-101',table(task(faith=101))),
    ('faith-255',table(task(faith=255))),('min-fields',table(task(minutes=1,faith=0,maximum=False))),
    ('duplicate',table(task(),task())),('order',table(task(65535),task(2),task(1)))]:
    add('catalog-'+name,'catalog',{'tasks':raw,'levels':base['levels']})
for name, raw in [('teams-zero',table(level(teams=0))),('teams-eight',table(level(teams=8))),
    ('reduction-zero',table(level(reduction=0))),('reduction-over',table(level(reduction=1001))),
    ('duplicate',table(level(),level())),('order',table(level(255),level(1),level(0)))]:
    add('levels-'+name,'catalog',{'tasks':base['tasks'],'levels':raw})
add('catalog-max-count','catalog',{'tasks':{'kind':'task-count','count':65535},'levels':{'kind':'level-count','count':255}},True)
for name, raw in [('zero',table(npc(0))),('duplicate',table(npc(),npc())),('order',table(npc(65535),npc(2),npc(1))),
    ('empty-names',table(npc(name='',second='',element=0,kind=0))),('odd-first',table(npc(name=b'a'))),
    ('odd-second',table(npc(second=b'a'))),('surrogate-first',table(npc(name=b'\x00\xd8'))),
    ('surrogate-second',table(npc(second=b'\x00\xdc'))),('control-names',table(npc(name='\0\x01'))),
    ('maximum-names',table(npc(name='字'*32767,second='😀'*16383)))]:
    add('npcs-'+name,'npcs',{'npc':raw,'career':base['career']})
for name, raw in [('empty',table()),('absent',table(career(9,99))),('duplicate',table(career(),career(2))),
    ('original-duplicate',table(career(9,1),career(9,2))),('zero-career',table(career(65535,0))),
    ('order',table(career(2,1),career(3,2)))]:
    add('careers-'+name,'npcs',{'npc':table(npc(2),npc(1)),'career':raw})
add('npcs-max-count','npcs',{'npc':{'kind':'npc-count','count':65535},'career':{'kind':'career-count','count':65535}},True)
for name, rows in [('missing-name',[text(20,'區')]),('missing-area',[text(10,'任務')]),
    ('blank-name',[text(10,'')]),('blank-area',[text(10,'任務'),text(20,'')]),
    ('spaces',[text(10,' \t\n')]),('python-strip',[text(10,'\x1c\x85\u2007\u3000')]),
    ('zero-width',[text(10,'\u200b')]),('nul',[text(10,'\0')]),
    ('name-8192',[text(10,'😀'*8192)]),('name-8193',[text(10,'😀'*8193)]),
    ('area-8192',[text(10,'任務'),text(20,'😀'*8192)]),('area-8193',[text(10,'任務'),text(20,'😀'*8193)]),
    ('invalid-utf16',[text(10,b'\x00\xd8')]),('duplicate',[text(10,'甲'),text(10,'乙')]),
    ('text-order',[text(20,'區'),text(999,'額外'),text(10,'任務')])]:
    for mode in ['attach','compose']:
        inputs = {k:v for k,v in base.items() if mode=='compose' or k in ['tasks','levels','text']}
        add(mode+'-'+name,mode,{**inputs,'text':table(*rows)})
add('compose-dynamic','compose',base,dynamic=True)
for key in base:
    add('compose-precedence-'+key,'compose',{k:(b'' if list(base).index(k)>=list(base).index(key) else v) for k,v in base.items()})
# Career parser precedes NPC parser even though the public arguments are NPC then career.
add('npcs-career-precedence','npcs',{'npc':b'','career':p('i',-1)})

# Ignored numeric/reserved fields must not change the decoded result.
for offset in range(5):
    raw=bytearray(table(talk(value=''))); raw[8+offset]=255
    add(f'talk-reserved-byte-{offset}','talk',{'raw':bytes(raw)})
for offset in range(28):
    raw=bytearray(table(talk(value=''))); raw[15+offset]^=255
    add(f'talk-reserved-numeric-{offset}','talk',{'raw':bytes(raw)})
for value in [1,127,128,254]:
    add(f'npcs-byte-fields-{value}','npcs',{'npc':table(npc(element=value,kind=value)),'career':table()})
for value in [1,99]:
    add(f'catalog-faith-{value}','catalog',{'tasks':table(task(faith=value)),'levels':base['levels']})
for value in [1,6,255]:
    add(f'levels-teams-{value}','catalog',{'tasks':base['tasks'],'levels':table(level(teams=value))})
for value in [1,999,65535]:
    add(f'levels-reduction-{value}','catalog',{'tasks':base['tasks'],'levels':table(level(reduction=value))})

# Raw parse_npcs has no 16MiB composition admission limit. Each name is 65534
# encoded bytes (32767 code points); 129 rows total 16934479 bytes, below 17MiB.
add('npcs-over-composition-cap','npcs',
    {'npc':{'kind':'npc-over-composition-cap','count':129},'career':table()},True)
assert cases[-1]['error'] is None and cases[-1]['expected']['count'] == 129
assert cases[-1]['diagnostics'][0]['inputs']['npc_data']['size'] == 16934479
# Combined-invalid inputs retain the exact first-error/checkpoint precedence.
add('talk-duplicate-before-control','talk',{'raw':table(talk(),talk(value='\x01'))})
add('task-truncated-before-zero-id','catalog',
    {'tasks':table(task(0)[:-1]),'levels':base['levels']})
add('npc-name-before-zero-id','npcs',
    {'npc':table(npc(0,name=b'\x00\xd8')),'career':table()})
add('npc-name-before-duplicate-id','npcs',
    {'npc':table(npc(),npc(name=b'\x00\xd8')),'career':table()})
add('career-truncated-before-duplicate','npcs',
    {'npc':base['npc'],'career':p('i',2)+career()+career()[:16]})

out = Path(__file__).with_name('Fixtures'); out.mkdir(exist_ok=True)
groups = [cases[i:i+80] for i in range(0,len(cases),80)]
refs=[]
for index, rows in enumerate(groups):
    payload=json.dumps(rows,ensure_ascii=True,separators=(',',':'))
    packed=gzip_json_bytes(payload); assert len(packed)<500000
    name=f'required-tables-{index:02}.json.gz'; (out/name).write_bytes(packed)
    refs.append((name,hashlib.sha256(packed).hexdigest(),hashlib.sha256(payload.encode()).hexdigest()))
sources=['wlre/services/world/npc_talk.py','wlre/services/expedition/data.py',
    'wlre/services/world/bundle_runtime_1275.py','wlre/network/wire.py','wlre/services/parser_diagnostics.py']
lines=['// Generated by generate_required_table_vectors.py. Actual decorated Python oracles.',
'using System.Text.Json;','using Lala.Core.Tests.TestSupport;','namespace Lala.Core.Tests.Catalogs.RequiredTables;',
'public static class RequiredTableOracleCases','{',f'    public const int VectorCount = {len(cases)};',
'    public static IEnumerable<object[]> SourceRefs()','    {']
for source in sources:
    digest=hashlib.sha256((ROOT/source).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    lines.append(f'        yield return new object[] {{ "{source}", "{digest}" }};')
lines+=['    }','    public static IEnumerable<object[]> ResourceRefs()','    {']
for name, packed, payload in refs: lines.append(f'        yield return new object[] {{ "{name}", "{packed}", "{payload}" }};')
lines+=['    }','    public static IEnumerable<object[]> CaseIds()','    {',
'        for (var id = 0; id < VectorCount; id++) yield return new object[] { id };','    }',
'    private static readonly Lazy<JsonElement>[] Fixtures =','    [']
for name,packed,payload in refs: lines.append(f'        new(() => Load("{name}", "{packed}", "{payload}")),')
lines+=['    ];','    public static JsonElement Case(int id) => Fixtures[id / 80].Value[id % 80];',
'    private static JsonElement Load(string name, string compressedHash, string decodedHash)','    {',
'        using var document = JsonDocument.Parse(GzipJson.DecodeResource(',
'            "Lala.Core.Tests.Catalogs.RequiredTables.Fixtures." + name, compressedHash, decodedHash));',
'        return document.RootElement.Clone();','    }','}']
Path(__file__).with_name('RequiredTableOracleCases.cs').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
assert len({case['name'] for case in cases})==len(cases)
print(f'{len(cases)} actual decorated Python vectors; {len(refs)} deterministic gzip resources')
