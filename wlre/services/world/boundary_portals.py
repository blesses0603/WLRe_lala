"""Bind unmarked coastal exits using current Eve touch regions and links.

StageMap EvtID is not a door index for hidden markers. Never invent one from
their target scene. EventManager._NewPortal and StageObjectData instead define
rectangular signType 1/4 touch regions; Role.SendMeetDoor uses their real index.
"""
from collections import Counter
import struct

from wlre.services.world.portal_links_1275 import parse_stage_map_portals, parse_eve_door_links
from wlre.services.world.portal_evidence_1275 import _packet_position, _projection_guard


def touch_bounds(door, stage):
    if type(door.get('sign_type')) is not int or door['sign_type'] not in (1, 4):return None
    keys = ('x','y','right','bottom','sign_x','sign_y')
    if any(type(door.get(k)) is not int or door[k]<0 for k in keys):return None
    rx, ry = stage.get('pos_x_ratio'), stage.get('pos_y_ratio')
    if type(rx) is not int or type(ry) is not int or not 1<=rx<=255 or not 1<=ry<=255:return None
    # Data.LoadEve scales both grid and sign offsets; Stage.TransferGridPosition
    # subtracts one 20-pixel grid cell. EveDoorLinks XY uses a different space.
    x = (door['x']-1)*20*rx + door['sign_x']*rx
    y = (door['y']-1)*20*ry + door['sign_y']*ry
    right = (door['right']-1)*20*rx + door['sign_x']*rx
    bottom = (door['bottom']-1)*20*ry + door['sign_y']*ry
    if not 0<=x<right<=65535 or not 0<=y<bottom<=65535:return None
    return (x,y,right,bottom)


def boundary_portal_bindings(stage_raw, link_raw, doors, stages):
    """Return independent (positions, destinations); do not override markers.

    Only a unique PlayerTouch rectangle containing the verified link point,
    whose real door ID equals that scene-local link ID, can supply a binding.
    A missing ordinary marker is allowed; conflicting/duplicate ones are not.
    """
    parse_stage_map_portals(stage_raw)  # strict length/schema validation
    referenced = set()
    for offset in range(4,len(stage_raw),18):
        scene,kind,cross,index,*_ = struct.unpack_from('<HBHIHHIB',stage_raw,offset)
        if kind in (2,3) and scene and index:referenced.add((scene,index))
    links = parse_eve_door_links(link_raw)
    positions, destinations = {}, {}
    for scene, entries in doors.items():
        stage = stages.get(scene)
        if type(scene) is not int or not isinstance(stage,dict):continue
        guard = _projection_guard(stage)
        if guard is None:continue
        counts = Counter(d.get('index') for d in entries if isinstance(d,dict))
        regions = [(d,touch_bounds(d,stage)) for d in entries if isinstance(d,dict)]
        for link in links.get(scene,()):
            key = (scene,link['index'])
            if key in referenced:continue
            target = link['destination']
            if target not in stages:continue
            point = _packet_position(stage,link['x'],link['y'])
            if point is None:continue
            matches = [(d,b) for d,b in regions if b is not None
                       and b[0]<=point[0]<=b[2] and b[1]<=point[1]<=b[3]]
            if len(matches)!=1:continue
            door,bounds = matches[0]
            index = door.get('index')
            if type(index) is not int or not 1<=index<=65535 or counts[index]!=1 or index!=link['index']:continue
            if not door.get('touch_event_ids'):continue
            positions[key] = {'scene':scene,'index':index,'x':point[0],'y':point[1],
                'projection_guard':guard,'position_verified':True,
                'source_kind':'1275_eve_door_links_grid_scaled','trigger_bounds':bounds,
                'binding_kind':'unique_boundary_touch_region'}
            destinations[key] = dict(link,matched_stage_map=False,matched_touch_region=True,
                event_x=door['x'],event_y=door['y'],destination_verified=True,
                trigger_verified=False,binding_kind='unique_boundary_touch_region')
    return positions,destinations
