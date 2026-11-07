"""Run retained Python functions, with explicit synthetic catalogs only, for pure candidates.

No game/runtime catalog, session, command transport, or reservation acquisition is used.
Re-run from any directory; needs the same Python imports as the retained source.
"""
import copy, gzip, hashlib, io, json, os, random, sys
from pathlib import Path
from unittest.mock import patch
os.environ['WLRE_DISABLE_AUTO_CATALOG']='1'
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from wlre.services.items import combat_resources as source, inventory
from wlre.services.items.live_combat_catalog import _pinned
from wlre.services.battle import combat
R=random.Random(202611080557); CASES=[]
def skill(sid=1001,**kw):
    row=dict(ID=sid,Kind=1,KindSort=1,TargetKind=0,ReduceSP=0,ReduceHP=0,FightWay=1,RangeKind1=1,CostItemID=0,CostItemCount=0,LvLimit=5,
        HitStatus=0,TargetNPCID=0,Element=2,AtkKind=1,Sort=0,NextSkillId=0,WeaponKind1=1,WeaponKind2=1,WeaponKind3=1,WeaponKind4=1,WeaponKind5=1)
    row.update(kw);return row
def cat():
    return dict(keys={},items={str(i):dict(kind=i,fit_type=0,skill_link=0,restrict=0,attributes=[]) for i in range(12)},npcs={},
        skills={'1001':skill()},characters=[],element_weights={'1':{'2':1.5,'3':.5,'4':1},'2':{'1':.5,'3':1.5,'4':1}})
def actor(pid=7,col=1,row=1,**kw):
    a=dict(pid=pid,master_id=0,npc_index=0,col=col,row=row,hp=100,sp=10,max_hp=200,max_sp=20,element=1,
        equips=[dict(item_id=0)]*3,statuses={},sex=1,head=2)
    a.update(kw);return a
def item(index,id=42,count=3,**kw):
    row=dict(index=index,item_id=id,count=count,damage=0,serial_version=0,serial=index,magic_spar=0,available_time=0.,limited_time=0.,beat_level=0,differ=0,modeling=0,saddle_beat_level=0,enhance_level=0,design_id=0,plugins=[],locked=False,star_soul_kind=0,star_soul_level=0)
    row.update(kw);return row
def bag():return dict(ready=True,reliable=True,revision=0,use_failed=False,items={'9':item(9,42,2),'2':item(2,42,3),'1':item(1,43,4)},reserved={},holds={},alchemy_slots=[],expedition_slots=[],maintenance_slots=[])
def state(ids=(1001,)):
    return dict(player=dict(role_id=7),knowledge=dict(player=dict(skills={str(sid):dict(level=5,exp=0,source='S8-1') for sid in ids},stats={}),companions={}),
        inventory=bag(),battle=dict(war_style=0),battle_units={'4:2':actor(81,4,2,hp=40,element=2),'3:1':actor(82,3,1,hp=60,element=3),'1:1':actor()})
def normal():return dict(items={str(i):i for i in range(12)},npcs={'80':dict(kind=0,bodyType=1,normalAttackKind=1)},catch_nets={})
def add(kind='learned',c=None,a=None,s=None,n=None,**args):
    c=copy.deepcopy(c if c is not None else cat());a=copy.deepcopy(a if a is not None else actor());s=copy.deepcopy(s if s is not None else state());n=copy.deepcopy(n if n is not None else normal())
    names={'42':'測試材料','43':''};before=copy.deepcopy((c,a,s,n)); token=_pinned.set(c)
    try:
        with patch.object(inventory,'item_name',side_effect=lambda id:names.get(str(id),f'物品{id}')),patch.object(combat.DATA,'snapshot',return_value=n):
            try:
                if kind=='learned': result=source.learned_command(s,a,**dict(dict(sid=1001),**args))
                elif kind=='best':result=source.best_skill_command(s,a,**args)
                elif kind=='food':result=source.food_command(s,a,**args)
                else:raise ValueError(kind)
                expected=dict(action=result,error=None)
            except Exception as exc:expected=dict(action=None,error=dict(type=type(exc).__name__,message=str(exc)))
    finally:_pinned.reset(token)
    assert before==(c,a,s,n),'Oracle mutated observations'
    CASES.append(dict(case_id=len(CASES),kind=kind,catalog=c,actor=a,state=s,normal=n,args=args,names=names,expected=expected,
        typed_resource_rejection=kind=='food' and args.get('resource','hp') not in ('hp','sp')))
