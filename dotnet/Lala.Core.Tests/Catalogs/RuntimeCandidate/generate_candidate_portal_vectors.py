"""Ten-table owned inputs with actual Python event-only reconciliation and coverage.

Reuses the retained candidate fixture and actual synthetic Eve bytes. No source
verification, cache, downloads, optional source fabrication or gameplay execution.
"""
from pathlib import Path
import sys,base64,hashlib,gzip,json,struct,ast
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'dotnet/Lala.Core.Tests/TestSupport')]
from gzip_json_fixture import gzip_json_bytes
from test_event_convey_portals import fixture
from wlre.services.world.doors_1275 import parse_verified_doors
from wlre.services.instance_catalog import parse_stages
from wlre.services.world.event_portals import reconcile_event_portals
from wlre.services.world.boundary_portals import reconcile_route_conflicts
from wlre.services.world.portal_coverage import audit_portal_coverage
PINS={
'wlre/services/instance_catalog.py':'c51e76030b6f628e75ec559ee61f207f808e8f392dbed8d732d38282bfa9032e',
'wlre/services/world/portal_evidence_1275.py':'8cd42819ac69c50677d34c7e72aa7066d60310a98b24033a976ee1892891f6e4',
'wlre/services/world/event_portals.py':'0bed2a5f1d2eb7b2127358b5664e5f265bc80b55efd08044194332137ed2865f',
'wlre/services/world/boundary_portals.py':'47ba6e52bbc9a7b7da67c64c3fd6fd43e576735231f410cfbbbf1a692c94ddb9',
'wlre/services/world/portal_coverage.py':'d9042fb84f2a3e8f9f1ce918913d56d8efee7800f433987b0e7f7b9f05a1a07a',
'wlre/services/world/doors_1275.py':'012862d1ec7cd7e7361aceaba2f3375ded192189a980956863e6e58035b93ba6',
}
for path,digest in PINS.items():assert hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==digest,path
source=Path(__file__).with_name('Fixtures')/'runtime-candidate.json.gz'
assert hashlib.sha256(source.read_bytes()).hexdigest()=='d9e7d7c81118b6643ed8dfc49335188fc92b140d5dc70152d60b7afd9ad02348'
base={k:base64.b64decode(v) for k,v in json.loads(gzip.decompress(source.read_bytes()))[0]['inputs'].items()}
def stage(id,rx=2,ry=4,width=9000,height=15000):
    row=bytearray(76);struct.pack_into('<HHIH',row,0,id,0,30,99)
    struct.pack_into('<HHBBBHH',row,52,width,height,0,rx,ry,0,0)
    return bytes(row)
def stages(ids=(60000,58001,11016),**kwargs):return struct.pack('<i',len(ids))+b''.join(stage(id,**kwargs) for id in ids)
def clean(value):
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items() if k not in ('can_send_packets','live_transfer_verified')}
    if isinstance(value,(tuple,list)):return [clean(v) for v in value]
    return value
cases=[]
def add(name,raw=None,stage_raw=None,edits=None,extra=None):
    inputs=dict(base)
    if raw is not None:
        raw=bytearray(raw)
        offsets={'x':55,'y':59,'right':67,'bottom':71,'sign_type':75,'sign_x':76,'sign_y':80}
        for key,value in (edits or {}).items():struct.pack_into('<B' if key=='sign_type' else '<I',raw,offsets[key],value)
        inputs['Eve']=bytes(raw)
        parsed=parse_verified_doors(bytes(raw))[60000][0]
        for key,value in (edits or {}).items():assert parsed[key]==value
    if stage_raw is not None:inputs['ScenesData_C']=stage_raw
    inputs.update(extra or {})
    doors=parse_verified_doors(inputs['Eve']);ss=parse_stages(inputs['ScenesData_C'])
    positions={};destinations={};reconcile_event_portals(doors,ss,positions,destinations)
    reconcile_route_conflicts(positions,destinations,[],{})
    coverage=audit_portal_coverage(doors,ss,None,None,positions,destinations,{}, {},[],[])
    cases.append(dict(name=name,inputs={k:base64.b64encode(v).decode() for k,v in inputs.items()},expected=dict(
        positions=[dict(key=list(k),value=clean(v)) for k,v in sorted(positions.items())],
        destinations=[dict(key=list(k),value=clean(v)) for k,v in sorted(destinations.items())],
        issues=[dict(key=[s,d['index']],value=d['portal_resolution_issue']) for s,rows in doors.items() for d in rows if d.get('portal_resolution_issue')],
        coverage=clean(coverage))))
