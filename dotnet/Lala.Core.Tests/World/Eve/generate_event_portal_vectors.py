"""Actual Python event reconciliation over decoded synthetic Eve bytes; no mocks/I/O authority.

Geometry edits are deliberately post-decode to exercise unsigned typed input boundaries.
Hashes below fingerprint the oracle and fixtures, not official resource provenance.
"""
from pathlib import Path
import sys, base64, hashlib, json, copy
ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT/'tests'), str(ROOT/'dotnet/Lala.Core.Tests/TestSupport')]
from gzip_json_fixture import gzip_json_bytes
from test_event_convey_portals import fixture
from test_boundary_portals import stages
from wlre.services.world.doors_1275 import parse_verified_doors
from wlre.services.world.event_portals import reconcile_event_portals

PINS = {
    'wlre/services/world/event_portals.py':'0bed2a5f1d2eb7b2127358b5664e5f265bc80b55efd08044194332137ed2865f',
    'wlre/services/world/boundary_portals.py':'47ba6e52bbc9a7b7da67c64c3fd6fd43e576735231f410cfbbbf1a692c94ddb9',
    'wlre/services/world/portal_evidence_1275.py':'8cd42819ac69c50677d34c7e72aa7066d60310a98b24033a976ee1892891f6e4',
    'wlre/services/world/doors_1275.py':'012862d1ec7cd7e7361aceaba2f3375ded192189a980956863e6e58035b93ba6',
}
for path, digest in PINS.items():
    assert hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==digest, path
cases=[]
def add(name, targets=(58001,), missing=False, edit=None, stage=None, prior=None, duplicate=False, no_events=False, remove_stage=False, passes=1):
    raw=fixture(targets,missing)
    doors=parse_verified_doors(raw)
    edit=edit or {}; doors[60000][0].update(edit)
    if no_events: doors[60000][0]['touch_event_records']=[]
    if duplicate: doors[60000].append(copy.deepcopy(doors[60000][0]))
    ss=stages(); ss[60000].update(stage or {})
    if remove_stage: del ss[60000]
    pos={}; dest={}
    if prior:
        if 'position' in prior: pos[60000,3]=copy.deepcopy(prior['position'])
        if 'destination' in prior: dest[60000,3]=copy.deepcopy(prior['destination'])
        if prior.get('issue'): doors[60000][0]['portal_resolution_issue']=prior['issue']
    outputs=[]
    for _ in range(passes):
        reconcile_event_portals(doors,ss,pos,dest)
        outputs.append(dict(positions=[dict(key=list(k),value=v) for k,v in sorted(pos.items())],
                            destinations=[dict(key=list(k),value=v) for k,v in sorted(dest.items())],
                            issues=[dict(key=[60000,d['index']],value=d['portal_resolution_issue']) for d in doors[60000] if d.get('portal_resolution_issue')]))
        outputs[-1]=copy.deepcopy(outputs[-1])
    cases.append(dict(name=name, raw=base64.b64encode(raw).decode(), edit=edit, stages={str(k):v for k,v in ss.items()}, prior=prior,
                      duplicate=duplicate,no_events=no_events,expected=outputs))

add('single');add('multiple',targets=(58001,11016));add('duplicate-targets',targets=(58001,58001));add('zero-target',targets=(0,));add('unknown',targets=(65530,))
add('missing',missing=True);add('mixed-known-unknown',targets=(58001,65530));add('no-transfers',no_events=True)
add('missing-stage',remove_stage=True);add('duplicate-index',duplicate=True);add('zero-index',edit={'index':0})
for sign in range(7): add(f'sign-{sign}',edit={'sign_type':sign})
for edit in ({'bottom':1},{'right':1},{'right':1,'bottom':1},{'right':0},{'bottom':0},{'x':0},{'x':0,'sign_x':20},{'x':4294967295},{'sign_x':4294967295},{'right':4294967295}):
    add('geometry-'+str(len(cases)),edit=edit)
