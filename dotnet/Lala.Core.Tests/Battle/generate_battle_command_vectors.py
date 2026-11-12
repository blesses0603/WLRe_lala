"""Real retained battle_commands oracle; explicit synthetic catalogs, no runtime/send calls."""
import copy, gzip, hashlib, io, json, os, random, sys
from pathlib import Path
from unittest.mock import patch
os.environ['WLRE_DISABLE_AUTO_CATALOG']='1'
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from wlre.services.battle import battle_commands as source, combat
from wlre.services.items import inventory
from wlre.services.items.live_combat_catalog import _pinned
R=random.Random(202611080731); CASES=[]
# Synthetic builders mirror existing candidate fixtures. All expected decisions below
# come from the retained functions themselves, not a second selector implementation.
def actor(pid=7,col=1,row=1,**kw):
    value=dict(pid=pid,master_id=0,npc_index=0,col=col,row=row,hp=100,sp=10,max_hp=200,max_sp=20,level=30,degree=0,
        equips=[dict(item_id=0)]*6,statuses={},sex=1,head=2)
    value.update(kw);return value

def skill(sid=1001,**kw):
    value=dict(ID=sid,Kind=1,KindSort=1,TargetKind=0,ReduceSP=0,ReduceHP=0,FightWay=1,RangeKind1=1,CostItemID=0,CostItemCount=0,LvLimit=5,
        HitStatus=0,TargetNPCID=0,Element=2,AtkKind=1,Sort=0,NextSkillId=0,WeaponKind1=1,WeaponKind2=1,WeaponKind3=1,WeaponKind4=1,WeaponKind5=1)
    value.update(kw);return value

def item(index,id=42,count=3,**kw):
    value=dict(index=index,item_id=id,count=count,damage=0,serial_version=0,serial=index,magic_spar=0,available_time=0.,limited_time=0.,beat_level=0,differ=0,modeling=0,saddle_beat_level=0,enhance_level=0,design_id=0,plugins=[],locked=False,star_soul_kind=0,star_soul_level=0)
    value.update(kw);return value

def cat():
    return dict(keys={},items={'0':dict(kind=0), '42':dict(kind=23,attributes=[dict(kind=25,value=200),dict(kind=26,value=110)]),
        '43':dict(kind=32,attributes=[dict(kind=25,value=140),dict(kind=26,value=150)])},npcs={},skills={'1001':skill()},characters=[],element_weights={})

def state():
    return dict(player=dict(role_id=7),knowledge=dict(player=dict(skills={'1001':dict(level=5,exp=0,source='S8-1')},stats={}),companions={}),
        inventory=dict(ready=True,reliable=True,revision=0,use_failed=False,items={'9':item(9,42,2),'2':item(2,42,3),'1':item(1,43,4)},reserved={},holds={},alchemy_slots=[],expedition_slots=[],maintenance_slots=[]),
        battle=dict(active=True,round=1,commands={},war_style=0),battle_units={'enemy':actor(101,3,2,hp=40),'companion':actor(80,2,1,master_id=7), 'player':actor()})

def normal():
    return dict(items={str(i):i for i in range(12)},npcs={str(i):dict(kind=0,bodyType=1,normalAttackKind=1,canCatch=i>=100) for i in [80,81,101,102]},catch_nets={'99':20})

def add(kind='round',s=None,a=None,t=None,c=None,n=None,label='',typed=None,**args):
    s=copy.deepcopy(s if s is not None else state());a=copy.deepcopy(a if a is not None else actor());t=copy.deepcopy(t if t is not None else actor(101,3,2))
    c=copy.deepcopy(c if c is not None else cat());n=copy.deepcopy(n if n is not None else normal());names={'42':'測試材料','43':''}
    before=copy.deepcopy((s,a,t,c,n,args));token=_pinned.set(c)
    try:
        with patch.object(inventory,'item_name',side_effect=lambda id:names.get(str(id),f'物品{id}')),patch.object(combat.DATA,'snapshot',return_value=n):
            try:
                if kind=='round': result=source.plan_round(s,**args)
                elif kind=='action':result=source.action_command(s,a,**args)
                elif kind=='catch':result=source.catch_allowed(s,a,t)
                elif kind=='owned':result=[next(k for k,v in s['battle_units'].items() if v is u) for u in source.owned_units(s,**args)]
                elif kind=='identity':result=source.identity(a)
                elif kind=='slot':result=source.slot(a)
                else:raise ValueError(kind)
                expected=dict(value=result,error=None)
            except Exception as exc:expected=dict(value=None,error=dict(type=type(exc).__name__,message=str(exc)))
    finally:_pinned.reset(token)
    assert before==(s,a,t,c,n,args),'Retained Python mutated input'
    CASES.append(dict(case_id=len(CASES),label=label,kind=kind,state=s,actor=a,target=t,catalog=c,normal=n,names=names,args=args,expected=expected,typed_rejection=typed))

