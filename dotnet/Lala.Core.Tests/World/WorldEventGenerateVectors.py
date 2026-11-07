import base64, gzip
"""Retained Python world reducer/helper parity; synthetic offline data only.

The current-runtime lookup and alias-verification result are injected for obstacle_scope.
No runtime is activated, catalog fetched, files synchronized or live packet sent.
"""
import json
import os
from pathlib import Path
import random
import struct
import sys
from types import SimpleNamespace
from unittest.mock import patch

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from wlre.core.state import State
from wlre.core.state_world_events import apply_world_event
from wlre.network.protocol import decode
from wlre.network.wire import Packet
from wlre.services.world.obstacle_scope import affects_navigation, house_scene

FIELDS = ('phase', 'packet_count', 'player', 'positions', 'navigation', 'location',
          'local_movement', 'movement_check')
def project(state):
    snapshot = state.snapshot()
    result = {key:snapshot[key] for key in FIELDS}
    result['positions'] = [dict(role_id=int(role), x=value[0], y=value[1])
                           for role,value in result['positions'].items()]
    if not result['player']:result['player'] = None
    context = result['navigation'].get('house_context')
    if context is not None:context.setdefault('sizes', {})
    return result

def p(fmt, *values):return struct.pack('<' + fmt, *values)
def world(role=17, scene=101, x=8, y=9):
    name='合成角色'.encode('utf-16-le')
    return (p('IBHHHBBB IIBB', role,1,scene,x,y,2,3,4,5,6,7,1)
            + p('BHI',1,8,9) + bytes([len(name)]) + name + bytes(9) + p('H',10))
def player(role=17,scene=101,x=8,y=9):return decode(Packet(3,1,world(role,scene,x,y)))['player']
def target(scene=101,x=50,y=60,**more):return dict(scene=scene,x=x,y=y,**more)

def scoped(catalog, callback):
    runtime = None if catalog is None else SimpleNamespace(stages=dict.fromkeys(catalog['stage_ids']))
    aliases = None if catalog is None else catalog.get('verified_instance_alias_ids')
    with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime', return_value=runtime), \
         patch('wlre.services.world.house_navigation.instance_aliases',
               side_effect=ValueError('synthetic unverified alias order') if aliases is None else None,
               return_value=dict.fromkeys(aliases or [])):
        return callback()

vectors=[]
class Scenario:
    def __init__(self,name,catalog=None,**initial):
        self.state=State(**initial);self.catalog=catalog
        self.value=dict(name=name,catalog=catalog,initial=project(self.state),steps=[])
        vectors.append(self.value)
    def step(self,operation,**args):
        step=dict(operation=operation,**args)
        if operation=='packet':
            self.state.packet_count+=1
            event=decode(Packet(args['main'],args['sub'],bytes.fromhex(args['hex'])))
            scoped(self.catalog,lambda:apply_world_event(self.state,event,affects_navigation))
        elif operation=='event':
            self.state.packet_count+=1
            scoped(self.catalog,lambda:apply_world_event(self.state,args['event'],affects_navigation))
        elif operation=='remote_walk_range':
            for role in range(args['start'],args['start']+args['count']):
                self.state.packet_count+=1
                apply_world_event(self.state,dict(type='walk',role_id=role,x=role%65536,y=1),affects_navigation)
        elif operation=='remember':self.state.remember_position(args['role_id'],args['x'],args['y'])
        elif operation=='clear':step['removed']=self.state.clear_position_history()
        elif operation=='wait':self.state.wait_for_position()
        elif operation=='confirm':self.state.confirm_location(args['scene'],args['x'],args['y'],args['source'])
        else:raise AssertionError(operation)
        step['expected']=project(self.state);self.value['steps'].append(step);return self
    def packet(self,main,sub,payload=b''):return self.step('packet',main=main,sub=sub,hex=payload.hex().upper())
    def event(self,kind,**data):return self.step('event',event=dict(type=kind,**data))
    def move(self,x=50,y=60):return self.event('movement_request',x=x,y=y)
    def walk(self,role=17,x=50,y=60):return self.packet(6,1,p('iHH',role,x,y))
    def position(self,role=17,scene=101,x=50,y=60,tail=b'',main=12):
        return self.packet(main,1,p('IHHH',role,scene,x,y)+tail)

