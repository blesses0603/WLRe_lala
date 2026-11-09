"""Deterministic actual-Python choose_action oracle; synthetic observations only.

Invokes retained auto_battle.validate/choose_action and their real command helpers.
Never starts/ticks AutoBattle, installs reservations, or contacts a game service.
"""
import copy, gzip, hashlib, io, json, os, random, sys
from pathlib import Path
from unittest.mock import patch
os.environ['WLRE_DISABLE_AUTO_CATALOG']='1'
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from wlre.services.battle import auto_battle as source, combat
from wlre.services.items import inventory
from wlre.services.items.live_combat_catalog import _pinned
R=random.Random(202611091108); CASES=[]
def actor(pid=7,col=1,row=1,**kw):
    value=dict(pid=pid,master_id=0,npc_index=0,col=col,row=row,hp=100,sp=10,max_hp=200,max_sp=20,level=30,degree=0,
        equips=[dict(item_id=0)]*6,statuses={},sex=1,head=2,element=1)
    value.update(kw);return value

def skill(sid=1001,**kw):
    value=dict(ID=sid,Kind=1,KindSort=1,TargetKind=0,ReduceSP=0,ReduceHP=0,FightWay=1,RangeKind1=1,CostItemID=0,CostItemCount=0,LvLimit=5,
        HitStatus=0,TargetNPCID=0,Element=2,AtkKind=1,Sort=0,NextSkillId=0,WeaponKind1=1,WeaponKind2=1,WeaponKind3=1,WeaponKind4=1,WeaponKind5=1)
    value.update(kw);return value

def item(index,id=42,count=3):
    return dict(index=index,item_id=id,count=count,damage=0,serial_version=0,serial=index,magic_spar=0,available_time=0.,limited_time=0.,beat_level=0,differ=0,modeling=0,saddle_beat_level=0,enhance_level=0,design_id=0,plugins=[],locked=False,star_soul_kind=0,star_soul_level=0)

def cat():
    return dict(keys={},items={'0':dict(kind=0), '42':dict(kind=23,attributes=[dict(kind=25,value=200),dict(kind=26,value=110)]),
        '43':dict(kind=32,attributes=[dict(kind=25,value=140),dict(kind=26,value=150)])},npcs={},skills={'1001':skill(),'1002':skill(1002)},characters=[],element_weights={'1':{'2':0.5,'3':1.5},'2':{'2':0.5,'3':1.5}})

def state():
    return dict(player=dict(role_id=7),knowledge=dict(player=dict(skills={str(i):dict(level=5,exp=0,source='S8-1') for i in [1001,1002]},stats={}),companions={}),
        inventory=dict(ready=True,reliable=True,revision=0,use_failed=False,items={'9':item(9,42,2),'2':item(2,42,3),'1':item(1,43,4)},reserved={},holds={},alchemy_slots=[],expedition_slots=[],maintenance_slots=[]),
        battle=dict(active=True,round=1,commands={},war_style=0),battle_units={'4:2':actor(101,4,2,hp=40,element=3),'3:1':actor(102,3,1,hp=60,element=2),'2:1':actor(80,2,1,master_id=7), '1:1':actor()})

def normal():
    return dict(items={str(i):i for i in range(12)},npcs={str(i):dict(kind=0,bodyType=1,normalAttackKind=1,canCatch=i>=100) for i in [80,81,101,102]},catch_nets={'99':20})

def profile(**kw):
    result=source.default_profile()
    for key in result:
        if key.startswith('b'):result[key]=False
    result.update(kw);return result

def action(id=0,**kw):return source.action(id,**kw)

def add(label,p=None,s=None,a=None,c=None,n=None,who='player'):
    s=copy.deepcopy(s if s is not None else state());a=copy.deepcopy(a if a is not None else actor())
    c=copy.deepcopy(c if c is not None else cat());n=copy.deepcopy(n if n is not None else normal());p=copy.deepcopy(p if p is not None else {})
    names={'42':'測試材料','43':''};before=copy.deepcopy((s,a,c,n,p));token=_pinned.set(c)
    try:
        with patch.object(inventory,'item_name',side_effect=lambda id:names.get(str(id),f'物品{id}')),patch.object(combat.DATA,'snapshot',return_value=n):
            validated=source.validate({'profiles':{who:p}})['profiles'][who]
            try:
                command,reason=source.choose_action(s,a,validated)
                expected=dict(action=command,reason=reason,error=None)
            except Exception as exc:expected=dict(action=None,reason=None,error=dict(type=type(exc).__name__,message=str(exc)))
    finally:_pinned.reset(token)
    assert before==(s,a,c,n,p),'Retained Python mutated input'
    CASES.append(dict(case_id=len(CASES),label=label,state=s,actor=a,catalog=c,normal=n,names=names,profile=validated,expected=expected))

