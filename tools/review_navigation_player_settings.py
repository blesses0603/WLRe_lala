"""Pinned static Lua evidence for player traffic-tag updates; no Lua execution.

This verifies source branches and call sites, not live invocation, callback
absence across the client, scene overrides or movement equivalence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from tools.review_navigation_awake_writes import INDEX_SHA
from wlre.services.world.official_lua_codec import _parameters,_cbc_decode

SOURCES={
 'Lua/Controller/PlayerController.lua':'0054442ed2d8a5196ea60c497155c8f5f45cd1ec303d01fd4ab6e36e3cccc542',
 'Lua/Common/Define.lua':'452e32903a686f22b8e98c1707efca80a45dcf73fd4f1bd5e7e08b38ae3db92c',
}


def review(lua_root,metadata):
    root=Path(lua_root)
    with (root/'index.json').open('rb') as stream:index_raw=stream.read(1024*1024+1)
    if len(index_raw)>1024*1024 or hashlib.sha256(index_raw).hexdigest()!=INDEX_SHA:raise ValueError('Unverified Lua index')
    index=json.loads(index_raw)
    with Path(metadata).open('rb') as stream:meta=stream.read(16*1024*1024+1)
    key,iv=_parameters(meta);texts={};sources=[]
    for name,sha in SOURCES.items():
        with (root/Path(name).name).open('rb') as stream:raw=stream.read(2*1024*1024+1)
        if len(raw)>2*1024*1024 or hashlib.md5(raw,usedforsecurity=False).hexdigest()!=index[name]:raise ValueError('Unverified Lua source')
        clear=_cbc_decode(raw,key,iv)
        if hashlib.sha256(clear).hexdigest()!=sha:raise ValueError('Unreviewed decoded source')
        texts[name]=clear.decode('utf-8-sig')
        sources.append(dict(path=name,input_sha256=hashlib.sha256(raw).hexdigest(),output_sha256=sha,bytes=len(clear)))
    text=texts['Lua/Controller/PlayerController.lua'];lines=text.splitlines()
    methods={};current=None;calls=[]
    for lineno,line in enumerate(lines,1):
        match=re.match(r'function PlayerController:([A-Za-z0-9_]+)\(',line)
        if match:current=match[1];methods[current]=[]
        if current:methods[current].append((lineno,line.strip()))
        if line.strip()=='self:UpdateTraversableTags();':calls.append(dict(method=current,line=lineno))
    if [c['method'] for c in calls]!=['UseTraffic','UnUseTraffic']:raise ValueError('Traffic update call sites changed')
    body='\n'.join(line for n,line in methods['UpdateTraversableTags'])
    expected='''function PlayerController:UpdateTraversableTags()
if self:GetTrafficKind() == TrafficKind.Sea then
self.roleController.moveController.seeker.traversableTags = TrafficPathTags.Sea;
elseif self:GetTrafficKind() == TrafficKind.Sky then
self.roleController.moveController.seeker.traversableTags = TrafficPathTags.Sky;
else
self.roleController.moveController.seeker.traversableTags = TrafficPathTags.Land;
end
end'''
    if not body.startswith(expected+'\n'):raise ValueError('Traffic branch changed')
    define=texts['Lua/Common/Define.lua']
    match=re.search(r'TrafficPathTags = \{\s*Land = (\d+),\s*Sea = (\d+),\s*Sky = (\d+),\s*\}',define)
    if not match or tuple(map(int,match.groups()))!=(9,4,15):raise ValueError('Tag constants changed')
    watched=('OnAwakeSettings','heuristic','heuristicScale','maxNearestNodeDistance','fullGetNearestSearch')
    hits={word:[i for i,line in enumerate(lines,1) if word in line] for word in watched}
    return dict(sources=sources,lua_index_sha256=INDEX_SHA,tag_masks=dict(land=9,sea=4,sky=15),
                update_method_line=methods['UpdateTraversableTags'][0][0],update_call_sites=calls,
                player_literal_setting_hits=hits,scope=__doc__,can_send_packets=False,
                runtime_invocation_verified=False,scene_overrides_verified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--lua-root',required=True);parser.add_argument('--metadata',required=True);args=parser.parse_args()
    print(json.dumps(review(args.lua_root,args.metadata),sort_keys=True))


if __name__=='__main__':main()
