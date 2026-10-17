"""Choose a displayed position while preserving authoritative server fields."""
import math


def current_position(state):
    location=state.get('location',{})
    fix=location.get('confirmed')
    player=state.get('player',{})
    local=state.get('local_movement')
    if (fix and local and player.get('role_id') is not None
            and local.get('role_id')==player['role_id']
            and local.get('scene')==player.get('scene')==fix.get('scene')
            and local.get('base_fix_packet')==fix.get('packet_number')
            and local.get('steps_sent',0)>0
            and local.get('status') in ('running','finished','stopped')
            and all(isinstance(local.get(k),(int,float)) and math.isfinite(local[k])
                    and 0<=local[k]<=65535 for k in ('x','y'))):
        return {'scene':local['scene'],'x':round(local['x']),'y':round(local['y']),
                'source':'local_report','kind':'local_report','filled':True,
                'label':'本機同步（待伺服器確認）'}
    if not fix or fix.get('scene')!=player.get('scene'):return None
    current=bool(location.get('confirmed_is_current'))
    return {**fix,'kind':'server_fix','filled':current,
            'label':'伺服器確認' if current else '末次伺服器確認'}
