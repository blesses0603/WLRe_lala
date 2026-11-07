"""Real skill_reasons/skill_rows oracle with explicit catalog and read-only item-name context."""
import copy, hashlib, json, os, random, sys
from pathlib import Path
from unittest.mock import patch
os.environ['WLRE_DISABLE_AUTO_CATALOG']='1'
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(Path(__file__).resolve().parents[1]/'TestSupport')]
from gzip_json_fixture import csharp_gzip_json
from wlre.services.items import combat_resources as source, inventory
from wlre.services.items.live_combat_catalog import _pinned
R=random.Random(202611080231);CASES=[]
def skill(sid=1001,**kw):
    return dict(ID=sid,Kind=1,KindSort=1,TargetKind=0,ReduceSP=0,ReduceHP=0,FightWay=1,RangeKind1=1,CostItemID=0,CostItemCount=0,LvLimit=9,
        WeaponKind1=1,WeaponKind2=1,WeaponKind3=1,WeaponKind4=1,WeaponKind5=1,**kw)
def base():
    return dict(keys={},items={str(i):dict(kind=i,fit_type=i%12,skill_link=0) for i in range(12)},npcs={},skills={'1001':skill()},
        characters=[dict(sex=1,head=2,skill=15004,body=20),dict(sex=1,head=2,skill=15005,body=21)],element_weights={})
def actor():return dict(pid=7,master_id=0,npc_index=0,col=1,row=1,sex=1,head=2,hp=100,sp=10,equips=[dict(item_id=0),dict(item_id=20),dict(item_id=0)],statuses={})
def state(ids=(1001,),role=7):return dict(player={} if role is None else dict(role_id=role),knowledge=dict(player=dict(skills={str(sid):dict(level=i+1,exp=i,source='S8-1') for i,sid in enumerate(ids)}),companions={}))
def item(index,id=42,count=3):return dict(index=index,item_id=id,count=count,damage=0,serial_version=0,serial=index,magic_spar=0,available_time=0.,limited_time=0.,beat_level=0,differ=0,modeling=0,saddle_beat_level=0,enhance_level=0,design_id=0,plugins=[],locked=False,star_soul_kind=0,star_soul_level=0)
def bag():return dict(ready=True,reliable=True,revision=0,use_failed=False,items={'9':item(9,42,2),'2':item(2,42,3),'1':item(1,43,4)},reserved={},holds={},alchemy_slots=[],expedition_slots=[],maintenance_slots=[])
def add(kind,cat=None,a=None,s=None,inv=None,sid=1001,names=None):
    cat=copy.deepcopy(cat or base());a=copy.deepcopy(a or actor());s=copy.deepcopy(s or state());inv=copy.deepcopy(inv or bag());names=names or {'42':'測試材料','43':''}
    s['inventory']=inv;_pinned.set(cat)
    with patch.object(inventory,'item_name',side_effect=lambda id:names.get(str(id),f'物品{id}')):
        expected=source.skill_reasons(s,a,sid) if kind=='reasons' else source.skill_rows(s,a)
    CASES.append(dict(case_id=len(CASES),kind=kind,catalog=cat,actor=a,state=s,skill_id=sid,names=names,expected=expected))
for i in range(500):
    sid=R.choice([1001,11172,15003,15004,15005]);cat=base();row=skill(sid)
    row.update(Kind=R.choice([0,1,8,9]),KindSort=R.choice([1,2,3,4,5]),TargetKind=R.randrange(6),ReduceSP=R.choice([0,0,0,1,10,11,65535]),ReduceHP=R.choice([0,1,50,99,100,101]),FightWay=R.randrange(27),RangeKind1=R.choice([0,1,2]),CostItemID=R.choice([0,42,43,65535]),CostItemCount=R.choice([0,1,3,5,6]))
    row.update({f'WeaponKind{n}':R.choice([0,1,2]) for n in range(1,6)})
    cat['skills']={str(sid):row};a=actor();a.update(pid=R.choice([7,7,7,8,None]),sex=R.choice([None,1,2]),head=R.choice([None,2,3]),exited=i%17==0,statuses=dict(silenced=bool(i%2),taunt=bool(i%3)))
    a['equips']=[dict(item_id=R.choice([0,20,21,20044,20045,20048,20050,999])) for _ in range(R.randrange(5))]
    if i%7==0:a.pop('hp')
    else:a['hp']=R.choice([-1,0,1,2,100,4294967295])
    if i%11==0:a.pop('sp')
    else:a['sp']=R.choice([-1,0,1,10,4294967295])
    s=state([sid] if i%9 else [],role=None if i%23==0 else 7)
    inv=bag();inv.update(ready=i%19!=0,reliable=i%13!=0)
    inv[R.choice(['alchemy_slots','expedition_slots','maintenance_slots'])]=[str(R.choice([1,2,9]))]
    inv['reserved']={str(R.choice([2,9])):R.choice([0,1,2,3,999])}
    if i%31==0:cat['skills']={}
    add('reasons',cat,a,s,inv,sid)
# Every status branch, active-skill gate and HP binary64 boundary.
for fight in range(32):
    cat=base();cat['skills']['1001'].update(FightWay=fight,TargetKind=1,RangeKind1=0)
    a=actor();a['statuses']=dict(silenced=True,taunt=True)
    add('reasons',cat,a)