add('owned-existing-flow')
add('event-single',fixture(),stages())
add('event-multiple',fixture((58001,11016)),stages())
add('unknown-target',fixture((65000,)),stages())
add('missing-convey',fixture(missing=True),stages())
add('zero-ratio',fixture(),stages(rx=0))
add('zero-map',fixture(),stages(width=0,height=0))
add('line-boundary',fixture(),stages(),{'bottom':1})
add('anchor-sign',fixture(),stages(),{'sign_type':2,'x':51,'y':51})
add('uint-max-position',fixture(),stages(),{'x':4294967295})
add('orphan-source-scene',fixture(),stages((58001,11016)))
add('unrelated-optional-inputs-ignored',fixture(),stages(),extra={'StageMapData_C':b'untrusted optional bytes','EveDoorLinks':b'bad','DoorLinkData_C':b'bad'})
add('same-scene-conditional',fixture((60000,58001)),stages())
add('duplicate-target-conveys',fixture((58001,58001)),stages())
# A separately labeled defensive-budget input: real Python decoders accept its layout,
# but the C# candidate deliberately rejects amplification before flattening shared transfers.
source_tree=ast.parse((ROOT/'dotnet/Lala.Core.Tests/World/Eve/generate_eve_door_vectors.py').read_text())
functions=[n for n in source_tree.body if isinstance(n,ast.FunctionDef) and n.name in ('common','door','parameter','event','convey','scene','container')]
env={'struct':struct,'u16':lambda v:struct.pack('<H',v),'u32':lambda v:struct.pack('<I',v),'name':lambda v=b'':v.ljust(20,b'\0')[:20]}
exec(compile(ast.Module(body=functions,type_ignores=[]),'owned-eve-constructors','exec'),env)
effect=env['parameter'](signed=True,style=96)
event=env['event'](blocks=[(env['parameter'](),[effect]*255)]*11)
large=env['container']([(60000,env['scene']({1:[env['door'](events=b'\x07'*255)],4:[event],6:[env['convey']()]}))])
from wlre.services.world.eve_v115 import derive_eve_indexes
derive_eve_indexes(large)
parsed=parse_verified_doors(large)
assert len(parsed[60000][0]['touch_event_records'])==255
assert sum(len(e['convey_transfers']) for e in parsed[60000][0]['touch_event_records'])==715275
cases[0]['budget_eve']=base64.b64encode(large).decode()
payload=json.dumps(cases,ensure_ascii=True,separators=(',',':'));packed=gzip_json_bytes(payload)
Path(__file__).with_name('Fixtures').joinpath('candidate-portals.json.gz').write_bytes(packed)
cs='''// Generated actual Python observations for owned ten-table fixtures. No provenance claim.
using System.Text.Json;
using Lala.Core.Tests.TestSupport;
namespace Lala.Core.Tests.Catalogs.RuntimeCandidate;
public static class CandidatePortalOracleCases
{
    public const int Count = COUNT;
    public static IEnumerable<object[]> Cases()
    {
CASES
    }
    internal static JsonElement Read(int index) => Fixture.Value[index];
    private static readonly Lazy<JsonElement> Fixture = new(() =>
    {
        using var doc = JsonDocument.Parse(GzipJson.DecodeResource("Lala.Core.Tests.Catalogs.RuntimeCandidate.Fixtures.candidate-portals.json.gz", "PACKED", "RAW"));
        if (doc.RootElement.GetArrayLength() != Count) throw new InvalidDataException("Candidate portal fixture count mismatch");
        return doc.RootElement.Clone();
    });
}
'''.replace('COUNT',str(len(cases))).replace('CASES','\n'.join('        yield return new object[] { '+json.dumps(c['name'])+', '+str(i)+' };' for i,c in enumerate(cases))).replace('PACKED',hashlib.sha256(packed).hexdigest()).replace('RAW',hashlib.sha256(payload.encode()).hexdigest())
Path(__file__).with_name('CandidatePortalOracleCases.cs').write_text(cs)
print('generated',len(cases),'candidate portal vectors')
