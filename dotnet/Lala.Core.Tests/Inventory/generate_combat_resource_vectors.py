"""Real pure combat_resources helpers with explicit pinned synthetic catalogs, no runtime activation."""
import copy, hashlib, json, os, random, sys
from pathlib import Path
from types import SimpleNamespace
os.environ['WLRE_DISABLE_AUTO_CATALOG']='1'
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(Path(__file__).resolve().parents[1]/'TestSupport')]
from gzip_json_fixture import csharp_gzip_json
from wlre.services.items import combat_resources as source
from wlre.services.items.live_combat_catalog import _pinned
from wlre.core.state_session_events import apply_session_event
R=random.Random(202611080212)
CASES=[]
BASE=dict(keys={'1':1001,'2':1002,'3':1001,'4':15003,'5':0},
    items={str(i):dict(kind=i,fit_type=i%12,skill_link=0,attributes=[]) for i in range(12)},
    skills={str(i):dict(ID=i,LvLimit=level,HitStatus=0,TargetKind=0) for i,level in [(1001,10),(1002,2),(15003,5),(15004,7),(15005,0)]},
    npcs={'80':dict(name='目錄名稱',skills=[1001,0,1002,1001,15003]),'81':dict(skills=[15003,1001])},
    characters=[dict(sex=1,head=2,skill=15004,body=11),dict(sex=1,head=2,skill=15005,body=12)], element_weights={})
BASE['items'].update({'100':dict(kind=3,fit_type=3,skill_link=1001),'101':dict(kind=7,fit_type=11,skill_link=1002),'102':dict(skill_link=999),'103':dict(skill_link=15005),'104':dict(skill_link=15003)})
def state(player=None,companions=None,role=7,active=None):
    return dict(player={} if role is None else dict(role_id=role,sex=1,head=2,name='角色名稱'),knowledge=dict(player=player or {},companions=companions or {},active_npc_id=active))
def actor(**kw):return dict(pid=7,master_id=0,npc_index=0,col=1,row=1,sex=1,head=2,equips=[],**kw)
def companion(index=1,npc=80,simple=False):
    stats=dict(index=index,npc_id=npc,exp=5,level=4,str=1,con=2,int=3,wis=4,agi=5,faith=6,can_grow=1,sport_exp=7,degree=0,potential=8,modeling=9,use_up_stats=10)
    if not simple:stats.update(hp=-10,sp=0,die=0,skill_potential=12,name='伺服器名稱',sublime_count=13,party_index=14)
    return dict(ready=True,npc_id=npc,index=index,stats=stats,skills={},server_skill_slots=[dict(level=3,exp=4),dict(level=0,exp=0),dict(level=1,exp=5),dict(level=7,exp=2),dict(level=9,exp=1)],equips=[])
def add(kind,**inputs):
    cat=copy.deepcopy(inputs.pop('catalog',BASE)); before=copy.deepcopy(inputs)
    _pinned.set(cat)
    if kind=='learned':
        raw=source.learned(inputs['state'],inputs['actor']); expected=[dict(id=int(sid),**v) for sid,v in raw.items()]
    elif kind=='weapon':expected=source.weapon_group(inputs['actor'])
    elif kind=='target':expected=source.target_valid(inputs['actor'],inputs['target'],inputs['skill'])
    elif kind=='heal':expected=source.heal_effects(inputs['item_id'])
    elif kind=='history':
        current=SimpleNamespace(**state(dict(skills={},stats={}),{}),inventory=dict(items={},reserved={}),attributes={})
        expected=[]
        a=actor();a.update(pid=80,master_id=7,npc_index=1)
        for event in inputs['events']:
            source.apply_live(current,event)
            if event['type']=='attribute_set':apply_session_event(current,event)
            profile=current.knowledge['companions'].get('1',{})
            learned=source.learned(dict(player=current.player,knowledge=current.knowledge),a)
            expected.append(copy.deepcopy(dict(order=list(profile.get('skills',{})),skills=profile.get('skills',{}),removed=profile.get('removed_skill_ids'),learned=[dict(id=int(sid),**v) for sid,v in learned.items()])))
    elif kind=='field':
        result,player=source.field_context(inputs['state'])
        def equip(v):return {k:v[k] for k in ('item_id','design_id','damage') if k in v}
        units=copy.deepcopy(list(result['battle_units'].values()))
        for v in units:v['equips']=[equip(e) for e in v['equips']]
        profile=inputs['state']['knowledge']['player']
        expected=dict(units=units,equips=None if 'equips' not in profile else [equip(v) for v in profile['equips']],
            unresolved=None if 'unresolved_equips' not in profile else [equip(v) for v in profile['unresolved_equips']],deferred=profile.get('deferred_equip_updates'))
        assert player is result['battle_units']['1:1']
    CASES.append(dict(case_id=len(CASES),kind=kind,catalog=cat,**before,expected=expected))