add('default player');add('default partner',who='partner',a=actor(80,2,1,master_id=7))
# Each rule by itself, and a ladder of all eligible rules proves priority.
keys=[('bDeadAction','deadAction'),('bEnemyHPAction','enemyHpAction'),('bLowHpAction','lowHpAction'),('bLowSpAction','lowSpAction'),('bRoundAction','roundAction'),('bRepeatAction','repeatAction'),('bOrderAction','orderAction')]
s=state();s['battle_units']['2:2']=actor(81,2,2,master_id=7,hp=0);s['battle_units']['1:1']['hp']=50
p=profile();p.update(bDeadAction=True,bEnemyHPAction=True,bLowHpAction=True,bLowSpAction=True,bRoundAction=True,bRepeatAction=True,bOrderAction=True,
    deadAction=action(60021),enemyHpAction=action(60041,compareKind=1,value=0),lowHpAction=action(60021,notice=2,value=100),lowSpAction=action(60041,notice=2,value=100),
    roundAction=[action(60021)],repeatAction=[action(60041)],orderAction=[action(10001)])
for flag,key in keys:
    add('priority '+key,p=p,s=s);p[flag]=False
add('priority fallback',p=p,s=s)
# Dead trigger/target fly asymmetry, sparse evidence, exited and revive metadata.
for way in [1,8,24]:
    for mode in ['plain','first_fly','only_fly','missing_hp','exited','alias','upgrade']:
        s=state();s['battle_units']['1:2']=actor(81,1,2,hp=0,is_fly=mode in ['first_fly','only_fly'])
        if mode!='only_fly':s['battle_units']['2:2']=actor(80,2,2,hp=0,master_id=7)
        if mode=='missing_hp':s['battle_units']['1:2'].pop('hp');s['battle_units']['2:2'].pop('hp')
        if mode=='exited':s['battle_units']['1:2']['exited']=True;s['battle_units']['2:2']['exited']=True
        if mode=='alias':s['battle_units']['dead_alias']=s['battle_units'].pop('1:2')
        c=cat();c['skills']['1001'].update(FightWay=way,TargetKind=1,HitStatus=254)
        if mode=='upgrade':c['skills']['1001']['NextSkillId']=1002;c['skills']['1002'].update(FightWay=8,TargetKind=1,HitStatus=254)
        add('dead '+str(way)+' '+mode,s=s,c=c,p=profile(bDeadAction=True,deadAction=action(1001,bUseNextSkill=mode=='upgrade')))
# Configured metadata is inspected before next-skill traversal. With a flying first
# corpse, adding an explicit revive target must fail even though a later one is valid.
for configured_way in [1,8,24]:
    s=state();s['battle_units']['1:2']=actor(81,1,2,hp=0,is_fly=True);s['battle_units']['2:2']=actor(80,2,2,hp=0,master_id=7)
    c=cat();c['skills']['1001'].update(FightWay=configured_way,TargetKind=1,HitStatus=254,NextSkillId=1002)
    c['skills']['1002'].update(FightWay=8,TargetKind=1,HitStatus=254)
    add('dead upgrade configured '+str(configured_way),s=s,c=c,p=profile(bDeadAction=True,deadAction=action(1001,bUseNextSkill=True)))
# Low-resource support metadata has the same pre-upgrade boundary. An original
# friendly target kind pins the ally and the upgraded enemy skill cannot use it.
for configured_kind in [0,1,3,5]:
    s=state();s['battle_units']['1:1']['hp']=20;c=cat()
    c['skills']['1001'].update(TargetKind=configured_kind,NextSkillId=1002)
    c['skills']['1002'].update(TargetKind=0)
    add('support upgrade configured '+str(configured_kind),s=s,c=c,p=profile(bLowHpAction=True,lowHpAction=action(1001,notice=2,value=50,bUseNextSkill=True)))
# Enemy condition is coordinate order and strict absolute threshold, not HP ordering.
for comparison in [1,2]:
    for threshold in [0,40,40.0,40.5,60,61,2**53+1,float(2**53),2**63-1,float(2**63),1e200]:
        for hp in [40,2**53+1,2**63-1]:
            s=state();s['battle_units']['3:1']['hp']=hp
            add('enemy strict numeric',s=s,p=profile(bEnemyHPAction=True,enemyHpAction=action(10001,compareKind=comparison,value=threshold)))
