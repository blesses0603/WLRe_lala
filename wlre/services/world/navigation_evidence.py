"""Bounded, passive own-position/navigation evidence; no credentials or packets."""
import copy

LIMIT=256
KINDS=frozenset(('world_player','role_list_available','position_snapshot','movement_request','walk','navigation_geometry_change'))


def defaults():return {'events':[],'dropped':0}


def observe(state,event):
    kind=event['type']
    if kind not in KINDS:return
    if kind in ('role_list_available','world_player'):state.navigation_evidence=defaults()
    if kind=='role_list_available':return
    pid=state.player.get('role_id');scene=state.player.get('scene')
    row={'sequence':state.packet_count,'scene':scene,'navigation_revision':state.navigation.get('revision',0)}
    if kind in ('position_snapshot','walk') and (pid is None or event.get('role_id')!=pid):return
    if kind=='world_player':
        row.update(kind='position_fix',source='S3-1',x=state.player['x'],y=state.player['y'])
    elif kind=='position_snapshot':
        row.update(kind='position_fix',source=event['source'],scene=event['scene'],x=event['x'],y=event['y'])
    elif kind=='movement_request':row.update(kind='local_request',source='C6-1',x=event['x'],y=event['y'])
    elif kind=='walk':row.update(kind='destination_notice',source='S6-1',x=event['x'],y=event['y'])
    elif kind=='navigation_geometry_change':
        from wlre.services.world.obstacle_scope import affects_navigation
        row.update(kind='geometry_change',affects_current_map=affects_navigation(event,scene),
            reason=event.get('reason','unspecified'),scope=event.get('geometry_scope','world'),
            details_parsed=bool(event.get('details_parsed')),stale=bool(state.navigation.get('stale')))
    if scene is None:return
    history=state.navigation_evidence
    history['events'].append(row)
    if len(history['events'])>LIMIT:
        history['events'].pop(0);history['dropped']+=1


def export(snapshot):
    """Copy the selected evidence fields, never export the whole character snapshot."""
    from wlre.services.world.runtime_1275 import baseline_revision,active_runtime
    history=snapshot.get('navigation_evidence',defaults())
    result={'schema_version':1,'resource_revision':int(baseline_revision()),
        'capture_type':'lala_passive_navigation_events','events':copy.deepcopy(history['events']),
        'dropped':history['dropped'],'stages':{},'reference_points':[],
        'can_send_packets':False,'live_movement_verified':False,'dynamic_geometry_verified':False}
    try:
        source=active_runtime()
        scenes={row['scene'] for row in history['events']}
        for scene in scenes:
            data=source.stages.get(scene)
            if data:
                result['stages'][str(scene)]={k:data[k] for k in ('model_id','offset_y')}
        result['stage_source_status']='verified_runtime_1275'
    except (OSError,ValueError,KeyError,AttributeError):result['stage_source_status']='unavailable'
    return result