# Every source precedence combination, duplicate keys, explicit removal, and novice collision order.
for i in range(200):
    p=dict(skills={})
    for sid in R.sample([1001,1002,15003,15004,19999],R.randrange(6)):
        p['skills'][str(sid)]=dict(level=R.choice([-1,0,1,9,4294967295]),exp=R.randrange(100),source=R.choice(['S5-3','S15技能槽＋NpcData','S8-1','manual']))
    if i%3:p['server_skill_records']=[dict(key=R.randrange(1,7),level=R.randrange(0,10),exp=R.randrange(100)) for _ in range(R.randrange(7))]
    p['removed_skill_ids']=list(map(str,R.sample([1001,1002,15003,15004],R.randrange(5))))
    a=actor(); a.update(sex=R.choice([None,1,2]),head=R.choice([None,2,3]),equips=[dict(item_id=R.choice([0,100,101,102,103,104,999])) for _ in range(R.randrange(10))])
    add('learned',state=state(p),actor=a)
for i in range(120):
    p=companion(); p['skills']={str(sid):dict(level=level,exp=3,source=src) for sid,level,src in R.sample([(1001,8,'S8-2'),(1002,9,'S15技能槽＋NpcData'),(15003,7,'S8-0'),(15004,4,'S8-4')],R.randrange(5))}
    p['removed_skill_ids']=list(map(str,R.sample([1001,1002,15003],R.randrange(4))))
    a=actor(); a.update(pid=R.choice([7,80,81]),master_id=R.choice([7,8,None]),npc_index=R.choice([1,2,65535]),equips=[dict(item_id=R.choice([100,101,104]))])
    cat=copy.deepcopy(BASE)
    if i%3==0:cat['npcs']={}
    if i%5==0:cat['npcs']['80']=dict(skills=[15003,15004,1001])
    add('learned',state=state({}, {'1':p}, role=None if i%17==0 else 7),actor=a,catalog=cat)
for ids in [[15003,15004],[15004,15003]]:
    for equipment in [[],[dict(item_id=104)]]:
        p=dict(skills={str(s):dict(level=i+1,exp=i,source='S8-1') for i,s in enumerate(ids)})
        a=actor();a['equips']=equipment
        add('learned',state=state(p),actor=a)
for item in [0,*range(12),999,10062,11098,12069,13064,15051,14063,17066,18062,19055,20039,21120,22125,23105,24090,25044]:
    for length in [0,2,3,9]:
        a=actor();a['equips']=[dict(item_id=item) for _ in range(length)]
        add('weapon',actor=a)
for i in range(400):
    a=actor();a.update(col=R.choice([0,1,2,3,4,255]),row=R.randrange(4))
    t=actor();t.update(col=R.choice([0,1,2,3,4,255]),row=R.randrange(4),exited=i%19==0,is_fly=i%23==0)
    if i%7:t['hp']=R.choice([-4294967295,-1,0,1,4294967295])
    add('target',actor=a,target=t,skill=dict(ID=R.choice([1001,11053,15138,15253]),HitStatus=R.choice([0,254,255]),TargetKind=R.randrange(8)))
for i in range(100):
    cat=copy.deepcopy(BASE)
    cat['items']['55']=dict(kind=R.choice([0,23,32,33]),attributes=[dict(kind=R.choice([24,25,26,27]),value=R.choice([-1,0,99,100,101,110,65535,2**63-1])) for _ in range(R.randrange(10))])
    add('heal',catalog=cat,item_id=55 if i%13 else 999)
