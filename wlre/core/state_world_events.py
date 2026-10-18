"""World and position events; server location observations are authoritative."""
WORLD_KINDS = frozenset((
    'world_player', 'position_snapshot', 'movement_request',
    'navigation_geometry_change', 'walk', 'nearby_leave',
))


def apply_world_event(state, event, affects_navigation):
    kind = event['type']
    if kind == "world_player":
        state.player = event["player"]
        state.positions.clear()
        state.remember_position(state.player["role_id"],state.player["x"],state.player["y"])
        state.phase = "world_received"
        state.confirm_location(state.player['scene'],state.player['x'],state.player['y'],'S3-1')
        state.navigation = {'scene':state.player['scene'],'revision':state.navigation['revision']+1,
                           'stale':False,'runtime_geometry_verified':False,'reasons':[]}
    elif kind == 'position_snapshot':
        if event['role_id']==state.player.get('role_id'):
            same_scene=event['scene']==state.player.get('scene')
            previous_navigation=state.navigation
            if not same_scene:state.positions.clear()
            state.player.update(scene=event['scene'],x=event['x'],y=event['y'])
            state.remember_position(event['role_id'],event['x'],event['y'])
            state.confirm_location(event['scene'],event['x'],event['y'],event['source'])
            # Same-map repositioning may also change floor or dynamic objects.
            state.navigation={'scene':event['scene'],'revision':previous_navigation['revision']+1,
                'stale':previous_navigation.get('stale',False) if same_scene else False,
                'runtime_geometry_verified':False,
                'reasons':previous_navigation.get('reasons',[]) if same_scene else []}
        else:
            state.remember_position(event['role_id'],event['x'],event['y'])
    elif kind == 'movement_request':
        state.location['requested_destination']={'x':event['x'],'y':event['y'],
                    'scene':state.player.get('scene'),'source':'C6-1','packet_number':state.packet_count}
        state.location['confirmed_is_current']=False
        state.wait_for_position()
    elif kind == 'navigation_geometry_change' and affects_navigation(event,state.player.get('scene')):
        state.navigation['stale'] = True
        state.navigation['revision'] += 1
        state.navigation['reasons'] = (state.navigation['reasons']+[event['reason']])[-10:]
    elif kind == "initial_data_complete":
        state.initial_data_complete = True

    if kind == "walk":
        state.remember_position(event["role_id"],event["x"],event["y"])
        if event['role_id']==state.player.get('role_id'):
            state.location['server_destination']={'x':event['x'],'y':event['y'],
                    'scene':state.player.get('scene'),'source':'S6-1','packet_number':state.packet_count}
            state.location['confirmed_is_current']=False
            state.wait_for_position()
    elif kind == 'nearby_leave' and event['role_id']!=state.player.get('role_id'):
        state.positions.pop(str(event['role_id']),None)