# Notice/metadata only target the first coordinate match; opposite-side ownership retained.
for attr in ['hp','sp']:
    for notice in [1,2,3]:
        for kind in [0,1,3,5]:
            for mode in ['full','missing','opposite','missing_pid','alias']:
                c=cat();c['skills']['1001']['TargetKind']=kind;s=state()
                for u in s['battle_units'].values():u[attr]=20
                if mode=='missing':
                    for u in s['battle_units'].values():u.pop(attr)
                if mode=='opposite':s['battle_units']['1:1']['pid']=77;s['battle_units']['2:1']['master_id']=99;s['battle_units']['3:1'].update(pid=7,master_id=7)
                if mode=='missing_pid':s['battle_units']['1:1'].pop('pid')
                if mode=='alias':s['battle_units']['alias']=s['battle_units'].pop('1:1')
                flag,key=('bLowHpAction','lowHpAction') if attr=='hp' else ('bLowSpAction','lowSpAction')
                add('notice '+attr+' '+str(notice)+' '+str(kind)+' '+mode,s=s,c=c,p=profile(**{flag:True,key:action(1001,notice=notice,value=30)}))
# Food fixed/automatic, resource override, unusable inventory falls through.
for id in [-2,-3,42,43]:
    for attr in ['hp','sp']:
        for mode in ['full','blocked','alias','reserved']:
            s=state();s['battle_units']['1:1']['hp']=50
            if mode=='blocked':s['inventory']['ready']=False
            if mode=='alias':s['battle_units']['alias']=s['battle_units'].pop('1:1')
            if mode=='reserved':s['inventory']['reserved']={'9':2,'2':3,'1':4}
            flag,key=('bLowHpAction','lowHpAction') if attr=='hp' else ('bLowSpAction','lowSpAction')
            add('food '+str(id)+' '+attr+' '+mode,s=s,p=profile(**{flag:True,key:action(id,kind=2,notice=2,value=100)}))
# Round/repeat use valid arrays padded by actual validation; signed modulo remains pure.
for round_number in [-(2**63),-100,-5,-1,0,1,2,3,4,5,6,2**63-1]:
    for repeat in [[],[action(60021)],[action(),action(60021),action(),action(60041)],[action(1001),action(60041),action(60021),action(10008),action(10001)]]:
        s=state();s['battle']['round']=round_number;s['battle']['active']=False
        for enabled in [True,False]:add('round/repeat modulo',s=s,p=profile(bRoundAction=enabled,roundAction=[action(60021),action(),action(60041)],bRepeatAction=True,repeatAction=repeat))
# Order/fallback carries last nonzero preference, while empty/disabled scans coordinates.
for target in [1,2,3]:
    for mode in ['disabled','empty','zero','normal','catch','best','learned','failed','last_zero','last_failure']:
        c=cat();c['skills']['1001']['ReduceSP']=999;s=state();p=profile(bOrderAction=mode!='disabled')
        sid={'normal':10001,'catch':10008,'best':-1,'learned':1002}.get(mode,1001)
        p['orderAction']=[] if mode=='empty' else [action(0 if mode=='zero' else sid,target=target)]
        if mode=='last_zero':p['orderAction'].append(action(0,target=1))
        if mode=='last_failure':p['orderAction'].append(action(1001,target=1))
        add('order '+mode+' '+str(target),s=s,c=c,p=p)
# Only ProtocolError is suppressed, reached KeyError must not become a later defend.
for field in ['Kind','KindSort','TargetKind','TargetNPCID','Element','CostItemID','CostItemCount','WeaponKind1']:
    for sid in [1001,-1]:
        c=cat();c['skills']['1001'].pop(field)
        add('malformed catalog '+field+' '+str(sid),c=c,p=profile(bOrderAction=True,orderAction=[action(sid,target=2),action(60021)]))
for mode in ['no_enemies','unknown_hp','dead_enemies','exited_enemies','no_equipment','no_normal_row','malformed_unused']:
    s=state();a=actor();c=cat();n=normal()
    if mode=='no_enemies':s['battle_units']={}
    for u in s['battle_units'].values():
        if u['col']>2:
            if mode=='unknown_hp':u.pop('hp')
            if mode=='dead_enemies':u['hp']=0
            if mode=='exited_enemies':u['exited']=True
    if mode=='no_equipment':a['equips']=[]
    if mode=='no_normal_row':a['equips'][2]=dict(item_id=65535)
    if mode=='malformed_unused':c['skills']['1001'].pop('Kind')
    add('fallback '+mode,s=s,a=a,c=c,n=n,p=profile())
