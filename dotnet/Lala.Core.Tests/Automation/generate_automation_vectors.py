"""Retained-Python synthetic decoder and lifecycle oracles. No accounts, traffic or runtime downloads.

Run from any directory. Holds use the pending-only service_scheduler boundary; explicit cube
requests include commands.py's world acknowledgement gate. Catalogs are synthetic caller inputs.
"""
import copy
import json
from pathlib import Path
import random
import struct
import sys
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'TestSupport'))
from gzip_json_fixture import csharp_gzip_json
from wlre.network.wire import Packet, ProtocolError
from wlre.network.resource_safety import command_allowed
from wlre.services import time_cube as cube, daily_tasks as daily


def packet(main, sub, body): return dict(op='packet', main=main, sub=sub, hex=body.hex())
def info(count=1, kind=0, check=180, keep=1): return packet(122,1,struct.pack('<BBHH',kind,count,check,keep))
def snapshot(progress=1, day=0, week=0, dv=50, wv=100, event=1):
    return packet(124,1,bytes([dv,wv]+[progress]*20+[day,0,0,0,week&255,week>>8,0,0,0,event,0]))
def marks(day=0, week=0, chest=0, event=0, dv=50, wv=100):
    return packet(124,3,bytes([1,dv,wv,day,chest,event,0,week&255,week>>8,0,0,0]))
def notice(kind=1): return packet(124,4,bytes([kind])+(bytes(9) if kind==2 else b''))
def tick(t): return dict(op='tick', now=t)
def bag(items=(), revision=2, **kw): return dict(op='bag',items=[dict(index=i+1,item_id=s,count=n) for i,(s,n) in enumerate(items)],revision=revision,**kw)
def context(**kw): return dict(op='context', **kw)
def auto(enabled): return dict(op='auto',enabled=enabled)
def request(action='claim_ready',**kw): return dict(op='request',action=action,now=1,**kw)
def catalog(variant='base'):
    a=[dict(kind=12,id=1,value=10)]
    if variant=='items': a=[dict(kind=10,id=100,value=2),dict(kind=11,id=100,value=1),dict(kind=10,id=200,value=1)]
    elif variant=='unknown': a=[dict(kind=99,id=1,value=1)]
    elif variant=='empty': a=[]
    elif variant=='zero': a=[dict(kind=10,id=100,value=0)]
    row=dict(index=200,group=1,id=1,name='synthetic',cycle=1,goal=1,condition_kind=1,condition_params=[1,0,0],awards=a)
    weekly={**row,'index':900,'group':2,'id':9,'cycle':2,'awards':[dict(kind=12,id=1,value=10)]}
    reward=dict(id=1,kind=1,value=20,mark=1,awards=[dict(kind=2,id=0,value=10)])
    return dict(tasks=[row,weekly],rewards=[reward,{**reward,'id':2,'kind':2,'mark':2}])

def initial():
    names=['star_ark','guild_actions','room_storage','maintenance','expedition','alchemy','crafting']
    s=SimpleNamespace(**{k:{} for k in names}, phase='world_ready', initial_data_complete=True,
        player={'role_id':1}, automation={'enabled':True}, battle={},event_flow={},battle_count=0,activities=[],instances={},
        inventory=dict(ready=True,reliable=True,capacity=10,revision=1,items={}),time_cube=cube.defaults(),daily_tasks=daily.defaults())
    cube.apply_cube(s,dict(type='world_player',player={'role_id':1}),0)
    daily.apply_daily_tasks(s,dict(type='world_player',player={'role_id':1}))
    return s

def project(s, service):
    d=copy.deepcopy(getattr(s,service))
    if service=='daily_tasks':
        d['handled']=len(d['handled'])
        d['rows']=[dict(cycle=r['cycle'],index=r['index'],id=r['id'],progress=r['progress'],received=r['received'],eligible=r['eligible']) for r in d['rows']]
        d['chests']=[dict(cycle=r['cycle'],kind=r['kind'],mark=r['mark'],value=r['value'],received=r['received'],eligible=r['eligible']) for r in d['chests']]
    else:
        d.setdefault('item_id',None);d.setdefault('check_minutes',None)
    return d

