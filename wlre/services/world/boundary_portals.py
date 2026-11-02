"""Bind all exits using current Eve geometry and independent link ordinals.

StageMap EvtID is not a door index for hidden markers. Never invent one from
their target scene. EventManager._NewPortal and StageObjectData instead define
rectangular signType 1/4 touch regions; Role.SendMeetDoor uses their real index.
"""
from collections import Counter

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


def door_anchor(door, stage):
    """EventManager._NewPortal uses TransferGridPosition for every sign type."""
    if any(type(door.get(k)) is not int or door[k]<0 for k in ('x','y','sign_x','sign_y')):
        return None
    rx,ry=stage.get('pos_x_ratio'),stage.get('pos_y_ratio')
    if type(rx) is not int or type(ry) is not int or not 1<=rx<=255 or not 1<=ry<=255:return None
    x=(door['x']-1)*20*rx+door['sign_x']*rx
    y=(door['y']-1)*20*ry+door['sign_y']*ry
    return (x,y) if 0<=x<=65535 and 0<=y<=65535 else None


def boundary_portal_bindings(stage_raw, link_raw, doors, stages):
    """Return (positions, destinations) keyed by actual Eve door identity.

    Only a unique PlayerTouch region or exact anchor matching the link point can
    supply a binding. Results are keyed by actual Eve door ID, while link_index
    retains the independent EveDoorLinks ordinal. StageMap markers are display
    references and cannot substitute for this geometric proof.
    """
    parse_stage_map_portals(stage_raw)  # validate display metadata, not door identity
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
            target = link['destination']
            point = _packet_position(stage,link['x'],link['y'])
            if point is None:continue
            matches = [(d,b) for d,b in regions if b is not None
                       and b[0]<=point[0]<=b[2] and b[1]<=point[1]<=b[3]]
            # Sign types 2/3/5 have prefab-defined collider shapes. Only an
            # exact unique NewPortal anchor is accepted; never guess a radius.
            matches += [(d,None) for d,b in regions if b is None
                        and d.get('sign_type') in (2,3,5)
                        and door_anchor(d,stage) == point]
            if len(matches)!=1:continue
            door,bounds = matches[0]
            index = door.get('index')
            if type(index) is not int or not 1<=index<=65535 or counts[index]!=1:continue
            if not door.get('touch_event_ids'):continue
            key = (scene,index)
            # Two links claiming one container cannot prove a unique route.
            if key in destinations:
                destinations[key] = None
                positions.pop(key,None)
                continue
            if target not in stages:
                destinations[key] = None
                continue
            binding = 'unique_boundary_touch_region' if bounds else 'unique_door_anchor'
            positions[key] = {'scene':scene,'index':index,'x':point[0],'y':point[1],
                'projection_guard':guard,'position_verified':True,
                'raw_link_x':link['x'],'raw_link_y':link['y'],
                'pos_x_ratio':stage['pos_x_ratio'],'pos_y_ratio':stage['pos_y_ratio'],
                'source_kind':'1275_eve_door_links_grid_scaled','trigger_bounds':bounds,
                'binding_kind':binding,'link_index':link['index']}
            destinations[key] = dict(link,index=index,link_index=link['index'],matched_stage_map=False,matched_touch_region=True,
                event_x=door['x'],event_y=door['y'],destination_verified=True,
                trigger_verified=False,binding_kind=binding)
    return positions,{key:value for key,value in destinations.items() if value is not None}


def reconcile_touch_bindings(stage_raw, link_raw, doors, stages, positions, destinations):
    """Replace all ordinal joins with current physical door evidence.

    Number equality is never a fallback for a missing or conflicting match.
    Build first so a parse failure cannot leave partially updated dictionaries.
    """
    bound_positions, bound_targets = boundary_portal_bindings(stage_raw,link_raw,doors,stages)
    positions.clear()
    destinations.clear()
    positions.update(bound_positions)
    destinations.update(bound_targets)


def reconcile_route_conflicts(positions, destinations, routes, evidence=None):
    """A second official route at the same point may expose conditional targets.

    Route ordinals are never door IDs. Only compare physical source points;
    conflicting destinations revoke the claimed unique target, not raw evidence.
    """
    targets = {}
    for row in routes:
        if (row.get('position_verified') is True
                and type(row.get('scene')) is int
                and type(row.get('destination')) is int):
            targets.setdefault((row['scene'],row.get('x'),row.get('y')),set()).add(row['destination'])
    for key,row in list(destinations.items()):
        point = positions.get(key,{})
        alternatives = targets.get((key[0],point.get('x'),point.get('y')),set())
        if alternatives - {row.get('destination')}:
            if isinstance(evidence,dict):
                reference = evidence.get((key[0],row.get('link_index',key[1])))
                if isinstance(reference,dict):
                    reference['issues'] = tuple(dict.fromkeys(
                        tuple(reference.get('issues') or ()) + ('conflicting_official_destinations',)))
                    reference['destination_candidates'] = tuple(sorted(alternatives | {row['destination']}))
            destinations.pop(key,None)
            positions.pop(key,None)
