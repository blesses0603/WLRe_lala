"""Execute pinned MoveController.Update in host Lua with an explicit identity collision stub.

No Unity physics, native vectors, runtime sender/FPS or observed vectorPath is claimed.
The same four-point Bangkok corridor is a supplied test input, not a captured path.
"""
import argparse
import ctypes
import ctypes.util
import hashlib
import json
from pathlib import Path
from tools.review_navigation_player_points import SOURCE_SHA
from tools.review_navigation_corner_following import OBSERVATIONS, distance_to_polyline, follow

POINTS=((4836,5154),(3680,3980),(3010,3870),(1850,4915))


def oracle(path):
    path=Path(path)
    if path.stat().st_size>128*1024:raise ValueError('Lua source size limit')
    source=path.read_bytes()
    if len(source)>128*1024 or hashlib.sha256(source).hexdigest()!=SOURCE_SHA:
        raise ValueError('Unverified MoveController source')
    library=ctypes.util.find_library('lua5.4')
    if not library:raise ImportError('Host Lua 5.4 unavailable')
    lua=ctypes.CDLL(library);P=ctypes.c_void_p
    for name,args,result in [('luaL_newstate',[],P),('luaL_openlibs',[P],None),('lua_close',[P],None),
        ('luaL_loadbufferx',[P,ctypes.c_char_p,ctypes.c_size_t,ctypes.c_char_p,ctypes.c_char_p],ctypes.c_int),
        ('lua_pcallk',[P,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_longlong,P],ctypes.c_int),
        ('lua_tolstring',[P,ctypes.c_int,ctypes.POINTER(ctypes.c_size_t)],P)]:
        fn=getattr(lua,name);fn.argtypes=args;fn.restype=result
    def run(fps,sender):
        if fps not in (30,60,120) or sender not in (1,3,6):raise ValueError('Unreviewed motion profile')
        prefix=b'''
debug.sethook(function() error("Instruction budget") end,"",5000000)
os=nil;io=nil;package=nil;dofile=nil;loadfile=nil
require=function(n) assert(n=="bit");return {} end
Mathf={};EMoveSender={None=0,Player=1,Server=3,AutoWalk=6};CGLayer={SkyTraffic=8}
table.Count=function(t) return #t end
Vector3={}
setmetatable(Vector3,{__index=function(t,k) if k=="zero" then return {x=0,y=0,z=0} end end})
function Vector3.CopyVecValue(a,b) a.x=b.x;a.y=b.y;a.z=b.z;return a end
function Vector3.Add(a,b) a.x=a.x+b.x;a.y=a.y+b.y;a.z=a.z+b.z;return a end
function Vector3.Sub(a,b) a.x=a.x-b.x;a.y=a.y-b.y;a.z=a.z-b.z;return a end
function Vector3.Mul(a,n) a.x=a.x*n;a.y=a.y*n;a.z=a.z*n;return a end
function Vector3.SqrMagnitude(a) return a.x*a.x+a.y*a.y+a.z*a.z end
function Vector3.SqrDistance2D(a,b) return (a.x-b.x)^2+(a.z-b.z)^2 end
function Vector3.Reset(a) a.x=0;a.y=0;a.z=0 end
function Vector3.SetNormalize(a) local d=math.sqrt(Vector3.SqrMagnitude(a));assert(d>0);return Vector3.Mul(a,1/d) end
function Vector3.GetTransformPosition(a,t) return Vector3.CopyVecValue(a,t.position) end
function Vector3.GetTransformLocalPosition(a,t) return Vector3.CopyVecValue(a,t.localPosition) end
function IsZeroVector3(a) return a.x==0 and a.y==0 and a.z==0 end
'''
        suffix=('''
CGTimer={deltaTime=1/'''+str(fps)+'''}
local position={x=48.36,y=10,z=8.46}
local transform={position=position,localPosition=position}
local calls=0;local done=0
local owner=setmetatable({transform=transform,useWorldPosition=false,
    currentPath={{x=36.8,y=10,z=20.2},{x=30.1,y=10,z=21.3},{x=18.5,y=10,z=10.85}},
    moveSender='''+str(sender)+''',moveDirection=Vector3.zero,verticalSpeed=0,GravityEnable=true,
    roleController={gameObject={layer=0},OnMoveDone=function() done=done+1 end}},MoveController)
owner.characterController={isGrounded=true,transform=transform,
 Move=function(self,delta)
   calls=calls+1
   -- Explicit identity collision stub: requested displacement is always applied.
   Vector3.Add(position,delta)
 end}
owner:SetDefaultSpeed(3.5)
local rows={string.format("[%.17g,%.17g]",position.x*100,6000-position.z*100)}
for frame=1,'''+str(20*fps)+''' do
 if owner.currentPath==nil then break end
 owner:Update(true,false)
 rows[#rows+1]=string.format("[%.17g,%.17g]",position.x*100,6000-position.z*100)
end
assert(owner.currentPath==nil and done==1 and calls>0)
return '{"collision_stub_calls":'..calls..',"done_callbacks":'..done..',"trace":['..table.concat(rows,",")..']}'
''').encode()
        program=prefix+source+suffix;state=lua.luaL_newstate()
        if not state:raise ValueError('Host Lua state unavailable')
        try:
            lua.luaL_openlibs(state)
            status=lua.luaL_loadbufferx(state,program,len(program),b'@pinned-motion-case',b't')
            if status==0:status=lua.lua_pcallk(state,0,1,0,0,None)
            size=ctypes.c_size_t();ptr=lua.lua_tolstring(state,-1,ctypes.byref(size))
            if not ptr or size.value>512*1024:raise ValueError('Invalid bounded host output')
            text=ctypes.string_at(ptr,size.value).decode()
            if status:raise ValueError('Host Lua failure: '+text)
            return json.loads(text)
        finally:lua.lua_close(state)
    return run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--move-source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();call=oracle(args.move_source);rows=[]
    for sender in (1,6,3):
        for fps in (30,60,120):
            result=call(fps,sender);trace=result.pop('trace')
            expected,_=follow(POINTS,fps,10 if sender==3 else 40)
            if len(trace)!=len(expected):raise AssertionError('Host Lua/Python frame counts differ')
            error=max(max(abs(a[i]-b[i]) for i in (0,1)) for a,b in zip(trace,expected))
            if error>1e-7:raise AssertionError('Host Lua/Python motion mismatch')
            distances=[distance_to_polyline((x,y),trace) for _,x,y in OBSERVATIONS]
            rows.append(dict(sender=sender,fps=fps,frames=len(trace)-1,python_model_max_error=error,
                max_observation_distance=max(distances),final_position=trace[-1],**result))
    report=dict(source_sha256=SOURCE_SHA,cases=rows,can_send_packets=False,unity_collision_verified=False,
                official_runtime_verified=False,
                limitations=['Video final position is observed stopping position, not a captured requested target.',
                             'Callback completion, CharacterController geometry and per-frame timing are not modeled.'],
                scope=__doc__)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))


if __name__=='__main__':main()