add(label='baseline')
for kind in ['owned','identity','slot','catch']:add(kind)
# Ordering uses local player first, then coordinates, stable source insertion ties.
for role in [None,0,7,2**32-1]:
    for living in [False,True]:
        s=state();s['player']={} if role is None else dict(role_id=role)
        s['battle_units']={'dead':actor(80,1,1,master_id=7,hp=0),'other':actor(9,0,0), 'late':actor(81,2,9,master_id=7),
            'local_high':actor(7,2,3),'tie_one':actor(80,1,2,master_id=7),'local_low':actor(7,1,9),
            'tie_two':actor(81,1,2,master_id=7),'exited':actor(81,1,0,master_id=7,exited=True), 'max_id':actor(2**32-1,-1,2**31-1)}
        s['battle_units']['unknown']=actor(80,1,3,master_id=7);s['battle_units']['unknown'].pop('hp')
        add('owned',s=s,living=living)
for pid in [0,7,2**32-1]:
    for master in [None,0,7,2**32-1]:
        a=actor(pid,-2**31,2**31-1)
        if master is None:a.pop('master_id')
        else:a['master_id']=master
        add('identity',a=a);add('slot',a=a)
# Capture evidence gates, ownership of dead/exited duplicates, actor equipment and
# master's level even if dead, versus companion's own appearance and net bonus.
for mode in ['base','npc_missing','false','owned_dead','owned_exited','master_dead','master_absent','master_missing_level','actor_missing_level','target_missing_level','short_equips','missing_master_id','companion','companion_own_level','net','no_net','flying']:
    s=state();a=actor();t=actor(101,3,1,level=36);n=normal()
    if mode=='npc_missing':n['npcs'].pop('101')
    if mode=='false':n['npcs']['101']['canCatch']=False
    if mode.startswith('owned_'):s['battle_units']['duplicate']=actor(101,2,9,master_id=7,hp=0 if mode=='owned_dead' else 1,exited=mode=='owned_exited')
    if mode=='master_dead':s['battle_units']['player']['hp']=0;a=actor(80,2,1,master_id=7)
    if mode=='master_absent':s['battle_units'].pop('player');a=actor(80,2,1,master_id=7)
    if mode=='master_missing_level':s['battle_units']['player'].pop('level');a=actor(80,2,1,master_id=7)
    if mode=='actor_missing_level':a.pop('level')
    if mode=='target_missing_level':t.pop('level')
    if mode=='short_equips':a['equips']=a['equips'][:5]
    if mode=='missing_master_id':a.pop('master_id')
    if mode in ['companion','companion_own_level']:a=actor(80,2,1,master_id=7,level=999 if mode.endswith('own_level') else 0)
    if mode=='net':a['equips'][5]=dict(item_id=99)
    if mode=='no_net':a['equips'][5]=dict(item_id=98)
    if mode=='flying':t['is_fly']=True
    add('catch',s=s,a=a,t=t,n=n,label=mode)
for degree,level,bonus in [(0,0,0),(1,1,-10),(-1,2,100),(-(2**63),2**63-1,2**63-1),(2**63-1,-(2**63),-(2**63)),(2**53+1,2**53+3,-(2**53))]:
    for target in [-(2**63),0,1,35,36,2**63-1]:
        a=actor(degree=degree,level=level);a['equips'][5]=dict(item_id=99);n=normal();n['catch_nets']['99']=bonus
        add('catch',a=a,t=actor(101,3,1,level=target),n=n,label='unbounded_level_arithmetic')
# Every action mode, target-key distinction, liveness and target tie ordering.
for mode in ['auto_skill','heal_hp','heal_sp','normal','defend','escape','catch','unknown','', 'NORMAL']:
    for slot in [None,'','enemy','3:2','absent']:
        for status in ['base','dead_actor','missing_actor_hp','no_targets','flying_enemy','exited_enemy','dead_enemy','missing_enemy_hp']:
            s=state();a=actor()
            if status=='dead_actor':a['hp']=0
            if status=='missing_actor_hp':a.pop('hp')
            if status=='no_targets':s['battle_units']={}
            if status=='flying_enemy':s['battle_units']['enemy']['is_fly']=True
            if status=='exited_enemy':s['battle_units']['enemy']['exited']=True
            if status=='dead_enemy':s['battle_units']['enemy']['hp']=0
            if status=='missing_enemy_hp':s['battle_units']['enemy'].pop('hp')
            add('action',s=s,a=a,mode=mode,target_slot=slot,label=status)