# Learned chain bounded at two, missing evidence/rows, cycles, replacements, removals.
for mode in ['full','level','missing_next','missing_data','cycle','self','deleted','server_stale','equipment','foreign','stale_companion']:
    c=cat();c['skills']={str(id):skill(id,NextSkillId=id+1) for id in range(1001,1006)};s=state(range(1001,1006));a=actor()
    if mode=='level':s['knowledge']['player']['skills']['1001']['level']=4
    if mode=='missing_next':s['knowledge']['player']['skills'].pop('1002')
    if mode=='missing_data':c['skills'].pop('1002')
    if mode=='cycle':c['skills']['1002']['NextSkillId']=1001
    if mode=='self':c['skills']['1001']['NextSkillId']=1001
    if mode=='deleted':s['knowledge']['player']['removed_skill_ids']=['1002']
    if mode=='server_stale':
        s['knowledge']['player']['skills']['1002']['source']='S5-3';s['knowledge']['player']['server_skill_records']=[]
    if mode=='equipment':
        s=state([]);c['items']['10']['skill_link']=1001;a['equips']=[dict(item_id=0),dict(item_id=0),dict(item_id=10)]
    if mode=='foreign':a['pid']=999
    if mode=='stale_companion':a.update(pid=80,master_id=7,npc_index=1)
    for next_skill in [False,True]:add(c=c,a=a,s=s,next_skill=next_skill)
# Target gate/ordering/tie keys versus coordinate fallback, unknown stats and long bounds.
for targetkind in range(7):
    for mode in [0,1,2,3,4]:
        for sid in [1001,10001,11053,15138,15253]:
            c=cat();c['skills']={str(sid):skill(sid,TargetKind=targetkind,HitStatus=254 if mode==4 else 0)};s=state([sid])
            s['battle_units']={'alias':actor(81,3,2,hp=0 if mode==1 else 80,element=2),
                '3:1':actor(82,3,1,hp=80,element=3,is_fly=mode==2),
                '1:2':actor(83,1,2,hp=0 if mode==1 else 90,exited=mode==3),
                '1:1':actor()}
            if mode==0:s['battle_units']['alias'].pop('hp')
            add(c=c,s=s,sid=sid,target_kind=mode)
for slot in [None,'','alias','3:2','missing']:
    for kind in [0,1,2,3,4]:
        s=state();s['battle_units']={'alias':actor(81,3,2,hp=80),'3:1':actor(82,3,1,hp=80)}
        add(s=s,target_kind=kind,target_slot=slot)
        add('best',s=state([])|{'battle_units':s['battle_units']},target_kind=kind,target_slot=slot)
for hp in [-(2**63),-(2**53)-1,-1,0,1,2**53-1,2**53,2**53+1,2**53+3,9007199254740894,9007199254740903,2**63-1]:
    for pct in [0,50,99,100,101,2**63-1]:
        c=cat();c['skills']['1001']['ReduceHP']=pct;a=actor(hp=hp)
        add(c=c,a=a,target_kind=3)
# Individual catalog-field faults retain real KeyError and short circuit precedence.
for field in skill():
    c=cat();c['skills']['1001'].pop(field)
    for kind in ['learned','best']:add(kind,c=c,target_kind=2)
for key in ['Kind','KindSort','TargetKind','CostItemCount','TargetNPCID','Element']:
    c=cat();c['skills']['1001'].pop(key);c['skills']['1001']['Kind']=9
    add(c=c)