s=Scenario('authority_requests_corrections_and_scene_resets',packet_count=2**90)
s.packet(3,1,world()).walk(18,30,40).move().walk(x=70,y=80)
s.position(18,999,50,60).position(x=49,y=59).position().position(x=99,y=99)
s.move(80,90).position(scene=102).position().packet(1,1,p('I',17))
s.walk(18).packet(1,1,p('I',18)).packet(1,1,p('I',18))
s.packet(3,1,world(18,103,10,20)).packet(1,23).packet(255,255)

for status in ('running','finished','cancelled','blocked','idle'):
    s=Scenario('local_target_precedence_'+status,player=player(),
               local_movement=dict(status=status,target=target(x=12,y=13)))
    s.walk(x=90,y=91).move(50,60).position(x=50,y=60).position(x=12,y=13)
for requested in (False,True):
    for server in (False,True):
        s=Scenario(f'wait_target_precedence_{requested}_{server}',player=player(),
                   location=dict(confirmed=None,confirmed_is_current=False,
                       requested_destination=target(x=1,y=2,source='C6-1',packet_number=3) if requested else None,
                       server_destination=target(x=3,y=4,source='S6-1',packet_number=4) if server else None),
                   movement_check=dict(status='matched',target=target(),role_id=17,confirmation=None))
        s.step('wait').step('confirm',scene=101,x=1,y=2,source='fixture')

for status in ('waiting','different_position','matched','scene_changed','cancelled'):
    for role in (None,17,18):
        s=Scenario(f'confirmation_status_identity_{status}_{role}',player=player(),
                   movement_check=dict(status=status,target=target(),role_id=role,confirmation=None))
        s.step('confirm',scene=101,x=49,y=59,source='fixture')
        s.step('confirm',scene=101,x=50,y=60,source='fixture')
        s.step('confirm',scene=102,x=50,y=60,source='fixture')

s=Scenario('before_identity_never_confirms_another_role')
s.move().walk(17).position().packet(3,1,world()).step('wait')
s=Scenario('identity_replacement_does_not_resolve_old_check',player=player())
s.move().packet(3,1,world(18,101,50,60)).position(18).packet(3,1,world())
s=Scenario('signed_walk_ids_never_alias_unsigned_identity',player=player(2**32-1))
s.walk(-1).walk(-2**31).position(2**32-1).packet(1,1,p('I',2**32-1))

for scene in (0,10000,10298,10299,63499,63500,63501,63502,65500,65501,65535):
    s=Scenario(f'house_context_boundaries_{scene}',player=player())
    s.position(scene=scene,tail=b'\0\0\0\2\0')
    s.position(scene=scene,tail=b'\0\0\1\3\1',main=7)
    s.position(scene=scene,tail=b'\0').position(scene=scene,tail=b'\1')
    s.packet(62,64).position(18,63502,tail=b'\0\0\3\1\3')
    s.position(scene=scene,tail=bytes(6)).position(scene=scene,tail=b'\1')
s=Scenario('house_sizes_do_not_cross_scenes_or_unverified_contexts',player=player())
s.position(scene=63501,tail=b'\0\0\0\2\0').position(scene=63501,tail=b'\0\0\1\3\1')
s.position(scene=63502,tail=b'\0').position(scene=63501,tail=b'\1')
s.position(scene=63501,tail=b'\0\0\0\1\0').packet(3,1,world(scene=63501))
s.position(scene=63501,tail=b'\0').position(scene=101)

