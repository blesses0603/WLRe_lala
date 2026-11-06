"""Offline bounded source audit of official Common/Controller or Logic Lua batches.

A separate explicit download step supplies the private cache. No Lua execution,
product allowlist changes, runtime-absence proof or movement authority.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from tools.review_navigation_awake_writes import INDEX_SHA
from wlre.services.world.official_lua_codec import _parameters,_cbc_decode

GROUPS={'controllers':('Lua/Common/','Lua/Controller/'),'logic':('Lua/Logic/',)}
TERMS=('OnAwakeSettings','heuristic','heuristicScale','maxNearestNodeDistance',
       'fullGetNearestSearch','AstarPath','traversableTags','tagPenalties',
       'FunnelModifier','StartEndModifier','Seeker','LuaHelper.GetPath',
       'LuaHelper.StartPath','LuaHelper.StartPathImmediately','LuaHelper.GetNodeTag')
MAX_FILE_BYTES=2*1024*1024
MAX_TOTAL_BYTES=16*1024*1024


def selection(index_path,group='controllers',batch=0):
    with Path(index_path).open('rb') as stream:raw=stream.read(1024*1024+1)
    if len(raw)>1024*1024 or hashlib.sha256(raw).hexdigest()!=INDEX_SHA:raise ValueError('Unreviewed Lua index')
    if group not in GROUPS or type(batch) is not int or not 0<=batch<=3:raise ValueError('Invalid batch selector')
    index=json.loads(raw);selected=sorted(n for n in index if n.startswith(GROUPS[group]));names=selected[batch*40:(batch+1)*40]
    if not names or len(names)>40:raise ValueError('Batch file count bound')
    if any('..' in n.split('/') or not re.fullmatch(r'Lua/(?:Common|Controller|Logic(?:/Protocols)?)/[A-Za-z0-9_]+\.lua',n) for n in names):raise ValueError('Unexpected batch path')
    return index,names


def audit(index_path,metadata,cache_root,group='controllers',batch=0):
    index,names=selection(index_path,group,batch)
    with Path(metadata).open('rb') as stream:meta=stream.read(16*1024*1024+1)
    key,iv=_parameters(meta);rows=[];missing=[];total=0;root=Path(cache_root)
    for name in names:
        path=root/name
        if not path.exists():missing.append(name);continue
        with path.open('rb') as stream:raw=stream.read(MAX_FILE_BYTES+1)
        total+=len(raw)
        if len(raw)>MAX_FILE_BYTES or total>MAX_TOTAL_BYTES:raise ValueError('Batch bytes bound')
        if hashlib.md5(raw,usedforsecurity=False).hexdigest()!=index[name]:raise ValueError('Official Lua MD5 mismatch: '+name)
        clear=_cbc_decode(raw,key,iv);lines=clear.decode('utf-8-sig').splitlines()
        hits={term:[i for i,line in enumerate(lines,1) if term in line] for term in TERMS}
        requires=[]
        for i,line in enumerate(lines,1):
            match=re.match(r'''\s*require\s*\(?\s*["']([^"']+)["']''',line)
            if match:requires.append(dict(line=i,module=match[1]))
        rows.append(dict(path=name,encrypted_bytes=len(raw),decoded_bytes=len(clear),
                         input_sha256=hashlib.sha256(raw).hexdigest(),output_sha256=hashlib.sha256(clear).hexdigest(),
                         literal_hits={k:v for k,v in hits.items() if v},literal_requires=requires))
    return dict(index_sha256=INDEX_SHA,indexed_count=len(index),selected_prefixes=GROUPS[group],group=group,batch=batch,
                selected_count=len(names),verified_count=len(rows),missing=missing,files=rows,
                encrypted_bytes=total,selected_batch_complete=not missing,
                unselected_count=len(index)-len(names),runtime_overrides_verified=False,
                can_send_packets=False,scope=__doc__,interpretation='Literal hits can include comments or strings; require extraction is partial, not a Lua parser or complete dependency graph')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('index','metadata','cache-root'):p.add_argument('--'+key,required=True)
    p.add_argument('--group',choices=tuple(GROUPS),default='controllers');p.add_argument('--batch',type=int,default=0)
    a=p.parse_args();print(json.dumps(audit(a.index,a.metadata,a.cache_root,a.group,a.batch),sort_keys=True))


if __name__=='__main__':main()
