"""Pinned minimap click-chain audit; no UI execution, client connection or target inference."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from tools.review_navigation_awake_writes import INDEX_SHA
from wlre.services.world.official_lua_codec import _parameters,_cbc_decode

SOURCES={
 'Lua/UI/Logic/UIMain.lua':'a2c95bbdbe36a0370c024b502262a1d2cf6d922a020825b3d5e4abd19133f4d1',
 'Lua/Controller/PlayerController.lua':'0054442ed2d8a5196ea60c497155c8f5f45cd1ec303d01fd4ab6e36e3cccc542',
 'Lua/Controller/RoleController.lua':'af01c2a8e1b785ff9bc53f080b9282ebcd3b31c275ec8f3ff10e1a0f869ce8e9',
 'Lua/Controller/MoveController.lua':'fa020de008d42e2d54c7e10bd75c67b9dbe2aaaba173ddf313b7d4c23646ef30',
 'Lua/Logic/Stage.lua':'784b5098241463159112b29fa81ca23dfa9a2cc24dd3fe20ec29f1a05df52605',
 'Lua/Logic/Role.lua':'6f6d9cb8baa76f4bd7cbb9f55a421fecfd5c5f1e3cb873fd41ecf8ae442b484b',
 'Lua/Common/Define.lua':'452e32903a686f22b8e98c1707efca80a45dcf73fd4f1bd5e7e08b38ae3db92c',
}
CHECKS={
 'Lua/UI/Logic/UIMain.lua':('local function OnClick_Event_MapMask','local function OnClick_Event_AreaMapBG',
  'ScreenPointToLocalPointInRectangle','base.RawImage_AreaMapBG.transform','Stage.GetFloorPosition(TargetPosition, 100)',
  'areaMapTargetPos.x,areaMapTargetPos.y = TransferMapPosition','Role.player:MoveToStage(Stage.stageId, areaMapTargetPos, callback, nil, true)',
  'base.Event_AreaMapBG_Delegate = OnClick_Event_AreaMapBG'),
 'Lua/Controller/PlayerController.lua':('local pos = TransferPosition(position2d.x, position2d.y)',
  'self.roleController:MoveToPosition(targetPosition, true, EMoveSender.Player, callback, true)'),
 'Lua/Controller/MoveController.lua':('self.moveSender = moveSender','self.horizontalSpeed = self.defaultSpeed',
  'AStarNextPathDistanceSquare = 0.16','AStarNextPathDistanceSquare = 0.01'),
 'Lua/Logic/Stage.lua':('SCALE_RATIO = 0.01','function TransferMapPosition','Physics.Raycast(cachedVec3, cachedVec3Down, nil, 200, layer)'),
 'Lua/Logic/Role.lua':('function Role.EndMove()','function Role.GetPlayerMoveDoneCallback()'),
}


def local_to_packet(local_x,local_y):
    """Bangkok 1296 area-map RectTransform-local units, NOT screen pixels."""
    if any(type(v) not in (float,int) or not math.isfinite(v) for v in (local_x,local_y)):
        raise ValueError('Invalid local coordinates')
    rate=100*1000/6000;middle=500;outline=12
    image_x=local_x+middle+outline
    image_y=(1024-outline)-(local_y+middle)
    world_x=(image_x-12)/rate
    world_z=(1024-12-image_y)/rate
    return world_x/0.01,6000-world_z/0.01


def review(index_path,metadata,cache_root):
    raw=Path(index_path).read_bytes()
    if len(raw)>1024*1024 or hashlib.sha256(raw).hexdigest()!=INDEX_SHA:
        raise ValueError('Unreviewed official index')
    index=json.loads(raw)
    if Path(metadata).stat().st_size>16*1024*1024:raise ValueError('Metadata size bound')
    key,iv=_parameters(Path(metadata).read_bytes());rows=[]
    for name,expected in SOURCES.items():
        path=Path(cache_root)/name
        if path.stat().st_size>2*1024*1024:raise ValueError('Lua size bound')
        raw=path.read_bytes()
        if hashlib.md5(raw,usedforsecurity=False).hexdigest()!=index[name]:raise ValueError('Indexed Lua mismatch')
        clear=_cbc_decode(raw,key,iv)
        if hashlib.sha256(clear).hexdigest()!=expected:raise ValueError('Decoded source mismatch')
        lines=clear.decode('utf-8-sig').splitlines();hits={}
        for check in CHECKS.get(name,()):
            hits[check]=[n for n,line in enumerate(lines,1) if check in line]
            if not hits[check]:raise ValueError('Expected chain evidence missing')
        rows.append(dict(path=name,sha256=expected,source_lines=hits))
    return dict(sources=rows,local_to_packet_formula='x=3000+6*u; y=3000-6*v',
                local_units_are_screen_pixels=False,source_sender='Player (1)',
                stop_radius_packet=40,original_click_known=False,requested_target_known=False,
                observed_stop=[1850,4915],runtime_chain_observed=False,can_send_packets=False,
                hypothetical_stop_as_target_local=[(1850-3000)/6,(3000-4915)/6],
                interpretation='Inverse of observed stop is arithmetic only, NOT recovered click position.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('index','metadata','cache-root','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=review(a.index,a.metadata,a.cache_root)
    a.output.write_text(json.dumps(r,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in r.items() if k!='sources'}))


if __name__=='__main__':main()
