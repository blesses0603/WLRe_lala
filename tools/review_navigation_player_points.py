"""Run verified MoveController source with a modeled host Lua/list bridge.

The source is external and hash pinned. Host Lua 5.4 is not the official client
Lua runtime; this validates the callback source, not the native binding or motion.
"""
import argparse
import ctypes
import ctypes.util
import hashlib
import json
import math
from pathlib import Path

SOURCE_SHA='fa020de008d42e2d54c7e10bd75c67b9dbe2aaaba173ddf313b7d4c23646ef30'


def oracle(path):
    path=Path(path)
    if path.stat().st_size>128*1024:raise ValueError('Lua source size limit')
    source=path.read_bytes()
    if hashlib.sha256(source).hexdigest()!=SOURCE_SHA:raise ValueError('Unreviewed MoveController source digest')
    library=ctypes.util.find_library('lua5.4')
    if not library:raise ImportError('Optional host Lua 5.4 library unavailable')
    lua=ctypes.CDLL(library);P=ctypes.c_void_p
    for name,args,result in [('luaL_newstate',[],P),('luaL_openlibs',[P],None),('lua_close',[P],None),
                             ('luaL_loadbufferx',[P,ctypes.c_char_p,ctypes.c_size_t,ctypes.c_char_p,ctypes.c_char_p],ctypes.c_int),
                             ('lua_pcallk',[P,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_longlong,P],ctypes.c_int),
                             ('lua_tolstring',[P,ctypes.c_int,ctypes.POINTER(ctypes.c_size_t)],P)]:
        function=getattr(lua,name);function.argtypes=args;function.restype=result
    def run(points,*,world=False,player=True):
        if type(world) is not bool or type(player) is not bool:raise ValueError('Invalid player profile')
        if points is not None and (not 0<=len(points)<=256 or any(len(p)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1000 for v in p) for p in points)):raise ValueError('Invalid player points')
        literal='nil' if points is None else '{'+','.join('{'+','.join(repr(float(v)) for v in p)+'}' for p in points)+'}'
        prefix=b'''debug.sethook(function() error("Instruction budget") end,"",100000)
Mathf={};Vector3={zero={}};require=function(name) assert(name=="bit");return {} end
os=nil;io=nil;package=nil;dofile=nil;loadfile=nil
'''
        suffix=('''
local points='''+literal+'''
local list=nil
if points~=nil then
 list={Count=#points,RemoveAt=function(self,index)
   assert(index==0 and self.Count>1)
   for i=0,self.Count-2 do self[i]=self[i+1] end
   self[self.Count-1]=nil;self.Count=self.Count-1
 end}
 for i,p in ipairs(points) do list[i-1]=p end
end
local localPosition={1,2,3};local worldPosition={4,5,6};local target={7,8,9}
local owner={defaultSpeed=4,transform={position=worldPosition,localPosition=localPosition},seeker={}}
local called=nil
AstarPath={active={}}
local function invoke(kind,seeker,start,finish,callback)
 assert(seeker==owner.seeker and finish==target)
 assert(start=='''+('worldPosition' if world else 'localPosition')+''')
 called=kind;callback({vectorPath=list},nil)
end
LuaHelper={StartPathImmediately=function(...) invoke("immediate",...) end,StartPath=function(...) invoke("async",...) end}
MoveController.MoveToPosition(owner,target,true,0,'''+str(world).lower()+','+str(player).lower()+''')
assert(called=="'''+('immediate' if player else 'async')+'''" and owner.findingPath==false)
if owner.currentPath==nil then return "null" end
local rows={}
for i,p in ipairs(owner.currentPath) do rows[i]=string.format("[%.17g,%.17g,%.17g]",p[1],p[2],p[3]) end
return "["..table.concat(rows,",").."]"
''').encode()
        program=prefix+source+suffix;state=lua.luaL_newstate()
        if not state:raise ValueError('Unable to create host Lua state')
        try:
            lua.luaL_openlibs(state)
            status=lua.luaL_loadbufferx(state,program,len(program),b'@verified-move-controller',b't')
            if status==0:status=lua.lua_pcallk(state,0,1,0,0,None)
            size=ctypes.c_size_t();ptr=lua.lua_tolstring(state,-1,ctypes.byref(size))
            if not ptr or size.value>65536:raise ValueError('Invalid host Lua output')
            output=ctypes.string_at(ptr,size.value).decode()
            if status:raise ValueError('Host Lua execution failed: '+output)
            result=json.loads(output);expected=None if not points else points[1:] if len(points)>1 else points
            if result!=expected:raise ValueError('Player callback point mismatch')
            return dict(current_path=result,world_position=world,player=player,can_send_packets=False,
                        scope='Verified source on host Lua 5.4; modeled managed list and synchronous callback, not official Lua VM or movement')
        finally:lua.lua_close(state)
    return run


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',required=True);args=parser.parse_args()
    run=oracle(args.source);rows=[]
    for points in (None,[],[[1,2,3]],[[1,2,3],[4,5,6]],[[1,2,3],[4,-5,6],[-7,8,9]]):
        for world in (False,True):
            for player in (False,True):rows.append(dict(input=points,output=run(points,world=world,player=player)))
    print(json.dumps(dict(source_sha256=SOURCE_SHA,cases=rows,can_send_packets=False),sort_keys=True))


if __name__=='__main__':main()