for catalog_name,catalog in [('none',None),('known',dict(stage_ids=[101],verified_instance_alias_ids=[])),
      ('alias',dict(stage_ids=[],verified_instance_alias_ids=[61501])),
      ('unverified_alias',dict(stage_ids=[],verified_instance_alias_ids=None))]:
    for scene in (101,10299,63501,61501,61502):
        s=Scenario(f'geometry_{catalog_name}_{scene}',catalog=catalog,player=player(scene=scene),
                   navigation=dict(scene=scene,revision=2**80,stale=False,runtime_geometry_verified=True,reasons=[]))
        for i in range(14):s.event('navigation_geometry_change',reason=f'change_{i}',geometry_scope='house',affects_geometry=True)
        s.event('navigation_geometry_change',reason='non_geometry',geometry_scope='house',affects_geometry=False)
        s.position(scene=scene).position(scene=102).packet(3,1,world(scene=scene))

s=Scenario('cache_order_eviction_protected_local',player=player(1),positions={'1':[8,9]})
s.step('remote_walk_range',start=2,count=2047)
s.step('remote_walk_range',start=2049,count=1)
s.step('remember',role_id=2,x=4,y=5).step('remember',role_id=2049,x=6,y=7)
s.step('remote_walk_range',start=2050,count=4097).step('clear').step('clear')
s.walk(2).position(1,102).walk(3).packet(3,1,world(4))
s=Scenario('cache_without_known_identity')
s.step('remote_walk_range',start=1,count=2051).step('remember',role_id=-1,x=0,y=0).step('clear')

rng=random.Random(20261107)
for i in range(6):
    s=Scenario(f'mixed_world_replay_{i}',player=player())
    for _ in range(60):
        kind=rng.randrange(7);role=rng.choice([17,18,19]);scene=rng.choice([101,102,63501,63502])
        x,y=rng.randrange(65536),rng.randrange(65536)
        if kind==0:s.walk(role,x,y)
        elif kind==1:s.position(role,scene,x,y,tail=rng.choice([b'',b'\0',b'\0\0\1\2\1']))
        elif kind==2:s.move(x,y)
        elif kind==3:s.packet(62,64)
        elif kind==4:s.packet(1,1,p('I',role))
        elif kind==5:s.packet(3,1,world(role,scene,x,y))
        else:s.step('clear')

scopes=[]
for catalog in (None,dict(stage_ids=[101,10299,61502],verified_instance_alias_ids=[61501]),
                dict(stage_ids=[101],verified_instance_alias_ids=None)):
    for scene in (None,0,101,10000,10298,10299,61500,61501,61502,62000,62001,63500,63501,65500,65501,65535):
        for geometry_scope in (None,'house','world'):
            for affects in (False,True):
                event=dict(geometry_scope=geometry_scope,affects_geometry=affects)
                result=scoped(catalog,lambda:dict(house=house_scene(scene),affects=affects_navigation(event,scene)))
                scopes.append(dict(catalog=catalog,scene=scene,geometry_scope=geometry_scope,
                                   affects_geometry=affects,expected=result))

lines=['// Generated by WorldEventGenerateVectors.py from retained Python. Offline synthetic evidence only.',
       'namespace Lala.Core.Tests.World;', 'public static class WorldEventPythonVectors', '{']
for method,values in [('Sequences',vectors),('Scopes',scopes)]:
    lines+=['    public static IEnumerable<object[]> '+method+'()', '    {']
    for i,value in enumerate(values):
        payload=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        lines.append('        yield return new object[] { '+json.dumps(value.get('name',f'scope_{i}'))+', '+'Decode(' + json.dumps(base64.b64encode(gzip.compress(payload.encode("utf-8"),mtime=0)).decode("ascii")) + ') };')
    lines+=['    }']
lines += ['    private static string Decode(string encoded)', '    {', '        using var input = new System.IO.MemoryStream(System.Convert.FromBase64String(encoded));', '        using var gzip = new System.IO.Compression.GZipStream(input, System.IO.Compression.CompressionMode.Decompress);', '        using var reader = new System.IO.StreamReader(gzip, System.Text.Encoding.UTF8);', '        return reader.ReadToEnd();', '    }', '}']
Path(__file__).with_name('WorldEventPythonVectors.cs').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(f'Generated {len(vectors)} sequences, {sum(len(v["steps"]) for v in vectors)} checkpoints, {len(scopes)} scope cases.')
