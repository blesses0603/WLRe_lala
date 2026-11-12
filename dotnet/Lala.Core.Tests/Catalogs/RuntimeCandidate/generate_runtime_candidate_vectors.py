"""Owned synthetic ten-table composition; execute exact runtime AST blocks, no file/cache/activation.

The verified-context/source extraction gates and optional catalogs are deliberately excluded.
Legacy synthetic ItemData exercises its real public parser, without replacing any digest pin.
Retained expectations focus on new joins/projections; existing parser families retain full rows.
"""
import ast
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / 'dotnet/Lala.Core.Tests/TestSupport')]
from gzip_json_fixture import gzip_json_bytes
from wlre.services import parser_diagnostics as diagnostics
from wlre.services.world.eve_v115 import EveDecodeError, derive_eve_index, derive_eve_indexes
from wlre.services.world.itemdata_v1 import parse_itemdata
from wlre.services.world.npc_talk import parse_talk_data
from wlre.services.expedition.data import parse_text_data, parse_catalog as parse_expedition, parse_npcs as parse_expedition_npcs
from wlre.services.instance_catalog import parse_stages
from wlre.services.world.doors_1275 import parse_verified_doors
from wlre.services.world.scene_names_1275 import bind_scene_names
from wlre.services.world.dynamic_bundle_runtime import parse_runtime_recipes

p = lambda fmt, *v: struct.pack('<'+fmt, *v)
table = lambda *rows: p('i',len(rows))+b''.join(rows)
VERSION = '1286_2026_10_29_13_42_37_94'
# Load constructors only, never execute the other generators or their huge vector loops.
def constructors(path, names, extra):
    tree=ast.parse((ROOT/path).read_text())
    nodes=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(nodes)==len(names)
    env={'struct':struct, **extra}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),env)
    return env
item_record=constructors('dotnet/Lala.Core.Tests/Catalogs/generate_catalog_vectors.py', ['item_record'], {})['item_record']
r=constructors('dotnet/Lala.Core.Tests/Catalogs/RequiredTables/generate_required_table_vectors.py',
    ['talk','task','level','npc','career','text'],{'p':p})
e=constructors('dotnet/Lala.Core.Tests/World/Eve/generate_eve_vectors.py',
    ['common','npc','interact','scene','container'],{'u16':lambda v:p('H',v),'u32':lambda v:p('I',v)})

d=constructors('dotnet/Lala.Core.Tests/World/Eve/generate_eve_door_vectors.py',
    ['common','door','parameter','event','convey'],{'u16':lambda v:p('H',v),'u32':lambda v:p('I',v),
    'name':lambda value=b'':value.ljust(20,b'\0')[:20]})

def eve(form=3, offers=((1,123,2,3),)):
    # Eve NPC 9001 intentionally need not exist in expedition NPC table. Source has no such join.
    payload=e['scene']({0:[e['npc']()],1:[d['door']()],4:[d['event']()],6:[d['convey']()],7:[e['interact'](form=form,items=offers)]},model=456)
    return e['container']([(500,payload)])
def smith(item=123, material=20, amount=2, time=0):
    row=bytearray(33)
    struct.pack_into('<HHBHB',row,0,item,7,2,8,3)
    struct.pack_into('<HB',row,8,material,amount)
    struct.pack_into('<BHBBHBBB',row,23,1,11,4,5,time,6,7,8)
    return bytes(row)
def stage(id=500,name=30):
    row=bytearray(76);struct.pack_into('<HHIH',row,0,id,0,name,456);return bytes(row)
def texts(name='任務',area='地區',scene='  場景😀  '):
    return table(r['text'](10,name),r['text'](20,area),r['text'](30,scene))
base={'Eve':eve(),'ItemData_C':table(*(item_record(id,open_used=flag)[0] for id,flag in [(123,255),(20,0),(99,1)])),
    'TalkData_C':table(r['talk']()),'TextData_C':texts(),
    'SmithData_C':table(p('H',9)+smith(),p('H',2)+smith(time=3),p('H',6)+smith(99)),
    'ScenesData_C':table(stage()),'AdventureData_C':table(r['task']()),
    'AdventureLvData_C':table(r['level']()),'NpcData_C':table(r['npc']()),'NpcCareerData_C':table(r['career']())}

runtime_path=ROOT/'wlre/services/world/bundle_runtime_1275.py'
tree=ast.parse(runtime_path.read_text())
body=next(n.body for n in ast.walk(tree) if isinstance(n,ast.Try) and any(isinstance(v,ast.Assign)
    and isinstance(v.targets[0],ast.Name) and v.targets[0].id=='eve' for v in n.body))
