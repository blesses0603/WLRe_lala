"""Static cross-reference follow-up for 18 reviewed dynamic-capability Lua files.

No Lua runs. Literal references include declarations, comments and strings and
cannot prove the absence of indirect/native calls or the value of runtime flags.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from tools.review_navigation_lua_batch import audit
from wlre.services.world.official_lua_codec import _parameters,_cbc_decode

BATCHES=(('controllers',1),('logic',4),('ui',12),('data',4),('support',3))
SYMBOLS=('InjectByModule','InjectByName','CacheInjectFunction','LuaInjectionStation',
         'InjectionBridgeInfo','LuaInjectionBus','DebugServerIp','mobdebug')


def review(index,metadata,cache_root):
    rows=[]
    for group,count in BATCHES:
        for batch in range(count):
            report=audit(index,metadata,cache_root,group,batch)
            if not report['selected_batch_complete']:raise ValueError('Dynamic-reference census requires complete cache')
            rows.extend(report['files'])
    if len(rows)!=866 or len({r['path'] for r in rows})!=866:raise ValueError('Incomplete or overlapping corpus')
    with Path(metadata).open('rb') as stream:meta=stream.read(16*1024*1024+1)
    key,iv=_parameters(meta);references={s:[] for s in SYMBOLS};dynamic=[];texts={}
    for row in rows:
        with (Path(cache_root)/row['path']).open('rb') as stream:raw=stream.read(2*1024*1024+1)
        if hashlib.sha256(raw).hexdigest()!=row['input_sha256']:raise ValueError('Source changed after audit')
        clear=_cbc_decode(raw,key,iv)
        if hashlib.sha256(clear).hexdigest()!=row['output_sha256']:raise ValueError('Decoded source changed')
        text=clear.decode('utf-8-sig');lines=text.splitlines()
        for symbol in SYMBOLS:
            hits=[i for i,line in enumerate(lines,1) if symbol in line]
            if hits:references[symbol].append(dict(path=row['path'],lines=hits))
        if row['dynamic_literal_hits']:dynamic.append(dict(path=row['path'],sha256=row['output_sha256'],hits=row['dynamic_literal_hits']))
        if row['path'] in ('Lua/System/Injection/LuaInjectionBus.lua','Lua/tolua.lua'):texts[row['path']]=text
    bus=texts['Lua/System/Injection/LuaInjectionBus.lua']
    # This particular pinned file uses only a single --[[...]] license block
    # and line comments. This is not advertised as a general Lua lexer.
    without_block=re.sub(r'--\[\[.*?\]\]', '',bus,flags=re.S)
    if any(line.split('--',1)[0].strip() for line in without_block.splitlines()):raise ValueError('Injection bus no longer comment-only')
    tolua=texts['Lua/tolua.lua'].splitlines()
    if tolua[14].strip()!='if DebugServerIp then' or tolua[15].strip()!='require("mobdebug").start(DebugServerIp)' or tolua[16].strip()!='end':raise ValueError('Debugger guard changed')
    if len(dynamic)!=18:raise ValueError('Dynamic inventory changed')
    return dict(verified_sources=866,dynamic_files=dynamic,symbol_references=references,
                injection_bus_comment_only=True,debugger_guard=dict(path='Lua/tolua.lua',line=15,condition='DebugServerIp',runtime_value_verified=False),
                callback_state_verified=False,indirect_calls_excluded=False,can_send_packets=False,scope=__doc__)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('index','metadata','cache-root'):p.add_argument('--'+key,required=True)
    a=p.parse_args();print(json.dumps(review(a.index,a.metadata,a.cache_root),sort_keys=True))


if __name__=='__main__':main()