for i in range(400):
    c=cat();sid=R.choice([1001,10001,10002,10003,10004,11172,15003,15004]);row=skill(sid,Kind=R.choice([1,1,8,9]),KindSort=R.choice([1,2,3,4]),
        TargetKind=R.randrange(6),ReduceSP=R.choice([0,0,1,10,11]),ReduceHP=R.choice([0,0,50,99,100]),CostItemID=R.choice([0,0,42,43,999]),CostItemCount=R.choice([-1,0,1,5,6]),
        FightWay=R.randrange(27),TargetNPCID=R.choice([0,0,81,999]),HitStatus=R.choice([0,0,254]))
    c['skills']={str(sid):row};a=actor(hp=R.choice([0,1,2,100]),sp=R.choice([0,5,10]),exited=i%17==0,statuses=dict(silenced=i%3==0,taunt=i%7==0));s=state([sid] if i%9 else [])
    if i%11==0:a.pop('sp')
    if i%13==0:a.pop('hp')
    if i%19==0:a['equips']=[]
    if i%23==0:a['pid']=999
    inv=s['inventory'];inv.update(ready=i%29!=0,reliable=i%31!=0,use_failed=i%5==0)
    inv['reserved']={str(R.choice([2,9])):R.choice([0,1,3,2**65])}
    if i%3==0:inv['alchemy_slots']=['2']
    add(c=c,a=a,s=s,sid=sid,target_kind=R.randrange(5),target_slot=R.choice([None,'','3:1','unknown']))
# Best attack family preference, numeric sort, ProtocolError-only skip and normal fallback.
for attack,magic in [(None,None),(None,4),(4,None),(3,4),(4,3),(4,4),(-(2**63),2**63-1)]:
    for kind in [1,2,3,4]:
        for way in [1,2,3]:
            c=cat();c['skills']={str(id):skill(id,AtkKind=kind,FightWay=way,Sort=1003-id,ReduceSP=id-1001) for id in [1003,1001,1002]};s=state([1003,1001,1002])
            if attack is not None:s['knowledge']['player']['stats']['atk']=attack
            if magic is not None:s['knowledge']['player']['stats']['matk']=magic
            add('best',c=c,s=s,target_kind=2)
for i in range(150):
    c=cat();ids=R.sample(range(1001,1007),R.randrange(7));s=state(ids);a=actor()
    c['skills']={str(id):skill(id,AtkKind=R.randrange(5),FightWay=R.randrange(5),KindSort=R.randrange(5),ReduceSP=R.choice([0,1,10,11]),Sort=R.choice([0,0,1,2]),TargetKind=R.randrange(6)) for id in ids}
    s['battle_units']={} if i%17==0 else s['battle_units'];a['equips']=[dict(item_id=0),dict(item_id=0),dict(item_id=R.choice([0,4,5,11,999]))]
    if i%7==0:a.update(pid=80,master_id=7)
    if i%19==0:a.update(pid=99,master_id=98)
    add('best',c=c,s=s,a=a,target_kind=R.randrange(5),target_slot=R.choice([None,'3:1','missing']))
# Companion cost bypass, actual slot ownership and remapped raw learning evidence.
for npc in [80,81]:
    for master in [7,8]:
        for removed in [False,True]:
            c=cat();c['skills']['1001'].update(CostItemID=42,CostItemCount=999);c['npcs']['80']=dict(skills=[1001]);s=state([])
            s['knowledge']['companions']['1']=dict(npc_id=80,index=1,skills={},equips=[],server_skill_slots=[dict(level=5,exp=2)],
                stats=dict(index=1,npc_id=80,exp=5,level=4,str=1,con=2,int=3,wis=4,agi=5,faith=6,can_grow=1,sport_exp=7,degree=0,potential=8,modeling=9,use_up_stats=10))
            if removed:s['knowledge']['companions']['1']['removed_skill_ids']=['1001']
            s['inventory']['ready']=False
            for kind in ['learned','best']:add(kind,c=c,s=s,a=actor(npc,2,1,master_id=master,npc_index=1))
# Food selection, restrictions, all gate precedence, item/resource/slot filters.
def foodcat():
    c=cat()
    for id,amount in [(42,40),(43,100),(44,10),(45,80),(46,50)]:
        c['items'][str(id)]=dict(kind=23 if id%2 else 32,restrict=0,attributes=[dict(kind=25,value=amount+100),dict(kind=26,value=amount+100)])
    return c
for war in range(26):
    for field in [False,True]:add('food',c=foodcat(),s=state()|{'battle':{'war_style':war}},field=field)