# Random composition with valid typed profile domains and explicit sparse observations.
for index in range(600):
    c=cat();s=state();p=profile();a=actor()
    for row in c['skills'].values():row.update(ReduceSP=R.choice([0,10,11]),TargetKind=R.randrange(6),FightWay=R.choice([1,2,8,24]),NextSkillId=R.choice([0,1002]))
    s['battle']['round']=R.choice([-5,-1,0,1,2,3,4,6]);s['battle']['war_style']=R.choice([0,0,16,21]);s['inventory']['ready']=index%13!=0
    for unit in s['battle_units'].values():
        unit.update(hp=R.choice([0,1,40,100]),sp=R.choice([-1,0,10,20]),exited=index%23==0,is_fly=index%17==0)
        if R.randrange(20)==0:unit.pop(R.choice(['hp','sp','master_id']))
    for flag,key in keys:
        p[flag]=R.choice([False,True]);count={'roundAction':3,'repeatAction':5,'orderAction':2}.get(key)
        def make():
            id=R.choice([0,-1,-2,-3,10001,60021,60041,10008,1001,1002,42,43]);row=action(id,kind=2 if id in [-2,-3,42,43] else 1,target=R.randrange(1,4))
            if key in ['lowHpAction','lowSpAction']:row.update(notice=R.randrange(1,4),value=R.choice([0,1,10,20,50,100,100.5]))
            if key=='enemyHpAction':row.update(compareKind=R.randrange(1,3),value=R.choice([0,1,40,100]))
            if row['kind']==1:row['bUseNextSkill']=R.choice([False,True])
            return row
        p[key]=[make() for _ in range(R.randrange(count+1))] if count else make()
    add('random '+str(index),p=p,s=s,a=a,c=c)
paths=['wlre/services/battle/auto_battle.py','wlre/services/battle/battle_commands.py','wlre/services/battle/combat.py','wlre/services/items/combat_resources.py','wlre/services/items/inventory.py','wlre/services/items/reservations.py','wlre/services/items/catalog.py','wlre/services/items/live_combat_catalog.py']
hashes={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in paths}
payload=json.dumps(dict(source_sha256=hashes,cases=CASES),ensure_ascii=False,separators=(',',':')).encode()
buffer=io.BytesIO()
with gzip.GzipFile(fileobj=buffer,mode='wb',filename='',mtime=0,compresslevel=9) as stream:stream.write(payload)
compressed=buffer.getvalue();assert len(compressed)<500_000;assert gzip.decompress(compressed)==payload
out=Path(__file__).parent;(out/'Fixtures').mkdir(exist_ok=True);(out/'Fixtures/auto-battle.json.gz').write_bytes(compressed)
cs='''// Generated by generate_auto_battle_vectors.py; deterministic real-Python oracle.
using System.Text.Json.Nodes;
using Lala.Core.Tests.TestSupport;
namespace Lala.Core.Tests.Battle;
public static class AutoBattlePythonVectors
{
    internal static JsonNode Read() => JsonNode.Parse(GzipJson.DecodeResource(
        "Lala.Core.Tests.Battle.Fixtures.auto-battle.json.gz", "COMPRESSED", "DECODED"))!;
    public static IEnumerable<object[]> Cases()
    {
        foreach (var row in Read()["cases"]!.AsArray()) yield return [row!["case_id"]!.GetValue<int>(),row.ToJsonString()];
    }
}
'''.replace('COMPRESSED',hashlib.sha256(compressed).hexdigest()).replace('DECODED',hashlib.sha256(payload).hexdigest())
(out/'AutoBattlePythonVectors.cs').write_text(cs,encoding='utf8')
print(f'Generated {len(CASES)} actual Python vectors; gzip {len(compressed)} bytes; JSON {len(payload)} bytes')
print('Outcomes:',{key:sum(row['expected']['error'] is not None and row['expected']['error']['type']==key for row in CASES) for key in ['ProtocolError','KeyError','TypeError','ValueError']})
print('Reasons:',{key:sum(row['expected']['reason']==value for row in CASES) for key,value in source.REASONS.items()})