scenarios=[]
def seq(name,service,ops,variant='base'):
    s=initial();ack=True;held=False;token='synthetic-A';cat=catalog(variant);available=True
    daily.runtime_catalog=lambda:(cat if available else None,token,'catalog unavailable')
    steps=[]
    for source in ops:
        op=copy.deepcopy(source); packets=[];error=False
        try:
            kind=op['op'];mod=cube if service=='time_cube' else daily
            if kind=='packet':
                p=Packet(op['main'],op['sub'],bytes.fromhex(op['hex']))
                event=(cube.decode_cube(p) if service=='time_cube' else daily.decode_daily_tasks(p))
                if event:
                    if service=='time_cube':cube.apply_cube(s,event,op.get('now',0))
                    else:daily.apply_daily_tasks(s,event)
            elif kind=='tick':
                if not held or getattr(s,service)['pending']:
                    packets=mod.tick(s,ack and not held,op['now'])
            elif kind=='request':
                if held:raise ProtocolError('held')
                if service=='time_cube':
                    if not ack:raise ProtocolError('world acknowledgement')
                    packets=cube.command(s,op,op['now'])
                else:packets=daily.command(s,op,ack,op['now'])
            elif kind=='auto':
                command=dict(type=service,action='auto',enabled=op['enabled'])
                if held and not command_allowed(command):raise ProtocolError('held')
                if service=='time_cube':packets=cube.command(s,command,0)
                else:packets=daily.command(s,command,ack,0)
            elif kind=='bag':
                for k,v in op.items():
                    if k=='op':continue
                    if k=='items':s.inventory[k]={str(i['index']):dict(item_id=i['item_id'],count=i['count']) for i in v}
                    elif k=='held':s.inventory['holds']={'test':1} if v else {}
                    elif k=='reserved':s.inventory['reserved']={'1':1} if v else {}
                    elif k=='supply':s.inventory['field_supply']={'pending':v}
                    else:s.inventory[k]=v
            elif kind=='context':
                for k,v in op.items():
                    if k=='op':continue
                    if k=='ack':ack=v
                    elif k=='held':held=v
                    elif k=='world':s.phase='world_ready' if v else 'disconnected'
                    elif k=='initial':s.initial_data_complete=v
                    elif k=='role':s.player['role_id']=v
                    elif k=='auto':s.automation['enabled']=v
                    elif k=='battle':s.battle['active']=v
                    elif k=='event':s.event_flow['blocked']=v
                    elif k=='post':s.battle_count=int(v);s.battle['post_event']={'status':'pending' if v else 'completed'}
                    elif k=='activities':s.activities=['test'] if v else []
                    elif k=='supply':s.inventory['field_supply']={'uncertain':v}
                    elif k=='instance':s.instances={'1':{'claim_pending':{} if v else None}}
                    else:setattr(s,k,v)
            elif kind=='catalog':token=op.get('token',token);available=op.get('available',available)
            elif kind=='role':
                s.player['role_id']=op['role'];event=dict(type='world_player',player=s.player)
                if service=='time_cube':cube.apply_cube(s,event,0)
                else:daily.apply_daily_tasks(s,event)
            elif kind=='role_list':
                if service=='time_cube':cube.apply_cube(s,dict(type='role_list_available'),0)
                else:daily.apply_daily_tasks(s,dict(type='role_list_available'))
            elif kind=='disconnect':mod.disconnect(s)
        except ProtocolError:error=True
        steps.append(dict(input=op,error=error,packets=[bytes([p.main,p.sub])+p.payload for p in packets],state=project(s,service)))
    for step in steps:step['packets']=[p.hex() for p in step['packets']]
    scenarios.append(dict(name=name,service=service,variant=variant,steps=steps))

ready=[snapshot(),packet(124,2,b'\x01\x02'),auto(False),tick(0),auto(True)]
for first in ('bag','count'):
    a,b=(bag(),info(0)) if first=='bag' else (info(0),bag())
    seq('cube receipt '+first,'time_cube',[info(),request('open'),a,tick(2),b,tick(3),tick(4)])