for mode in ['not_ready','unreliable','both','failed','empty_error','exact','overshoot','under','locked','available','limited','alchemy','reserved','exclusive','uncertain','restricted','bad_hp','bad_sp','zero_attribute','hundred_attribute','duplicate_effect','fly','exited','dead','unknown_hp','unknown_sp','missing_max','zero_max','negative','only_hp']:
    c=foodcat();s=state();inv=s['inventory']
    if mode in ['not_ready','both']:inv['ready']=False
    if mode in ['unreliable','both','empty_error']:inv['reliable']=False
    if mode=='empty_error':inv['sync_error']=''
    if mode=='failed':inv['use_failed']=True
    if mode=='exact':s['battle_units']['1:1']['max_hp']=140
    if mode=='overshoot':s['battle_units']['1:1']['max_hp']=130
    if mode=='under':s['battle_units']['1:1']['max_hp']=1000
    for itemrow in inv['items'].values():
        if mode=='locked':itemrow['locked']=True
        if mode=='available':itemrow['available_time']=1
        if mode=='limited':itemrow['limited_time']=-1
    if mode=='alchemy':inv['alchemy_slots']=['1','2','9']
    if mode=='reserved':inv['reserved']={'1':4,'2':3,'9':2}
    if mode in ['exclusive','uncertain']:
        inv['holds']={'crafting':[dict(index=str(i),identity=[42,i,0],count=1,remaining=1,before=3,exclusive=mode=='exclusive',uncertain=mode=='uncertain') for i in [1,2,9]]}
    for row in c['items'].values():
        if mode=='restricted':row['restrict']=256
        if mode in ['bad_hp','bad_sp','zero_attribute','hundred_attribute']:row['attributes'].append(dict(kind=26 if mode=='bad_sp' else 25,value={'bad_hp':99,'bad_sp':-1,'zero_attribute':0,'hundred_attribute':100}[mode]))
        if mode=='duplicate_effect':row['attributes'].append(dict(kind=25,value=101))
        if mode=='only_hp':row['attributes']=[a for a in row['attributes'] if a['kind']==25]
    target=s['battle_units']['1:1']
    if mode=='fly':target['is_fly']=True
    if mode=='exited':target['exited']=True
    if mode=='dead':target['hp']=0
    if mode=='unknown_hp':target.pop('hp')
    if mode=='unknown_sp':target.pop('sp')
    if mode=='missing_max':target.pop('max_hp')
    if mode=='zero_max':target['max_hp']=0
    if mode=='negative':target.update(sp=-(2**63),max_sp=2**63-1)
    for field in [False,True]:
        for resource in ['hp','sp','unknown']:add('food',c=c,s=s,resource=resource,field=field)
for resource in ['hp','sp']:
    for index in [None,0,1,2,9,255,-1,65536]:
        for item_id in [None,0,42,43,999]:add('food',c=foodcat(),resource=resource,index=index,item_id=item_id)
# Exact binary64 ratio ties and Int64 subtraction/absolute value boundaries.
for hp,maxhp in [(1,3),(2**53-1,2**53),(2**53,2**53+1),(2**53+1,2**53+2),(2**63-2,2**63-1),(1,2**63-1)]:
    for delta in [-1,0,1]:
        s=state();s['battle_units']={'1:2':actor(7,1,2,hp=hp,max_hp=maxhp),'1:1':actor(8,1,1,hp=max(1,hp+delta),max_hp=maxhp)}
        add('food',c=foodcat(),s=s)
for i in range(300):
    c=foodcat();s=state();s['battle_units']={}
    for j in range(R.randrange(6)):
        col=R.randrange(1,5);row=j+1;t=actor(80+j,col,row,hp=R.choice([0,1,50,100]),sp=R.choice([-1,0,1,9,10,20]),max_hp=R.choice([50,100,101,1000]),max_sp=R.choice([10,20,100]),exited=i%19==0,is_fly=i%7==0)
        s['battle_units'][f'{col}:{row}']=t
    inv=s['inventory'];inv['items']={str(index):item(index,R.choice([42,43,44,45,46,999]),R.choice([0,1,2]),locked=i%31==0) for index in R.sample(range(1,20),R.randrange(8))}
    if i%5==0:inv['alchemy_slots']=['1','2','3']
    if i%7==0:inv['reserved']={'1':2**65,'2':1,'3':-1}
    for id in [42,43,44,45,46]:c['items'][str(id)]['attributes']=[dict(kind=25,value=R.choice([0,99,100,101,140,200,2**63-1])),dict(kind=26,value=R.choice([0,99,100,101,150]))]
    add('food',c=c,s=s,resource=R.choice(['hp','sp']),target_slot=R.choice([None,'','1:1','1:2','unknown']),field=i%2==0)