for hp in [-(2**63),-(2**53)-1,-4294967295,-1,0,1,2,99,100,101,4294967295,2**53-1,2**53,2**53+1,2**53+3,9007199254740894,9007199254740903,2**63-1]:
    for pct in [-2**63,-1,1,50,99,100,101,255,2**63-1]:
        cat=base();cat['skills']['1001']['ReduceHP']=pct;a=actor();a['hp']=hp
        add('reasons',cat,a)
for sid in [15003,15004,11172]:
    for weapon in [0,20044,20045,20048,20050,999]:
        cat=base();cat['skills']={str(sid):skill(sid)};a=actor();a.update(sex=0,head=0);a['equips'][2]['item_id']=weapon
        add('reasons',cat,a,state([sid]),sid=sid)
for role in [None,0,7]:
    for pid in [None,0,7,80]:
        cat=base();cat['skills']['1001'].update(CostItemID=42,CostItemCount=6);a=actor();a['pid']=pid
        add('reasons',cat,a,state(role=role))
for mode in ['not_ready','not_reliable','enough','reserved','alchemy','expedition','maintenance','exclusive','uncertain','missing']:
    cat=base();cat['skills']['1001'].update(CostItemID=42,CostItemCount=5);inv=bag()
    if mode=='not_ready':inv['ready']=False
    if mode=='not_reliable':inv['reliable']=False
    if mode=='reserved':inv['reserved']={'2':1}
    if mode in ['alchemy','expedition','maintenance']:inv[mode+'_slots']=['2']
    if mode in ['exclusive','uncertain']:inv['holds']={'crafting':[dict(index='2',identity=[42,2,0],count=1,remaining=1,before=3,exclusive=mode=='exclusive',uncertain=mode=='uncertain')]}
    if mode=='missing':inv['items']={}
    add('reasons',cat,inv=inv)
for i in range(160):
    cat=base();ids=R.sample([1001,1002,1003,1004,11172,15003,15004,99999],R.randrange(9));s=state(ids);a=actor()
    a['statuses']=dict(silenced=bool(i%2),taunt=bool(i%3));a['hp']=R.choice([0,1,100]);a['sp']=R.choice([0,5,10])
    for sid in ids:
        if sid==99999:continue
        row=skill(sid);row.update(KindSort=R.randrange(1,6),ReduceSP=R.choice([0,1,10,65535,99999,100000]),CostItemID=42,CostItemCount=1)
        if i%2:row['name']=R.choice(['技能名稱','',f'名稱{sid}'])
        if row['KindSort']==4 and i%3==0:row.pop('ReduceSP')
        cat['skills'][str(sid)]=row
    add('rows',cat,a,s)
for i in range(30):
    cat=base();cat['npcs']['80']=dict(skills=[1001]);cat['skills']['1001'].update(CostItemID=42,CostItemCount=99)
    a=actor();a.update(pid=80,master_id=7 if i%5 else 8,npc_index=1)
    s=state([]);s['knowledge']['companions']['1']=dict(npc_id=80,index=1,skills={},equips=[],server_skill_slots=[dict(level=1,exp=2)],
        stats=dict(index=1,npc_id=80,exp=5,level=4,str=1,con=2,int=3,wis=4,agi=5,faith=6,can_grow=1,sport_exp=7,degree=0,potential=8,modeling=9,use_up_stats=10))
    if i%3==0:s['knowledge']['companions']['1']['removed_skill_ids']=['1001']
    if i%7==0:cat['skills']['1001'].pop('CostItemID');cat['skills']['1001'].pop('CostItemCount')
    add('reasons' if i%2 else 'rows',cat,a,s,dict(bag(),ready=False))
for active in [True,False]:
    cat=base();cat['items']['10']['skill_link']=1001;a=actor();a['equips'][2]['item_id']=10 if active else 0
    add('reasons',cat,a,state([]))
    add('rows',cat,a,state([]))
paths=['wlre/services/items/combat_resources.py','wlre/services/items/inventory.py','wlre/services/items/reservations.py','wlre/services/items/catalog.py','wlre/services/items/live_combat_catalog.py','wlre/services/battle/combat.py']
hashes={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in paths}
out=Path(__file__).parent;parts=[]
for index,start in enumerate(range(0,len(CASES),150),1):
    name=f'Part{index:02}';parts.append(name)
    payload=json.dumps(CASES[start:start+150],ensure_ascii=False,separators=(',',':'))
    text='// Generated by generate_combat_skill_validation_vectors.py.\nnamespace Lala.Core.Tests.Inventory;\npublic static partial class CombatSkillValidationPythonVectors\n{\n    private static string '+name+'() => '+csharp_gzip_json(payload)+';\n}\n'
    assert len(text.encode())<=500_000
    (out/f'CombatSkillValidationPythonVectors.{name}.cs').write_text(text,encoding='utf8')
main='// Generated by generate_combat_skill_validation_vectors.py.\nnamespace Lala.Core.Tests.Inventory;\npublic static partial class CombatSkillValidationPythonVectors\n{\n    public const string SourceSha256 = '+json.dumps(json.dumps(hashes,separators=(',',':')))+';\n    public static IEnumerable<object[]> Cases()\n    {\n'
for name in parts:main+=f'        foreach (var row in System.Text.Json.Nodes.JsonNode.Parse({name}())!.AsArray()) yield return [row!["kind"]!.GetValue<string>(), row.ToJsonString()];\n'
main+='    }\n}\n';(out/'CombatSkillValidationPythonVectors.cs').write_text(main,encoding='utf8')
print('Generated',len(CASES),'vectors in',len(parts),'parts')