def assignment(n,key,value=None):
    return isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id==key and (value is None or isinstance(n.value,ast.Constant) and n.value.value==value)
start=next(i for i,n in enumerate(body) if assignment(n,'stage','Eve'))
stop=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Tuple) and isinstance(n.targets[0].elts[0],ast.Name) and n.targets[0].elts[0].id=='portal_destinations')
# Multi-target assignment: portal_destinations, portal_names, portal_positions = ...
start2=next(i for i,n in enumerate(body) if isinstance(n,ast.If) and 'len(recipes)' in ast.unparse(n.test))
stop2=next(i for i,n in enumerate(body) if assignment(n,'daily_catalog'))
wrapper=ast.parse('def __compose_extracted():\n    return locals()').body[0]
wrapper.body=body[start:stop]+body[start2:stop2]+wrapper.body
code=compile(ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[])),str(runtime_path),'exec')
class BundleRuntimeUnavailable(ValueError):pass

def compose(sources,version):
    env=dict(globals(),sources=sources,dynamic=True,revision=1286,
        verified_data=SimpleNamespace(spec=SimpleNamespace(package_version=version)),
        stored=lambda feature,tables,parse:parse())
    exec(code,env)
    return projection(env['__compose_extracted'](),sources)

def projection(env,sources):
    x=env; exp=x['expedition']
    return dict(npc=x['npc'],interacts=x['interacts'],
        items=[[k,v['open_used']] for k,v in x['items'].items()],
        talks=[[int(k),v['text'],v['voice_id']] for k,v in x['talk_rows'].items()],texts=x['texts'],
        products=x['recipes'],catalog=x['recipe_catalog'],
        stages=[[k,v['name_id'],v['model_id']] for k,v in x['scene_rows'].items()],
        door_counts=[[int(k),len(v)] for k,v in x['doors'].items()],
        door_summaries=[[int(k),door['index'],door['touch_event_ids'],
            [[event['index'],event['destination_decoded'],[transfer['destination'] for transfer in event['convey_transfers']]] for event in door['touch_event_records']]]
            for k,doors in x['doors'].items() for door in doors],
        scene_names=bind_scene_names(x['scene_rows'],x['texts']),
        tasks=[[int(k),v['name'],v['area_label']] for k,v in exp['tasks'].items()],
        level_ids=[int(k) for k in exp['levels']],npcs=exp['npcs'],expedition_hashes=exp['source_sha256'],
        hashes={k:hashlib.sha256(v).hexdigest() for k,v in sources.items()})

cases=[]
def add(name,mode='compose',sources=None,version=VERSION):
    inputs=dict(base if sources is None else sources)
    expected=error=None
    run=diagnostics.DiagnosticRun('unused-in-memory-candidate')
    token=diagnostics._run.set(run)
    try:
        if mode=='compose':expected=compose(inputs,version)
        elif mode=='recipes':
            products,catalog=parse_runtime_recipes(inputs['SmithData_C'],parse_itemdata(inputs['ItemData_C'],package_version=version))
            expected={'products':products,'catalog':catalog}
        elif mode=='scenes':expected=bind_scene_names(parse_stages(inputs['ScenesData_C']),parse_text_data(inputs['TextData_C']))
        else:raise AssertionError(mode)
    except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
    finally:diagnostics._run.reset(token)
    recipe_diagnostic=next((event for event in run.events.values() if event['schema']=='runtime-recipes-v1'),None)
    cases.append(dict(id=len(cases),name=name,mode=mode,version=version,
        inputs={k:base64.b64encode(v).decode() for k,v in inputs.items()},expected=expected,error=error,recipe_diagnostic=recipe_diagnostic))
add('all-ten-duplicate-products')
add('all-ten-legacy-recipe',sources={**base,'SmithData_C':table(smith())})
add('all-ten-empty-expedition',sources={**base,'AdventureData_C':table(),'AdventureLvData_C':table(),'NpcData_C':table(),'NpcCareerData_C':table()})
for key in base:
    add('empty-'+key,sources={**base,key:b''})
for index,key in enumerate(base):
    if index+1<len(base):
        following=list(base)[index+1]
        add('precedence-'+key,sources={**base,key:b'',following:b''})
for form in [0,1,2,3,4,255]:
    for kind in [0,2,3,4,255]:
        for db in [0,2,255]:
            add(f'shop-{form}-{kind}-{db}',sources={**base,'Eve':eve(form,((1,65535,db,kind),))})