# Distinguishes correctly rounded integer division from separately rounded operands.
s=state();s['battle_units']={'1:1':actor(7,1,1,hp=743123302442833097,max_hp=5301563546026923518),
    '1:2':actor(8,1,2,hp=743123302442833047,max_hp=5301563546026923518)}
add('food',c=foodcat(),s=s)
# Python negates unbounded integers for descending HP. MinValue is not MaxValue.
for target_kind in [1,3]:
    c=cat();c['skills']['1001']['HitStatus']=254;s=state();s['battle_units']={
        '3:1':actor(81,3,1,hp=-(2**63)),'3:2':actor(82,3,2,hp=2**63-1)}
    add(c=c,s=s,target_kind=target_kind)
# All normal fallback branches still use the independent normal catalog observation.
for weapon in [0,1,3,4,5,7,11,999,10062,20037]:
    for identity in ['player','transformed','human','monster','foreign']:
        a=actor();a['equips']=[dict(item_id=0),dict(item_id=0),dict(item_id=weapon)];n=normal();n['items']['20037']=11
        if identity=='transformed':a['change_body_id']=20
        if identity in ['human','monster']:a.update(pid=80,master_id=7);n['npcs']['80']['kind']=1 if identity=='monster' else 0
        if identity=='foreign':a.update(pid=80,master_id=9)
        add('best',s=state([]),a=a,n=n)
for a in [actor(equips=[]),actor(equips=[dict(item_id=0)]*2)]:add('best',s=state([]),a=a)
for cost in [-1,1,5,6]:
    c=cat();c['skills']['1001'].update(CostItemID=42,CostItemCount=cost);s=state();s['inventory']['use_failed']=True
    add(c=c,s=s)
s=state();s['battle_units']['1:1'].update(sp=-1);s['battle_units']['1:1'].pop('max_sp');add('food',c=foodcat(),s=s,resource='sp')
paths=['wlre/services/items/combat_resources.py','wlre/services/items/inventory.py','wlre/services/items/reservations.py','wlre/services/items/catalog.py','wlre/services/items/live_combat_catalog.py','wlre/services/battle/combat.py','wlre/services/battle/battle_commands.py']
hashes={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in paths}
payload=json.dumps(dict(source_sha256=hashes,cases=CASES),ensure_ascii=False,separators=(',',':')).encode()
buffer=io.BytesIO()
with gzip.GzipFile(fileobj=buffer,mode="wb",filename="",mtime=0,compresslevel=9) as stream:stream.write(payload)
compressed=buffer.getvalue();assert len(compressed)<=500_000
assert gzip.decompress(compressed)==payload
out=Path(__file__).parent; (out/'Fixtures').mkdir(exist_ok=True);(out/'Fixtures/combat-action-candidates.json.gz').write_bytes(compressed)
cs='''// Generated by generate_combat_action_candidates.py; deterministic real-Python oracle.
using System.Text.Json.Nodes;
using Lala.Core.Tests.TestSupport;
namespace Lala.Core.Tests.Inventory;
public static class CombatActionCandidatePythonVectors
{
    internal static JsonNode Read() => JsonNode.Parse(GzipJson.DecodeResource(
        "Lala.Core.Tests.Inventory.Fixtures.combat-action-candidates.json.gz",
        "COMPRESSED", "DECODED"))!;
    public static IEnumerable<object[]> Cases()
    {
        foreach (var row in Read()["cases"]!.AsArray()) yield return [row!["case_id"]!.GetValue<int>(),row.ToJsonString()];
    }
}
'''.replace('COMPRESSED',hashlib.sha256(compressed).hexdigest()).replace('DECODED',hashlib.sha256(payload).hexdigest())
(out/'CombatActionCandidatePythonVectors.cs').write_text(cs,encoding='utf8')
print(f'Generated {len(CASES)} vectors; gzip {len(compressed)} bytes; JSON {len(payload)} bytes')
print('Typed unsupported-resource cases:',sum(row['typed_resource_rejection'] for row in CASES))
print('Outcomes:', {kind:sum(row['expected']['error'] is not None and row['expected']['error']['type']==kind for row in CASES) for kind in ['ProtocolError','KeyError','TypeError','ValueError']})