seq('cube late duplicate timeout','time_cube',[info(),request('open'),info(),packet(122,2,b'legacy'),tick(2),request('open'),tick(16),info(0),bag(),auto(False),auto(True),info(),tick(50),request('open')])
seq('cube countdown metadata','time_cube',[info(0,check=1,keep=2),packet(122,3,b'\x34\x12'),tick(10**12),request('open'),info(2,1,0,0),tick(2)])
seq('cube cancel pending','time_cube',[info(),tick(1),auto(False),info(0),bag(),tick(2),auto(True),tick(3)])
seq('cube disconnect role','time_cube',[info(),tick(1),dict(op='disconnect'),info(),tick(30),dict(op='role',role=2),info(),tick(31),dict(op='role_list'),tick(32)])
seq('cube held pending receipt','time_cube',[info(),tick(1),context(held=True),auto(False),auto(True),request('open'),info(0),bag(),tick(30),tick(31)])
seq('cube held pending timeout','time_cube',[info(),tick(1),context(held=True,ack=False,auto=False),tick(16),info(),bag(),tick(17)])
for key in ('world','initial','ack','auto','battle','event','post','activities','supply','instance'):
    blocked=key not in ('world','initial','ack','auto')
    seq('cube guard '+key,'time_cube',[info(),context(**{key:blocked}),tick(1),request('open'),context(**{key:not blocked}),tick(2)])
for key in ('star_ark','guild_actions','daily_tasks','room_storage','maintenance','crafting','alchemy','expedition'):
    # Preserve actual service dictionaries when toggling the other task service.
    if key=='daily_tasks':continue
    seq('cube service '+key,'time_cube',[info(),context(**{key:{'pending':{'test':1}}}),tick(1),context(**{key:{}}),tick(2)])
for patch in [dict(ready=False),dict(reliable=False),dict(capacity=0),dict(capacity=1),dict(held=True),dict(reserved=True),dict(supply=True)]:
    seq('cube bag '+str(patch),'time_cube',[info(3),dict(op='bag',**patch),tick(1),request('open')])
for first in ('notice','marks'):
    a,b=(notice(),marks(day=1)) if first=='notice' else (marks(day=1),notice())
    seq('daily receipts '+first,'daily_tasks',ready+[tick(1),a,tick(2),b,tick(3),tick(4)])
seq('daily chest all flags','daily_tasks',ready+[marks(day=1,week=256),tick(1),notice(2),marks(day=1,week=256,chest=1),tick(2),marks(day=1,week=256,chest=1,event=2),tick(3),tick(4)])
seq('daily item deltas','daily_tasks',ready+[bag([(100,5)],1),tick(1),notice(),marks(day=1),bag([(100,7),(200,1)]),tick(2),bag([(100,7),(200,1)]),tick(2),bag([(100,8)]),tick(2),bag([(100,3),(100,5),(200,1)],3,reliable=False),tick(2),dict(op='bag',reliable=True),tick(3)],'items')
seq('daily unrelated receipt timeout','daily_tasks',ready+[tick(1),notice(2),marks(day=2),bag([(999,4)]),tick(2),notice(),marks(day=3),tick(21),bag([(100,3),(200,1)],3),auto(False),auto(True),tick(50)],'items')
seq('daily duplicate timeout','daily_tasks',ready+[tick(1),notice(),notice(),tick(2),request(),tick(21),marks(day=1),notice(),auto(False),auto(True),tick(50),request('task',index=900)])
seq('daily stop pending','daily_tasks',ready+[tick(1),auto(False),notice(),marks(day=1),tick(21),tick(22)])
seq('daily held pending receipt','daily_tasks',ready+[tick(1),context(held=True),auto(False),auto(True),request(),notice(),marks(day=1),tick(21),tick(22)])
seq('daily held pending timeout','daily_tasks',ready+[tick(1),context(held=True,ack=False,auto=False),tick(21),notice(),marks(day=1),tick(22)])
seq('daily server error handled','daily_tasks',ready+[tick(1),packet(124,5,b'\x0f'),tick(2),auto(True),request('task',index=200),tick(3)])
for trigger in [packet(124,2,b'\x03\x02'),snapshot(),marks(dv=0),packet(124,3,b'\x02\x00\x01\x01'),packet(124,3,b'\xffanything'),dict(op='catalog',token='synthetic-B'),context(role=2)]:
    seq('daily epoch '+str(trigger),'daily_tasks',ready+[tick(1),trigger,tick(2),snapshot(),packet(124,2,b'\x01\x02'),notice(),marks(day=1),tick(30)])
