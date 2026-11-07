"""Offline actual defaults/decode_ark/apply_ark/_remember_question failure-path oracle.

QuestionStore construction is replaced with a deterministic OSError before any SQLite
or filesystem access. runtime_catalog is injected with explicit synthetic read results.
The real _remember_question runs (including real identity/fingerprint validation), not a
reimplementation. Successful persistence, candidate resolution and arithmetic are excluded.
All expected snapshots come directly from retained Python. The deferred .NET composition
status is deliberately tested separately rather than falsely labeled a Python store fault.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import sys
from types import SimpleNamespace
from unittest.mock import patch

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'dotnet/Lala.Core.Tests/TestSupport'))
from gzip_json_fixture import csharp_gzip_json
from wlre.services import star_ark as ark
from wlre.network.wire import Packet, ProtocolError

RNG = random.Random(7919111)
TOKEN = (True, 'a' * 64)
TEXTS = {101: '請問1+1=?', 201: '1', 202: '2', 203: '3', 204: '4'}
SCENARIOS = []
def pack(fmt, *args): return struct.pack('<'+fmt, *args)
def eventrow(index=1, id=123, kind=3, planet=1, main=False): return dict(index=index,id=id,kind=kind,planet=planet,main=main)
def context(role=17, generation=8, available=True, token=TOKEN, texts=None, second=None):
    return dict(role=role, daily_generation=generation,
                current=dict(available=available, token=token, texts=TEXTS if texts is None else texts), second=second)
def pending(kind='question', **updates):
    value=dict(kind=kind, role=17, token=TOKEN, daily_generation=8, due=100.5, task_before=2)
    if kind=='dispatch': value.update(quote=dict(planet=1,agent=1,duration=60,price=20,hours=1),balance=100,paid=False,ship_ack=False)
    elif kind in ('fight','question'):
        value.update(event=eventrow(kind=1 if kind=='fight' else 3),complete=False,result=False,bag_needed=False)
        if kind=='fight':value.update(awards=[dict(kind=10,id=100,value=2)],bag_revision=9,bag_expected={100:2},bag_before={100:0})
    value.update(updates)
    return value

def question(**updates):
    value=dict(type='ark_question',question=101,award=dict(kind=6,id=8,value=5),options=[201,202,203,204],
               selected=2,text=TEXTS[101],labels=[TEXTS[i] for i in (201,202,203,204)],known_answer=202,
               answer_kind='reviewed_candidate',answer_source='synthetic source',candidate_reason='synthetic reason',
               candidate_revision='synthetic revision',candidate_source='user_reviewed',selected_candidate=True)
    value.update(updates);return value

def populated(**updates):
    value=dict(role=17,ready=True,events_ready=True,planet=2,explore=100,
        agents={1:dict(index=1,id=5,skills=[1,2],planet=0),2:dict(index=2,id=6,skills=[3,4],planet=0)},
        ship=dict(total=0,remaining=0,awarded=0,planet=0,agents=[0,0]),events={1:eventrow()},main_events={1:eventrow(id=10001,main=True)},
        generation=4,attempted=[(TOKEN,4,False,1,123)],starcoin=dict(ready=True,reliable=True,amount=100,revision=7),
        reserved=20,confirmed=10,settings_revision=3,catalog_token=TOKEN,rows=[dict(opaque='retained')],quote=dict(opaque='retained'),
        answers={'historical-key':204},status='合成保留狀態')
    value.update(updates);return value

def snapshot():
    return pack('BHB',2,100,2)+bytes([1,5,1,2,0,2,6,3,4,0])+pack('HhH',0,0,0)+bytes(60)
def events():return b''.join(pack('HBB',123 if i==1 else 0,3 if i==1 else 0,1 if i==1 else 0) for i in range(1,13))+b'\0'
def main_events():return b''.join(pack('HB',10001 if i==1 else 0,3 if i==1 else 0) for i in range(1,21))
def qpacket(kind=6, id=8):return pack('IBII4I',101,kind,id,5,201,202,203,204)
def fight(won=True,id=123,awards=None):
    awards=[(0,0,0),(10,100,2)] if awards is None else awards
    return bytes([won])+(pack('HB',id,len(awards))+b''.join(pack('BII',*a) for a in awards) if won else b'')

def unavailable_store(*_a, **_k):raise OSError('synthetic unavailable-store boundary, no filesystem access')

class Scenario:
    def __init__(self,name,seed=None,ctx=None):
        self.name=name;self.ctx=context() if ctx is None else copy.deepcopy(ctx)
        self.state=SimpleNamespace(star_ark=ark.defaults(),player={},daily_tasks={})
        if seed:self.state.star_ark.update(copy.deepcopy(seed))
        self.initial=copy.deepcopy(self.state.star_ark);self.steps=[]
    def packet(self,sub,data=b'',main=191,ctx=None):
        operation=dict(main=main,sub=sub,hex=data.hex());error=None;intents=[]
        try:event=ark.decode_ark(Packet(main,sub,data))
        except ProtocolError as exc:event=None;error=str(exc)
        if event is not None:self.apply(event,intents,ctx)
        self.record(operation,error,intents,ctx);return self
    def direct(self,event,ctx=None):
        intents=[];self.apply(event,intents,ctx);self.record(dict(direct=event),None,intents,ctx);return self
    def apply(self,event,intents,ctx):
        ctx=copy.deepcopy(self.ctx if ctx is None else ctx)
        self.state.player={'role_id':ctx['role']};self.state.daily_tasks={'generation':ctx['daily_generation']}
        if event['type']=='world_player':self.state.player={'role_id':event['player']['role_id']}
        reads=[ctx['current'],ctx['second'] or ctx['current']];index=0
        def runtime():
            nonlocal index
            read=reads[min(index,1)];index+=1
            return ({'texts':read['texts']} if read['available'] else None),read['token'],'synthetic runtime'
        remember=ark._remember_question
        def trace(state,p,q,correct=None):
            selected=q.get('selected');answer=None if selected is None else q['options'][selected-1]
            operation='Observe' if correct is None else 'Confirm' if correct else 'Reject'
            rejected=correct is False and (q.get('selected_candidate',False) or
                (q.get('answer_kind') in ('computed','reviewed_candidate') and answer==q.get('known_answer')))
            intents.append(copy.deepcopy(dict(operation=operation,token=p['token'],role=p['role'],daily_generation=p['daily_generation'],
                ark_generation=state.star_ark['generation'],event=p.get('event'),question=q,selected_answer=answer,rejected_candidate=rejected)))
            remember(state,p,q,correct)
        with patch.object(ark,'runtime_catalog',runtime),patch.object(ark,'QuestionStore',unavailable_store),patch.object(ark,'_remember_question',trace):
            ark.apply_ark(self.state,event)
    def record(self,operation,error,intents,ctx):
        self.steps.append(dict(operation=operation,error=error,context=copy.deepcopy(self.ctx if ctx is None else ctx),
                               expected=copy.deepcopy(self.state.star_ark),intents=intents))
    def finish(self):SCENARIOS.append(dict(name=self.name,initial=self.initial,steps=self.steps))

# All decoded receive branches, defaults, replacements and same/different role behavior.
for role in (None,0,17,18,0xffffffff):
    s=Scenario('role_gates_'+str(role),seed=populated(role=role))
    for sub,data in [(1,snapshot()),(2,events()),(7,b'\x03\x07'),(17,pack('BH',21,10000)),(11,qpacket())]:s.packet(sub,data)
    s.direct(dict(type='unrelated')).direct(dict(type='world_player',player={'role_id':17})).packet(1,snapshot())
    s.direct(dict(type='world_player',player={'role_id':17})).direct(dict(type='world_player',player={'role_id':18}))
    s.direct(dict(type='role_list_available')).finish()

for kind in (None,'dispatch','fight','question','future'):
    seed=populated(pending=None if kind is None else pending(kind),question=question(),uncertain=True)
    for sub,data in [(0,b'\xff'),(1,snapshot()),(2,events()),(3,pack('BBBBH',1,1,1,0,60)),(4,pack('HBHH',60,1,300,2)),
        (5,b'\x01\x01'),(6,b'\x01\x02\xff'),(7,b'\x01\x05'),(7,b'\x03\x07'),(10,pack('BH',1,123)),
        (10,pack('BH',2,124)),(15,fight()),(15,fight(False)),(16,main_events()),(17,pack('BH',20,10000)),
        (18,pack('BHB',1,10002,1)),(19,pack('Bh',1,32767)),(11,qpacket()),(12,b'\1\2')]:
        s=Scenario(f'pending_{kind}_{sub}_{data.hex()[:14]}',seed=seed);s.packet(sub,data).packet(sub,data).finish()

# Monetary arithmetic, zero-offset baselines, matching debit and duplicates.
for ready in (False,True):
 for reliable in (False,True):
  for amount,offset,add in [(80,20,False),(100,0,True),(120,20,True),(81,20,False),(0xffffffff,0xffffffff,True),(0,0xffffffff,False)]:
   for paid in (False,True):
    seed=populated(pending=pending('dispatch',paid=paid),starcoin=dict(ready=ready,reliable=reliable,amount=100,revision=2**70))
    s=Scenario(f'coin_{ready}_{reliable}_{amount}_{offset}_{add}_{paid}',seed=seed)
    s.packet(24,pack('IIBB',amount,offset,add,False),75).packet(24,pack('IIBB',amount,offset,add,False),75).finish()
for amount in (None,0,0xffffffff):
 s=Scenario('coin_no_pending_'+str(amount),seed=populated(starcoin=dict(ready=amount is not None,reliable=False,amount=amount,revision=0)))
 s.packet(24,pack('IIBB',123,0,0,1),75).packet(24,pack('IIBB',124,1,1,0),75).finish()

# Dispatch ack permutations preserve the source distinction between evidence and success.
for ready in (False,True):
 for planet,ids,total in [(1,[1,0],60),(2,[1,0],60),(1,[2,0],60),(1,[1,2],60),(1,[1,0],61),(1,[3,0],60)]:
  for ack in (False,True):
   s=Scenario(f'dispatch_{ready}_{planet}_{ids}_{total}_{ack}',seed=populated(ready=ready,pending=pending('dispatch',ship_ack=ack)))
   s.packet(3,pack('BBBBH',planet,1,*ids,total)).packet(5,bytes([planet,1])).finish()
for ship in ({},dict(total=60,remaining=30,awarded=0,planet=1,agents=[1,3])):
 for end in (1,2):
  s=Scenario(f'collect_end_{ship}_{end}',seed=populated(ship=ship,pending=pending('future')))
  s.packet(19,pack('Bh',1,5)).packet(5,bytes([end,1])).finish()
for index in (1,3):
 s=Scenario('skill_and_agent_'+str(index),seed=populated(pending=pending('dispatch')))
 s.packet(6,bytes([index,1,255])).packet(7,bytes([index,9])).packet(7,bytes([index,9])).finish()

for complete in ((1,123),(1,124),(2,123),(1,10001)):
 for row_present in (False,True):
  s=Scenario(f'complete_{complete}_{row_present}',seed=populated(events={1:eventrow()} if row_present else {},pending=pending('question')))
  s.packet(10,pack('BH',*complete)).packet(10,pack('BH',*complete)).finish()
for awards in ([],[(10,100,2)],[(0,9,100),(10,100,2),(0,7,22)],[(10,100,3)],[(10,100,2),(10,100,2)]):
 for id in (123,124):
  s=Scenario(f'fight_awards_{id}_{awards}',seed=populated(pending=pending('fight')))
  s.packet(15,fight(id=id,awards=awards)).packet(15,fight(id=id,awards=awards)).finish()

# Current-question identity guards (including the second runtime read).
contexts=[context(),context(role=18),context(generation=9),context(available=False),context(token=(True,'b'*64)),
          context(texts={}),context(texts={k:v for k,v in TEXTS.items() if k!=204}),
          context(second=dict(available=True,token=(True,'b'*64),texts=TEXTS)),
          context(second=dict(available=False,token=TOKEN,texts=TEXTS))]
for i,ctx in enumerate(contexts):
 for kind in ('question','dispatch',None):
  s=Scenario(f'question_identity_{i}_{kind}',seed=populated(pending=pending(kind) if kind else None),ctx=ctx)
  s.packet(11,qpacket()).packet(12,b'\1\2').packet(11,qpacket()).finish()
for kind,id in ((6,8),(6,9),(22,999),(10,8),(0,0)):
 s=Scenario(f'question_award_{kind}_{id}',seed=populated(pending=pending()))
 s.packet(11,qpacket(kind,id)).finish()
for token in ((False,'a'*64),(True,None),(True,'x'*64),(True,'a'*63),TOKEN):
 s=Scenario('question_identity_validation_'+str(token),seed=populated(pending=pending(token=token)),ctx=context(token=token))
 s.packet(11,qpacket()).finish()
for selected in (None,1,2,4):
 for correct in (False,True):
  for received in (1,2,4):
   for result in (False,True):
    s=Scenario(f'answer_{selected}_{correct}_{received}_{result}',seed=populated(pending=pending(result=result),question=question(selected=selected)))
    s.packet(12,bytes([correct,received])).packet(12,bytes([correct,received])).finish()
for kind in ('computed','reviewed_candidate','server_confirmed',''):
 for known in (None,201,202):
  for claimed in (False,True):
   s=Scenario(f'wrong_candidate_{kind}_{known}_{claimed}',seed=populated(pending=pending(),question=question(answer_kind=kind,known_answer=known,selected_candidate=claimed)))
   s.packet(12,b'\0\4').finish()

s=Scenario('generation_and_replacement',seed=populated(generation=2**100,pending=pending('dispatch')))
s.packet(18,pack('BHB',1,10002,3)).packet(10,pack('BH',1,10002)).packet(16,main_events()).packet(2,events()).packet(2,events()).finish()

# Malformed decode must not modify state or emit intent.
for sub,data in [(1,snapshot()),(2,events()),(3,pack('BBBBH',1,1,1,0,60)),(11,qpacket()),(12,b'\1\2'),(15,fight()),(16,main_events())]:
 s=Scenario('malformed_'+str(sub),seed=populated(pending=pending()))
 for size in range(len(data)):s.packet(sub,data[:size])
 s.packet(sub,data+b'x').packet(sub,data).finish()

for n in range(55):
 s=Scenario('mixed_'+str(n),seed=populated(pending=pending(RNG.choice(['dispatch','question','fight','future'])),uncertain=bool(n%2)))
 operations=[(1,snapshot()),(2,events()),(3,pack('BBBBH',1,1,1,0,60)),(5,b'\1\1'),(6,b'\2\2\5'),(7,b'\3\4'),
             (10,pack('BH',1,123)),(11,qpacket()),(12,b'\0\2'),(15,fight()),(16,main_events()),(17,pack('BH',21,10000)),
             (18,pack('BHB',1,10004,4)),(19,pack('Bh',1,4)),(0,b'\5'),(255,b'synthetic')]
 for _ in range(40):
  sub,data=RNG.choice(operations);s.packet(sub,data)
 s.finish()

sources=['wlre/services/star_ark.py','wlre/storage/ark_questions.py','wlre/services/ark_candidates.py',
         'wlre/services/ark_candidate_data.py','wlre/services/ark_first_answer.py','wlre/network/wire.py']
hashes={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sources}
out=Path(__file__).parent
header=['// Generated by generate_ark_receive_vectors.py. Synthetic offline retained-Python oracle.',
        'namespace Lala.Core.Tests.Social.Ark;','public static partial class ArkReceivePythonVectors','{',
        '    public const string SourceSha256 = '+json.dumps(json.dumps(hashes,separators=(',',':')))+';',
        '    public static IEnumerable<object[]> Sequences()','    {']
chunks=[SCENARIOS[i:i+35] for i in range(0,len(SCENARIOS),35)]
for i in range(len(chunks)):header+=['        foreach (var row in Part'+str(i+1)+'()) yield return row;']
header+=['    }','}']
(out/'ArkReceivePythonVectors.cs').write_text('\n'.join(header)+'\n',encoding='utf-8')
for i,chunk in enumerate(chunks):
 payload=json.dumps(chunk,ensure_ascii=False,separators=(',',':'),allow_nan=False)
 code='\n'.join(['// Generated deterministic gzip fixture.','namespace Lala.Core.Tests.Social.Ark;',
       'public static partial class ArkReceivePythonVectors','{',f'    private static IEnumerable<object[]> Part{i+1}()',
       '    {','        using var document = System.Text.Json.JsonDocument.Parse('+csharp_gzip_json(payload)+');',
       '        foreach (var row in document.RootElement.EnumerateArray())',
       '            yield return new object[] { row.GetProperty("name").GetString()!, row.GetRawText() };','    }','}'])+'\n'
 path=out/f'ArkReceivePythonVectors.Part{i+1:02}.cs';path.write_text(code,encoding='utf-8');assert path.stat().st_size<500_000
print(f'{len(SCENARIOS)} sequences; {sum(len(s["steps"])+1 for s in SCENARIOS)} snapshots; {len(chunks)} parts; '+
      str(sum(len(step['intents']) for s in SCENARIOS for step in s['steps']))+' memory intents')