for stage in ({'pos_x_ratio':0},{'pos_y_ratio':0},{'pos_x_ratio':255,'pos_y_ratio':255},{'map_width':0,'map_height':0},{'map_width':0},{'map_width':65535,'map_height':65535},{'small_offset_x':65535,'small_offset_y':65535}):
    add('stage-'+str(len(cases)),stage=stage)
for x in (65534,65535,65536):
    add('point-limit-'+str(x),edit={'sign_type':2,'x':1,'y':1,'sign_x':x},stage={'pos_x_ratio':1})
# Existing position intentionally outside new bounds: Python preserves it verbatim.
p=dict(scene=60000,index=3,x=65000,y=65000,position_verified=False,projection_guard=None,source_kind='prior',trigger_bounds=None,binding_kind='prior',link_index=9,raw_link_x=11,raw_link_y=12,pos_x_ratio=2,pos_y_ratio=4)
d=dict(scene=60000,index=3,destination=58001,link_index=9,matched_stage_map=True,stage_marker_only=True,stage_marker_kind=3,stage_marker_event_id=58001,stage_marker_name_id=123,x=11,y=12,arrival_x=13,arrival_y=14)
add('preserve-prior-point-and-metadata',prior={'position':p,'destination':d},passes=2)
add('conflict-tombstone',prior={'position':p,'destination':dict(d,destination=11016)},passes=3)
add('preexisting-issue',prior={'position':p,'destination':d,'issue':'existing_conflict'},passes=2)
add('missing-revokes-prior',missing=True,prior={'position':p,'destination':d})
add('unknown-revokes-prior',targets=(65530,),prior={'position':p,'destination':d})
add('no-transfers-preserves-prior',no_events=True,prior={'position':p,'destination':d})
add('invalid-geometry-preserves-prior',edit={'x':4294967295},prior={'position':p,'destination':d})
# Deterministic grid edges stress signed math and line/rectangle ordering.
for sign in (1,2,4,5):
    for x in (0,1,2,3277,4294967295):
        for ratio in (1,2,255):
            add(f'grid-{sign}-{x}-{ratio}',edit={'sign_type':sign,'x':x,'right':x,'sign_x':1},stage={'pos_x_ratio':ratio})
raw=json.dumps(cases,ensure_ascii=True,separators=(',',':')).encode()
packed=gzip_json_bytes(raw.decode())
path=Path(__file__).with_name('Fixtures')/'event-portals.json.gz';path.write_bytes(packed)
# Helper uses the same canonical fixture serializer.
import gzip
raw=gzip.decompress(packed)
cs='''// Generated by generate_event_portal_vectors.py; synthetic actual Python oracle, not resource provenance.
using System.Text.Json;
using Lala.Core.Tests.TestSupport;
namespace Lala.Core.Tests.World.Eve;
public static class EventPortalPythonVectors
{
    public const int Count = COUNT;
    public static IEnumerable<object[]> Cases()
    {
CASES
    }
    public static JsonElement Read(int index) => Fixture.Value[index];
    private static readonly Lazy<JsonElement> Fixture = new(() =>
    {
        using var doc = JsonDocument.Parse(GzipJson.DecodeResource("Lala.Core.Tests.World.Eve.Fixtures.event-portals.json.gz", "PACKED", "RAW"));
        if (doc.RootElement.GetArrayLength() != Count) throw new InvalidDataException("Event portal fixture count mismatch");
        return doc.RootElement.Clone();
    });
}
'''.replace('COUNT',str(len(cases))).replace('CASES','\n'.join('        yield return new object[] { '+json.dumps(c['name'])+', '+str(i)+' };' for i,c in enumerate(cases))).replace('PACKED',hashlib.sha256(packed).hexdigest()).replace('RAW',hashlib.sha256(raw).hexdigest())
Path(__file__).with_name('EventPortalPythonVectors.cs').write_text(cs)
for pth in ('wlre/services/world/event_portals.py','wlre/services/world/boundary_portals.py','wlre/services/world/portal_evidence_1275.py','wlre/services/world/doors_1275.py'):
    print(pth,hashlib.sha256((ROOT/pth).read_bytes().replace(b'\r\n',b'\n')).hexdigest())
print('vectors',len(cases))