for first in ('snapshot','groups'):
    a,b=(snapshot(),packet(124,2,b'\x01\x02')) if first=='snapshot' else (packet(124,2,b'\x01\x02'),snapshot())
    seq('daily reset '+first,'daily_tasks',ready+[auto(False),marks(day=1,week=256),a,auto(True),tick(1),b,tick(2)])
seq('daily disconnect role','daily_tasks',ready+[tick(1),dict(op='disconnect'),notice(),marks(day=1),tick(30),dict(op='role',role=2),dict(op='role_list')])
seq('daily catalog availability','daily_tasks',ready+[dict(op='catalog',available=False),tick(1),request(),dict(op='catalog',available=True,token='synthetic-B'),tick(2),request()])
for variant in ('unknown','empty','zero'):
    seq('daily bad awards '+variant,'daily_tasks',ready+[request('task',index=200),tick(1)],variant)
for key in ('world','initial','ack','auto','battle','event','post','activities','supply','instance'):
    blocked=key not in ('world','initial','ack','auto')
    seq('daily guard '+key,'daily_tasks',ready+[context(**{key:blocked}),tick(1),request('task',index=200),context(**{key:not blocked}),tick(2)])
for key in ('star_ark','guild_actions','room_storage','maintenance','crafting','alchemy','expedition'):
    seq('daily service '+key,'daily_tasks',ready+[context(**{key:{'checking':True,'enabled':True}}),tick(1),request('task',index=200),context(**{key:{}}),tick(2)])
seq('daily explicit commands','daily_tasks',ready+[request('task',index=999),request('task',index=-1),request('chest',cycle=0),request('chest',cycle=2),request('task',index=900),notice(),marks(week=256),tick(3)])

# Strict decoder oracles: every prefix/trailer of fixed layouts plus semantic invalids, opaque forms and deterministic random payloads.
wire=[]
def decode_case(main,sub,body):
    try:
        e=cube.decode_cube(Packet(main,sub,body)) if main==122 else daily.decode_daily_tasks(Packet(main,sub,body));error=False
    except ProtocolError:e=None;error=True
    wire.append(dict(case=len(wire),main=main,sub=sub,hex=body.hex(),error=error,event=e))
valid=[info(),info(3,1,65535,65535),packet(122,3,b'\x01\x00'),snapshot(),packet(124,2,b'\x01\xff'),marks(255,65535),packet(124,3,b'\x02\xff\x0c\x02'),notice(1),notice(2),packet(124,5,b'\xff')]
for v in valid:
    body=bytes.fromhex(v['hex'])
    for n in range(len(body)+1):decode_case(v['main'],v['sub'],body[:n])
    decode_case(v['main'],v['sub'],body+b'\0')
for v in [info(4),info(1,2),packet(122,3,b'\0\0'),snapshot(event=2),packet(124,3,b'\x02\x01\x09\x01'),packet(124,3,b'\x02\x01\x00\x02'),packet(124,3,b'\x02\x01\x01\x03')]:decode_case(v['main'],v['sub'],bytes.fromhex(v['hex']))
for kind in (0,1,2,3,255):
    for n in (0,1,8,9,10,18,27):decode_case(124,4,bytes([kind])+bytes(range(n)))
for n in (0,1,32,255):decode_case(122,2,bytes(n));decode_case(124,3,b'\xff'+bytes(n))
for sub in (0,6,255):decode_case(122,sub,b'noise');decode_case(124,sub,b'noise')
rng=random.Random(124122)
for _ in range(80):decode_case(rng.choice([122,124]),rng.randint(1,5),rng.randbytes(rng.randint(0,40)))
output=Path(__file__).with_name('PythonAutomationVectors.cs')
payload = json.dumps(dict(wire=wire,sequences=scenarios),ensure_ascii=False,separators=(',',':'))
output.write_text('// Generated by generate_automation_vectors.py; synthetic and offline only.\n'
                  '// Deterministic gzip bytes preserve the JSON without using the assembly string heap.\n'
                  'namespace Lala.Core.Tests.Automation;\ninternal static class PythonAutomationVectors\n{\n'
                  '    internal static readonly string Json = ' + csharp_gzip_json(payload) + ';\n}\n', encoding='utf-8')
print(f'{len(wire)} decoder cases; {len(scenarios)} sequences; {sum(len(s["steps"]) for s in scenarios)} state transitions')