for mode in ['normal','catch']:
    for first_hp,second_hp in [(1,1),(2**63-1,2**53+1),(2**53+1,2**53),(-1,1)]:
        s=state();s['battle_units']={'first':actor(101,3,2,hp=first_hp),'second':actor(102,3,1,hp=second_hp),'player':actor()}
        add('action',s=s,mode=mode)
# Readiness precedes all ownership/mode errors; exclusion uses coordinates plus commands keys.
for active in [False,True]:
    for round in [-(2**63),-1,0,1,2**63-1]:
        for slots in [[],['1:1'],['2:1'],['1:1','2:1'],['player','companion']]:
            s=state();s['battle'].update(active=active,round=round,commands={k:{} for k in slots[::2]})
            add(s=s,excluded=slots[1::2],modes={'1:1':'unknown','2:1':'defend'},label='round_precedence_exclusions')
# Shared hypothetical item usage: skill+food, food+food and exhausted later actor.
for qty in range(1,7):
    for reserved in [0,1,2,2**80]:
        for first,second,third in [('auto_skill','heal_hp','heal_sp'),('heal_hp','heal_hp','heal_sp'),('normal','defend','escape'),('auto_skill','auto_skill','heal_hp')]:
            c=cat();c['skills']['1001'].update(CostItemID=42,CostItemCount=2);s=state()
            s['inventory']['items']={'2':item(2,42,qty)};s['inventory']['reserved']={'2':reserved}
            s['battle_units']['companion_two']=actor(81,2,2,master_id=7,name='伙伴二')
            s['battle_units']['player']['name']='角色';s['battle_units']['companion']['name']=''
            add(s=s,c=c,modes={'1:1':first,'2:1':second,'2:2':third},label='shared_round_reservations')
# No status/HP mutation from projected actions; two local observations also share skill cost.
for qty in [3,4,5,6]:
    c=cat();c['skills']['1001'].update(CostItemID=42,CostItemCount=2);s=state()
    s['inventory']['items']={'2':item(2,42,qty)};s['battle_units']['same_owner']=actor(7,1,2)
    add(s=s,c=c,modes={'1:1':'auto_skill','1:2':'auto_skill','2:1':'heal_hp'},label='two_skill_proposals')
# Only ProtocolError is actor-prefixed, while a malformed reached field aborts directly.
for field in ['ID','Kind','TargetKind','TargetNPCID','CostItemCount']:
    c=cat();c['skills']['1001'].pop(field);s=state();s['battle_units']['player']['name']='Named'
    add(s=s,c=c,modes={'1:1':'auto_skill'},label='key_error_not_prefixed')
for gate in ['ready','reliable','use_failed','ban','empty','excluded','missing_role','unknown_hp','dead','exited']:
    s=state()
    if gate in ['ready','reliable']:s['inventory'][gate]=False
    if gate=='use_failed':s['inventory'][gate]=True
    if gate=='ban':s['battle']['war_style']=9
    if gate=='empty':s['battle_units']={}
    if gate=='excluded':s['battle']['commands']={'1:1':{},'2:1':{}}
    if gate=='missing_role':s['player']={}
    for unit in s['battle_units'].values():
        if gate=='unknown_hp':unit.pop('hp')
        if gate=='dead':unit['hp']=0
        if gate=='exited':unit['exited']=True
    add(s=s,modes={'1:1':'heal_hp','2:1':'heal_sp'},label=gate)