for material,amount in [(20,0),(20,255),(0,0),(0,255),(65535,1)]:
    add(f'material-{material}-{amount}','recipes',{'SmithData_C':table(smith(material=material,amount=amount)),'ItemData_C':base['ItemData_C']})
for raw in [b'',b'123',p('i',0),p('i',-1),p('i',20001),table(smith(65535)),table(smith(),smith()),table(p('H',1)+smith(),p('H',1)+smith()),base['SmithData_C']+b'!']:
    add('recipe-error-'+str(len(cases)),'recipes',{'SmithData_C':raw,'ItemData_C':base['ItemData_C']})
add('ambiguous-missing-material','recipes',{'SmithData_C':table(p('H',1)+smith(material=65535),p('H',2)+smith()),'ItemData_C':base['ItemData_C']})
for value in ['', ' ', '\u001c', '\x00', '  甲\u0085', '😀'*160, '😀'*161, 'a'*159+' ', 'a'*160+' ', 'a\n', '\ufeff']:
    add('scene-name-'+str(len(cases)),'scenes',{'ScenesData_C':table(stage()),'TextData_C':texts(scene=value)})
for nameid in [0,10,65535,4294967295]:
    add(f'scene-name-id-{nameid}','scenes',{'ScenesData_C':table(stage(name=nameid)),'TextData_C':texts()})
add('scene-order','scenes',{'ScenesData_C':table(stage(65535),stage(0),stage(7)),'TextData_C':texts()})
for value in ['', ' ', '\u001c', '\x00', '😀'*8192, '😀'*8193]:
    add('strict-name-'+str(len(cases)),sources={**base,'TextData_C':texts(name=value)})
add('empty-scenes-precedes-expedition',sources={**base,'ScenesData_C':table(),'AdventureData_C':b''})
add('empty-talks-precedes-expedition',sources={**base,'TalkData_C':table(),'AdventureData_C':b''})
mismatched=bytearray(base['Eve']);struct.pack_into('<H',mismatched,14,99)
add('door-model-mismatch',sources={**base,'Eve':bytes(mismatched)})
add('recipe-before-door-model',sources={**base,'Eve':bytes(mismatched),'SmithData_C':b''})
add('door-before-empty-scene',sources={**base,'Eve':bytes(mismatched),'ScenesData_C':table()})
add('career-before-npc',sources={**base,'NpcData_C':b'','NpcCareerData_C':b''})
add('reviewed1296-pin-required',version='1296_2026_11_04_13_34_19_13')
add('unknown-item-version',version='unknown')

out=Path(__file__).resolve().parent
raw=json.dumps(cases,ensure_ascii=True,separators=(',',':')).encode()
compressed=gzip_json_bytes(raw.decode())
(out/'Fixtures/runtime-candidate.json.gz').write_bytes(compressed)
sources=['wlre/services/world/bundle_runtime_1275.py','wlre/services/world/dynamic_bundle_runtime.py','wlre/services/world/scene_names_1275.py','wlre/services/world/itemdata_v1.py']
lines=['// Generated from exact retained Python runtime AST blocks. Synthetic inputs only.',
'using System.Text.Json;','using Lala.Core.Tests.TestSupport;','namespace Lala.Core.Tests.Catalogs.RuntimeCandidate;',
'public static class RuntimeCandidateOracleCases','{',f'    public const int Count = {len(cases)};',
'    public static IEnumerable<object[]> CaseIds() { for (int i = 0; i < Count; i++) yield return new object[] { i }; }',
'    public static IEnumerable<object[]> SourceRefs()','    {']
for path in sources:
    digest=hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    lines.append(f'        yield return new object[] {{ "{path}", "{digest}" }};')
lines+=['    }','    private static readonly Lazy<JsonElement> Data = new(() => JsonDocument.Parse(GzipJson.DecodeResource(',
'        "Lala.Core.Tests.Catalogs.RuntimeCandidate.Fixtures.runtime-candidate.json.gz",',
f'        "{hashlib.sha256(compressed).hexdigest()}", "{hashlib.sha256(raw).hexdigest()}" )).RootElement);',
'    internal static JsonElement Case(int id) => Data.Value[id];','}']
(out/'RuntimeCandidateOracleCases.cs').write_text('\n'.join(lines)+'\n')
print(f'{len(cases)} cases, {len(compressed)} compressed bytes, {len(raw)} decoded bytes')
print('baseline',cases[0]['error'])
