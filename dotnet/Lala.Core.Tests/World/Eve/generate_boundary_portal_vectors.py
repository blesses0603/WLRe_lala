"""Actual retained Python parser, reference, boundary/conflict and coverage oracle.

Synthetic v115 bytes plus explicit typed geometry edits. No mocks, user assets,
network, source authentication, activation or packet operations.
"""
from pathlib import Path
import sys, base64, hashlib, json, copy, struct, gzip
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'dotnet/Lala.Core.Tests/TestSupport')]
from gzip_json_fixture import gzip_json_bytes
from test_event_convey_portals import fixture
from wlre.services.world.doors_1275 import parse_verified_doors
from wlre.services.world.portal_links_1275 import parse_stage_map_portals,parse_eve_door_links
from wlre.services.world.portal_evidence_1275 import read_only_portal_evidence,read_only_stage_portal_markers,read_only_door_link_routes
from wlre.services.world.boundary_portals import boundary_portal_bindings,reconcile_route_conflicts
from wlre.services.world.portal_coverage import audit_portal_coverage

# Exact reviewed source fingerprints, never resource provenance.
PINS={'boundary_portals.py': '47ba6e52bbc9a7b7da67c64c3fd6fd43e576735231f410cfbbbf1a692c94ddb9', 'portal_coverage.py': 'd9042fb84f2a3e8f9f1ce918913d56d8efee7800f433987b0e7f7b9f05a1a07a', 'portal_links_1275.py': '4325e3e71ce067f874532607ecc5719e1810666a0af0b6fcc7f23677bcac9a73', 'portal_evidence_1275.py': '8cd42819ac69c50677d34c7e72aa7066d60310a98b24033a976ee1892891f6e4', 'portal_schema.py': '57b484033ca28183f01b83248b27bb62e88db12249ca3ca9c8cec872cef095ed', 'event_portals.py': '0bed2a5f1d2eb7b2127358b5664e5f265bc80b55efd08044194332137ed2865f', 'doors_1275.py': '012862d1ec7cd7e7361aceaba2f3375ded192189a980956863e6e58035b93ba6'}
for path,digest in PINS.items():
    assert hashlib.sha256((ROOT/'wlre/services/world'/path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==digest,path

def table(rows): return struct.pack('<i',len(rows))+b''.join(struct.pack('<HBHIHHIB',*r) for r in rows)
def linktext(rows,scene=60000):
    return '事件ID='+str(scene)+'\n'+''.join(f'原場景位置[X:{x},Y:{y}][{d}][X:{ax},Y:{ay}]\n' for x,y,d,ax,ay in rows)
def routebytes(rows):return struct.pack('<i',len(rows))+b''.join(struct.pack('<6H',*r) for r in rows)
def clean(value):
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items() if k not in ('can_send_packets','live_transfer_verified','event_index')}
    if isinstance(value,(tuple,list)):return [clean(v) for v in value]
    return value
def entries(value):return [dict(key=list(k),value=clean(v)) for k,v in sorted(value.items())]
def output(pos,dest,doors,evidence):
    return dict(positions=entries(pos),destinations=entries(dest),issues=[dict(key=[s,d['index']],value=d['portal_resolution_issue']) for s,ds in doors.items() for d in ds if d.get('portal_resolution_issue')],evidence=entries(evidence))
base_stages={k:dict(pos_x_ratio=1,pos_y_ratio=1,map_width=10000,map_height=10000,small_offset_x=0,small_offset_y=0) for k in (60000,58001,11016,12000)}
cases=[]
def add(name,markers=None,links=None,routes=None,edits=None,event=False,targets=(58001,),missing=False,stage_edits=None,remove=(),raw_stage=None,raw_link=None,names=(),passes=1,door_scene=60000,route_edits=None):
    raw=fixture(targets,missing); base=parse_verified_doors(raw)[60000][0]
    if not event:base['touch_event_records']=[]
    door_edits=[{}] if edits is None else edits
    doors={door_scene:[dict(copy.deepcopy(base),**e) for e in door_edits]}
    stages=copy.deepcopy(base_stages)
    for k,v in (stage_edits or {}).items():stages.setdefault(k,copy.deepcopy(base_stages[60000])).update(v)
    for k in remove:stages.pop(k,None)
    sr=raw_stage if raw_stage is not None else table(markers) if markers is not None else None
    lr=raw_link if raw_link is not None else links.encode('utf-16-le') if links is not None else None
    rr=routebytes(routes) if routes is not None else None
    expected={}
    try:expected['parsed_stage']=entries(parse_stage_map_portals(sr)) if sr is not None else None
    except ValueError:expected['stage_error']=True
    try:expected['parsed_links']={str(k):v for k,v in parse_eve_door_links(lr).items()} if lr is not None else None
    except ValueError:expected['link_error']=True
    evidence={};marks=[];rs=[]
    try:
        if lr is not None:evidence=read_only_portal_evidence(sr,lr,doors,stages)
        expected['references']=entries(evidence)
    except ValueError:expected['reference_error']=True
    try:
        if sr is not None:marks=read_only_stage_portal_markers(sr,stages)
        expected['markers']=clean(marks)
    except ValueError:expected['marker_error']=True
    try:
        if rr is not None:rs=read_only_door_link_routes(rr,stages)
        for i,e in (route_edits or {}).items():rs[i].update(e)
        expected['routes']=clean(rs)
    except ValueError:expected['route_error']=True
    pos={};dest={};expected['passes']=[]
    for _ in range(passes):
        try:
            pos,dest=boundary_portal_bindings(sr,lr,doors,stages)
            expected['passes'].append(output(pos,dest,doors,evidence))
        except ValueError:expected['binding_error']=True;break
    reconcile_route_conflicts(pos,dest,rs,evidence)
    expected['conflicts']=output(pos,dest,doors,evidence)
    expected['coverage']=clean(audit_portal_coverage(doors,stages,sr,lr,pos,dest,{tuple(k):'label' for k in names},evidence,rs,marks))
    b64=lambda b:base64.b64encode(b).decode() if b is not None else None
    cases.append(dict(name=name,raw=b64(raw),door_scene=door_scene,door_edits=door_edits,no_events=not event,stages=stages,stage_raw=b64(sr),link_raw=b64(lr),route_raw=b64(rr),route_edits=route_edits or {},names=names,expected=expected))

m=lambda kind=2,event=1,x=60,y=1100,name=1,scene=60000:(scene,kind,0,event,x,y,name,0)
l=linktext([(60,1100,58001,100,200)])
add('missing-both');add('empty-both',markers=[],links='事件ID=60000\n')
add('link-only',links=l);add('normal-label-link',markers=[m()],links=l,names=[(60000,1)])
add('kind2-server-decided',markers=[m(event=0)]);add('kind3-target',markers=[m(3,58001)],names=[(60000,58001)])
add('kind3-zero-target',markers=[m(3,0)]);add('kind3-unknown',markers=[m(3,65000)])
add('kind3-uint-max',markers=[m(3,4294967295)]);add('kind4-reference',markers=[m(4,58001)])
add('duplicate-markers',markers=[m(),m()],links=l)
add('triple-markers',markers=[m(),m(),m()],links=l)
add('marker-zero-scene',markers=[m(scene=0)],links=l)
add('unrecognized-kind',markers=[m(6)],links=l)
add('orphan-source-target',markers=[m(scene=61000)],links=linktext([(1,1,62000,2,2)],scene=61000))
add('scene-without-doors',markers=[m()],links=l,edits=[])
add('duplicate-doors',markers=[m()],links=l,edits=[{},{}])
add('zero-door-id',markers=[m()],links=l,edits=[{'index':0}])
add('missing-touch',links=l,edits=[{'touch_event_ids':[]}])
add('swapped-ordinal',markers=[m(event=1),m(event=2)],links=linktext([(1000,1000,58001,1,2),(2000,2000,11016,3,4)]),edits=[dict(index=1,x=100,y=100,right=102,bottom=102,sign_type=1),dict(index=2,x=50,y=50,right=52,bottom=52,sign_type=1)])
add('two-links-same-region',links=linktext([(60,1100,58001,1,2),(61,1100,11016,3,4)]))
add('unknown-then-valid-link',links=linktext([(60,1100,65000,1,2),(61,1100,58001,3,4)]))
add('unknown-ambiguity-label-no-resurrection',markers=[m(3,58001)],links=linktext([(60,1100,65000,1,2),(61,1100,58001,3,4)]))
add('marker-link-conflict',markers=[m(3,11016)],links=l)
add('marker-two-targets',markers=[m(3,11016),m(3,58001)])
add('marker-prefer-named-target',markers=[m(2,1,name=2),m(3,58001,name=0),m(3,58001,x=70,name=7)])
add('link-marker-label-preference',markers=[m(2,1,name=0),m(3,58001,x=70,name=7),m(3,58001,x=65,name=8)],links=l)
for sign in (1,2,3,4,5):
    add('sign-'+str(sign),links=linktext([(1000,1000,58001,1,2)]),edits=[dict(index=9,x=51,y=51,right=53,bottom=53,sign_type=sign)])
    add('sign-offset-mismatch-'+str(sign),links=linktext([(1000,1000,58001,1,2)]),edits=[dict(index=9,x=51,y=51,right=53,bottom=53,sign_type=sign,sign_x=1)])
add('line-no-binding',links=l,edits=[{'bottom':1}])
add('event-only',event=True);add('event-multiple',event=True,targets=(58001,11016));add('event-missing',event=True,missing=True,links=l)
add('event-conflict-persistent',event=True,links=linktext([(60,1100,11016,1,2)]),passes=3)
add('event-unknown',event=True,targets=(65000,),links=l)
add('event-allows-independent-subset',event=True,targets=(58001,11016),routes=[(60000,70,1110,58001,1,2)])
# midpoint for the base door is (70,1110).
add('event-revokes-extra-target',event=True,targets=(58001,11016),routes=[(60000,70,1110,12000,1,2)])
for suffix,route in [('conflict',(60000,60,1100,11016,1,2)),('same',(60000,60,1100,58001,1,2)),('otherpoint',(60000,61,1100,11016,1,2)),('otherscene',(11016,60,1100,11016,1,2))]:
    add('route-'+suffix,markers=[m()],links=l,routes=[route])
add('route-unverified',links=l,routes=[(60000,60,1100,11016,1,2)],route_edits={0:{'position_verified':False}})
add('server-decided-single-route',markers=[m()],routes=[(60000,60,1100,58001,1,2)])
add('server-decided-multiple-route',markers=[m()],routes=[(60000,60,1100,58001,1,2),(60000,60,1100,11016,1,2)])
for delta in ({'pos_x_ratio':0},{'pos_y_ratio':0},{'pos_x_ratio':255,'pos_y_ratio':255},{'map_width':0,'map_height':0},{'map_width':65535,'map_height':65535}):
    add('geometry-'+str(len(cases)),markers=[m()],links=l,routes=[(60000,60,1100,58001,1,2)],stage_edits={60000:delta})
for edit in ({'x':4294967295},{'x':0},{'x':0,'sign_x':20},{'sign_x':4294967295}):add('uint-'+str(len(cases)),markers=[m()],links=l,edits=[edit])
for raw in (b'',b'x',struct.pack('<i',-1),struct.pack('<i',100001),table([m()])+b'x'):
    add('bad-stage-'+str(len(cases)),raw_stage=raw,links=l)
for text in ('','bad','事件ID=0','事件ID=60000\n事件ID=60000','事件ID=60000\n原場景位置[X:1,Y:2][0][X:3,Y:4]','事件ID=60000\n原場景位置[X:65536,Y:2][58001][X:3,Y:4]','事件ID=60000\n原場景位置[X:1,Y:2][58001][X:3,Y:4][extra]'):
    add('bad-link-'+str(len(cases)),markers=[m()],raw_link=text.encode('utf-16-le'))
for raw in (b'x',b'\x00\xd8',b'\x00\xdc'):add('bad-encoding-'+str(len(cases)),raw_link=raw)
for text in ('\ufeff\ufeff'+l,l.replace('事件ID','[事件ID]'),l.replace('X:','甲：').replace('Y:','乙：'),l.replace('\n','\x85'),l.replace('\n','\x1c'),l.translate(str.maketrans('0123456789','０１２３４５６７８９')),l.translate(str.maketrans('0123456789','𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡')),l.replace('原場景位置','原場景位置 arbitrary ').replace(']\n','] trailing\n')):
    add('accepted-link-'+str(len(cases)),markers=[m()],raw_link=text.encode('utf-16-le'))
# wide duplicate marker IDs survive coverage without ushort truncation.
add('wide-duplicate-coverage',markers=[m(event=4294967295),m(event=4294967295)],links=l,edits=[])
add('zero-name-marker-sorting',markers=[m(2,0,x=65,name=0),m(3,0,x=60,name=8)],names=[(60000,0)])
add('markers-all-kinds',markers=[m(kind,kind) for kind in range(6)])
# Source parser allows zero-scene rows but marker projection rejects them, including ignored kinds.
add('zero-scene-ignored-kind',markers=[m(0,0,scene=0)])
add('empty-link-text-whitespace',raw_link=' \n'.encode('utf-16-le'))
add('scene-only-link-header',links='事件ID=61000\n',remove=(12000,))
add('route-unknown-endpoint',routes=[(61000,1,2,62000,3,4)])
add('zero-route-source',routes=[(0,1,2,58001,3,4)])
add('zero-route-target',routes=[(60000,1,2,0,3,4)])

add('alternating-python-whitespace',raw_link=('\x1f \x1f '+l.replace('\n','\n\x1f \x1f ')+'\x1f ').encode('utf-16-le'))
add('excess-decimal-zeros',raw_link=('事件ID='+'0'*5000+'60000').encode('utf-16-le'))

payload=json.dumps(cases,ensure_ascii=True,separators=(',',':'));packed=gzip_json_bytes(payload)
Path(__file__).with_name('Fixtures').joinpath('boundary-portals.json.gz').write_bytes(packed)
cs='''// Generated actual Python oracle. Fingerprints do not establish official resource provenance.
using System.Text.Json;
using Lala.Core.Tests.TestSupport;
namespace Lala.Core.Tests.World.Eve;
public static class BoundaryPortalPythonVectors
{
    public const int Count = COUNT;
    public static IEnumerable<object[]> Cases()
    {
CASES
    }
    public static JsonElement Read(int index) => Fixture.Value[index];
    private static readonly Lazy<JsonElement> Fixture = new(() =>
    {
        using var doc = JsonDocument.Parse(GzipJson.DecodeResource("Lala.Core.Tests.World.Eve.Fixtures.boundary-portals.json.gz", "PACKED", "RAW"));
        if (doc.RootElement.GetArrayLength() != Count) throw new InvalidDataException("Boundary portal fixture count mismatch");
        return doc.RootElement.Clone();
    });
}
'''.replace('COUNT',str(len(cases))).replace('CASES','\n'.join('        yield return new object[] { '+json.dumps(c['name'])+', '+str(i)+' };' for i,c in enumerate(cases))).replace('PACKED',hashlib.sha256(packed).hexdigest()).replace('RAW',hashlib.sha256(payload.encode()).hexdigest())
Path(__file__).with_name('BoundaryPortalPythonVectors.cs').write_text(cs)
print('vectors',len(cases),'pins',PINS)