for i in range(280):
    s=state();c=cat();n=normal();s['battle_units']={}
    for j in range(R.randrange(1,8)):
        pid=R.choice([7,80,81,101,102]);col=R.randrange(1,5);row=R.randrange(1,4)
        u=actor(pid,col,row,master_id=R.choice([0,7,9]),hp=R.choice([0,1,99,2**63-1]),sp=R.choice([0,10]),exited=i%19==0,level=R.randrange(25,40))
        if i%13==0:u.pop('hp')
        if i%17==0:u.pop('level')
        if i%23==0:u['equips']=[]
        if i%29==0:u['equips']=[dict(item_id=0),dict(item_id=0),dict(item_id=999)]
        s['battle_units'][f'key{j}']=u
    s['battle']['commands']={R.choice(['1:1','2:1','3:1']):{}} if i%3==0 else {}
    s['inventory']['reserved']={str(R.choice([1,2,9])):R.choice([-1,0,1,2**80])}
    if i%7==0:s['inventory']['alchemy_slots']=['2']
    if i%11==0:s['inventory']['ready']=False
    c['skills']['1001'].update(CostItemID=R.choice([0,42]),CostItemCount=R.choice([0,1,3]),ReduceSP=R.choice([0,11]))
    modes={f'{col}:{row}':R.choice(list(source.ACTIONS)) for col in range(1,5) for row in range(1,4)}
    add(s=s,c=c,n=n,modes=modes,target_slot=R.choice([None,'','3:1','key0']),excluded=R.sample(['1:1','2:1','3:1'],R.randrange(3)),label='random_round')
# Keep actual unsupported source results, but assert typed rejection explicitly.
a=actor();a.pop('pid');add('identity',a=a,typed='identity_missing_pid')
a=actor();a.pop('pid');add('action',a=a,mode='defend',typed='action_missing_pid')
s=state();s['battle_units']['companion'].pop('pid');add('owned',s=s,typed='owned_missing_pid')
s=state();s['player']={};add('catch',s=s,typed='capture_missing_role')
# A battle intent cannot name an absent actor. Existing general candidate helpers
# admit nullable identities; the battle boundary rejects only reached successful
# emission, preserving all preceding food errors. Retain real Python observations.
for mode in ['heal_hp','heal_sp','auto_skill']:
    a=actor();a.pop('pid');c=cat()
    if mode=='auto_skill':c['items']['0']['skill_link']=1001
    add('action',a=a,c=c,mode=mode,typed='action_missing_pid',label='missing_identity_at_emission')
for mode in ['heal_hp','heal_sp']:
    for gate in ['not_ready','no_targets','no_food']:
        a=actor();a.pop('pid');s=state()
        if gate=='not_ready':s['inventory']['ready']=False
        if gate=='no_targets':s['battle_units']={}
        if gate=='no_food':s['inventory']['items']={}
        add('action',a=a,s=s,mode=mode,label='missing_identity_'+gate)
paths=['wlre/services/battle/battle_commands.py','wlre/services/battle/combat.py','wlre/services/items/combat_resources.py','wlre/services/items/inventory.py','wlre/services/items/reservations.py','wlre/services/items/catalog.py','wlre/services/items/live_combat_catalog.py']
hashes={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in paths}
payload=json.dumps(dict(source_sha256=hashes,cases=CASES),ensure_ascii=False,separators=(',',':')).encode();buffer=io.BytesIO()
with gzip.GzipFile(fileobj=buffer,mode='wb',filename='',mtime=0,compresslevel=9) as stream:stream.write(payload)
compressed=buffer.getvalue();assert len(compressed)<=500_000;assert gzip.decompress(compressed)==payload
out=Path(__file__).parent;(out/'Fixtures').mkdir(exist_ok=True);(out/'Fixtures/battle-commands.json.gz').write_bytes(compressed)
cs='''// Generated by generate_battle_command_vectors.py; actual retained Python oracle.
using System.Text.Json.Nodes;
using Lala.Core.Tests.TestSupport;
namespace Lala.Core.Tests.Battle;
public static class BattleCommandPythonVectors
{
    internal static JsonNode Read() => JsonNode.Parse(GzipJson.DecodeResource(
        "Lala.Core.Tests.Battle.Fixtures.battle-commands.json.gz",
        "COMPRESSED", "DECODED"))!;
    public static IEnumerable<object[]> Cases()
    {
        foreach (var row in Read()["cases"]!.AsArray()) yield return [row!["case_id"]!.GetValue<int>(),row.ToJsonString()];
    }
}
'''.replace('COMPRESSED',hashlib.sha256(compressed).hexdigest()).replace('DECODED',hashlib.sha256(payload).hexdigest())
(out/'BattleCommandPythonVectors.cs').write_text(cs,encoding='utf8')
print(f'Generated {len(CASES)} vectors; gzip {len(compressed)}; decoded {len(payload)}')
print('Outcomes:',{kind:sum(row['expected']['error'] is not None and row['expected']['error']['type']==kind for row in CASES) for kind in ['ProtocolError','KeyError','TypeError','ValueError']})
print('Typed rejection:',sum(row['typed_rejection'] is not None for row in CASES))