for i in range(100):
    p=dict(stats={} if i%5==0 else dict(hp=R.choice([-1,0,1,4294967295]),sp=0,max_hp=999,atk=5),skills={})
    if i%3:p['equips']=[dict(item_id=0) for _ in range(9)]
    if i%4:
        p['unresolved_equips']=[dict(item_id=100,design_id=12,damage=3),dict(item_id=101,design_id=14,damage=5)]
        p['deferred_equip_updates']=[dict(type='equip_damage',index=3,damage=99),dict(type='equip_broken',item_id=101),dict(type='battle_equip',equip_index=3,item_id=102,design_id=22)]
    companions={str(s):companion(s,80 if i%7 else 81,simple=i%2==0) for s in [2,1]}
    companions['2']['stats'].update({} if i%2 else dict(hp=0,max_sp=999))
    cat=copy.deepcopy(BASE)
    if i%6==0:cat['items'].pop('101')
    if i%7==0:cat['npcs']={}
    add('field',catalog=cat,state=state(p,companions,role=None if i%9==0 else 7,active=80 if i%8 else None))
for role in [None,0,7]:
    for pid in [None,0,7]:
        a=actor();a['pid']=pid
        add('learned',state=state(dict(skills={'1001':dict(level=1,exp=0,source='S8-1')}),role=role),actor=a)
# A catalog row zero is not a grant, and can erase the previous equipment candidate.
cat=copy.deepcopy(BASE);cat['skills']['0']=dict(ID=0,LvLimit=99)
a=actor();a['equips']=[dict(item_id=100),dict(item_id=0)]
add('learned',state=state(),actor=a,catalog=cat)
for case in range(20):
    events=[]
    def s8(sid,level):return dict(type='attribute_set',entity='follow:1',index=1,human_kind=4,kind=110,parameter=sid,value=level,sub=2)
    def s15(npc=80):
        p=companion(npc=npc);data={**p['stats'],'skill_slots':p['server_skill_slots'],'equips':[]}
        return dict(type='companion_snapshot',companions=[data])
    events += [s8(15004,4),s8(1001,8),s15()]
    for _ in range(12):events.append(s8(R.choice([1001,1002,15003,15004]),R.choice([-1,0,1,2,9])))
    events += [s15(),s15(81),s8(15003,7),s15(),s8(1001,0),s8(1001,9)]
    add('history',events=events)
paths=['wlre/services/items/combat_resources.py','wlre/services/items/live_combat_catalog.py','wlre/services/battle/combat.py','wlre/core/state_session_events.py']
hashes={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in paths}
out=Path(__file__).parent
parts=[]
for index,start in enumerate(range(0,len(CASES),150),1):
    name=f'Part{index:02}';parts.append(name)
    payload=json.dumps(CASES[start:start+150],ensure_ascii=False,separators=(',',':'))
    text='// Generated by generate_combat_resource_vectors.py; real Python helper output.\nnamespace Lala.Core.Tests.Inventory;\npublic static partial class CombatResourcePythonVectors\n{\n    private static string '+name+'() => '+csharp_gzip_json(payload)+';\n}\n'
    assert len(text.encode())<=500_000
    (out/f'CombatResourcePythonVectors.{name}.cs').write_text(text,encoding='utf8')
main='// Generated by generate_combat_resource_vectors.py.\nnamespace Lala.Core.Tests.Inventory;\npublic static partial class CombatResourcePythonVectors\n{\n    public const string SourceSha256 = '+json.dumps(json.dumps(hashes,separators=(',',':')))+';\n    public static IEnumerable<object[]> Cases()\n    {\n'
for name in parts:main+=f'        foreach (var row in System.Text.Json.Nodes.JsonNode.Parse({name}())!.AsArray()) yield return [row!["kind"]!.GetValue<string>(), row.ToJsonString()];\n'
main+='    }\n}\n';(out/'CombatResourcePythonVectors.cs').write_text(main,encoding='utf8')
print('Generated',len(CASES),'vectors in',len(parts),'parts')
