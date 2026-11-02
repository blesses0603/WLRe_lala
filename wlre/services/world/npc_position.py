"""Position evidence for a manual NPC request, shared by UI and dispatcher.

A completed locally reported path may permit a request; it does not turn into
an authoritative server arrival. The server still decides NPC distance.
"""
import math
from wlre.services.world.dynamic_bundle_runtime import current_catalog_token


def interaction_position_problem(state):
    player=state.get('player',{});scene=player.get('scene')
    location=state.get('location',{});fix=location.get('confirmed') or {}
    local=state.get('local_movement') or {}
    if local.get('status')=='running':return '角色仍在移動中，請等待路徑完成'
    if location.get('confirmed_is_current') and fix.get('scene')==scene:return None
    target=local.get('target') or {}
    token=local.get('catalog_token')
    navigation=state.get('navigation') or {}
    if (local.get('status')!='finished' or local.get('role_id')!=player.get('role_id')
            or local.get('scene')!=scene or fix.get('scene')!=scene
            or type(fix.get('packet_number')) is not int
            or local.get('base_fix_packet')!=fix['packet_number']
            or type(local.get('steps_sent')) is not int or local['steps_sent']<=0
            or type(token) not in (tuple,list) or tuple(token)!=current_catalog_token()
            or local.get('navigation_revision')!=navigation.get('revision')
            or navigation.get('stale') or target.get('scene')!=scene
            or target.get('source')!='local_goal'):
        return '目前位置尚未核對；請等待定位或重新完成移動'
    if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=65535
           for v in (local.get('x'),local.get('y'),target.get('x'),target.get('y'))):
        return '移動位置或目的地無效，請重新定位'
    if math.hypot(local['x']-target['x'],local['y']-target['y'])>1.5:
        return '本次移動尚未走完目的路徑'
    return None
