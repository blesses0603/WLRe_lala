"""Offline synthetic Python command and health parity; never reads credentials or live traffic."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from wlre.network.command_envelope import validate_command,rejected_command_type
from wlre.network.connection_health import ConnectionHealth

def cs(v):
    if v is None:return 'null'
    if isinstance(v,bool):return str(v).lower()
    if isinstance(v,str):return json.dumps(v,ensure_ascii=False)
    return str(v)
values=[None,42,False,'', 'walk','start_auto_battle','_', '__','_x_', '0', 'a'*64,'a'*65,'技能', '😀'*64,'😀'*65,'a b','a\nb','secret:login=dummy','x\0y','１２','Ω','é']
lines=['// Generated from retained Python command_envelope and connection_health; synthetic only.',
'namespace Lala.Core.Tests.Diagnostics;', 'public static class PythonDiagnosticVectors','{',
'    public static IEnumerable<object?[]> CommandCases()','    {']
for value in values:
    command={'type':value,'password':'synthetic-never-log'}
    try:expected=validate_command(command);error=None
    except Exception as ex:expected=None;error=str(ex)
    lines.append('        yield return new object?[] { '+', '.join(map(cs,[value,expected,error,rejected_command_type(command)]))+' };')
lines+=['    }','    public static IEnumerable<object?[]> HealthSequence()','    {']
class Clock:
    now=100.0
    wall=1700000000.0
clock=Clock(); events=[]
h=ConnectionHealth(events.append,clock=lambda:clock.now,wall=lambda:clock.wall,quiet_after=120,interval=1)
ops=[('publish',0,False),('publish',0.5,False),('receive',0.5,False),('publish',0.5,True),('publish',1.0,False),('publish',1.5,False),('publish',120.5,False),('receive',121,False),('publish',121,True),('wall_back',122,False),('publish',122,False),('publish',43201,False),('receive',43202,False),('publish',43202,True),('close',43202,False),('receive',43203,False),('publish',43203,False)]
for op,t,force in ops:
    clock.now=100+t; before=len(events)
    if op=='wall_back':clock.wall-=86400
    elif op=='receive':h.received()
    elif op=='publish':h.publish(force=force)
    elif op=='close':h.close('server_closed')
    e=events[-1] if len(events)>before else None
    vals=[op,t,force,None if e is None else e['status'],None if e is None else e['age'],None if e is None else e['last_received_at'],None if e is None else e['packets'],h.closed]
    lines.append('        yield return new object?[] { '+', '.join(cs(v) if not isinstance(v,float) else repr(v)+'d' for v in vals)+' };')
lines+=['    }','}']
Path(__file__).with_name('PythonDiagnosticVectors.cs').write_text('\n'.join(lines)+'\n')
