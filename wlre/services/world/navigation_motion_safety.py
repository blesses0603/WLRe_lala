"""Fail-closed planar geometry checks and exact-waypoint PREVIEW fallback.

No collision, actor clearance, runtime equivalence or movement authority is
inferred. The fallback describes a controller policy; it never sends packets.
"""
import math
from wlre.services.world.navigation_funnel import covered

MAX_SEGMENTS=512
MAX_TRIANGLES=10000
MAX_CHECKS=2_000_000


def _point(p):
    return isinstance(p,(tuple,list)) and len(p)==3 and all(type(v) in (int,float) and math.isfinite(v) for v in p)


def check_preview(mesh,route,segments,*,catalog_key,expected_catalog_key):
    result=dict(can_send_packets=False,live_movement_verified=False,
                collision_verified=False,actor_clearance_verified=False,
                status='rejected',fallback=None)
    def reject(reason):
        return {**result,'reason':reason}
    if not catalog_key or catalog_key!=expected_catalog_key:return reject('catalog_mismatch')
    if route.get('can_send_packets') is not False:return reject('preview_authority_required')
    points=route.get('points',[]);faces=route.get('faces',[])
    if not 2<=len(points)<=MAX_SEGMENTS or any(not _point(p) for p in points):return reject('invalid_points')
    if not faces or len(faces)>MAX_SEGMENTS or any(type(n) is not int or n not in mesh.walkable for n in faces):
        return reject('forbidden_faces')
    if any(b not in mesh.adjacency[a] for a,b in zip(faces,faces[1:])):return reject('forbidden_connection')
    if max(p[1] for p in points)-min(p[1] for p in points)>1e-7:return reject('nonplanar')
    height=points[0][1]
    if any(abs(p[1]-height)>1e-7 for n in faces for p in mesh.faces[n]):return reject('nonplanar')
    triangles=[mesh.faces[n] for n in sorted(mesh.walkable)
               if all(abs(p[1]-height)<=1e-7 for p in mesh.faces[n])]
    if (not triangles or len(triangles)>MAX_TRIANGLES or len(segments)>MAX_SEGMENTS
            or (len(points)+len(segments))*len(triangles)>MAX_CHECKS):return reject('geometry_budget')
    if not covered(points[0],points[0],[mesh.faces[faces[0]]]) or not covered(points[-1],points[-1],[mesh.faces[faces[-1]]]):
        return reject('endpoint_outside_corridor')
    # Validate the fallback against its ordered corridor, not merely any nearby
    # island with the same tag. Other floors and disconnected islands cannot help.
    corridor=[mesh.faces[n] for n in faces]
    if any(not covered(a,b,corridor) for a,b in zip(points,points[1:])):return reject('ideal_path_not_contained')
    if not segments or any(len(s)!=2 or any(not _point(p) for p in s) for s in segments):return reject('invalid_motion')
    if any(abs(p[1]-height)>1e-7 for s in segments for p in s):return reject('nonplanar_motion')
    if math.dist(segments[0][0],points[0])>1e-7 or any(math.dist(a[1],b[0])>1e-7 for a,b in zip(segments,segments[1:])):
        return reject('discontinuous_motion')
    if math.dist(segments[-1][1],points[-1])>400.000001:return reject('motion_endpoint_outside_threshold')
    rejected=[i for i,(a,b) in enumerate(segments) if not covered(a,b,triangles)]
    # Always return an exact-waypoint candidate, even when these finite sampled
    # profiles pass. No claim covers arbitrary FPS or the official controller.
    return {**result,'status':'geometry_preview_only','reason':None,
            'modeled_motion_containment':'rejected' if rejected else 'contained',
            'rejected_segments':rejected,
            'fallback':dict(policy='exact_waypoint_arrival_no_skipping',points=[tuple(p) for p in points],
                geometry_contained=True,preview_stepper='exact_waypoint_step',requires_live_controller_validation=True,
                can_send_packets=False,live_movement_verified=False),
            'remaining_requirements':['actual_collision_and_actor_clearance','runtime_settings',
                                      'controller_and_device_validation']}


def exact_waypoint_step(points,index,position,distance):
    """Pure PREVIEW step: consume distance through corners, never skip a waypoint.

    Call only with the validated fallback points and unchanged geometry. Returned
    segments describe point-center movement; no physical/controller guarantee.
    """
    if (not 2<=len(points)<=MAX_SEGMENTS or any(not _point(p) for p in points)
            or not _point(position) or type(index) is not int or not 0<=index<len(points)-1
            or type(distance) not in (int,float) or not math.isfinite(distance) or not 0<=distance<=1e9):
        raise ValueError('Invalid exact-waypoint preview step')
    if max(p[1] for p in points)-min(p[1] for p in points)>1e-7:raise ValueError('Nonplanar preview step')
    start,end=points[index:index+2];edge=math.dist(start,end)
    if abs(math.dist(start,position)+math.dist(position,end)-edge)>1e-7:
        raise ValueError('Position left the validated segment')
    segments=[];position=tuple(position);done=False
    for _ in range(MAX_SEGMENTS):
        end=points[index+1];remaining=math.dist(position,end)
        if distance<remaining:
            if distance>0:
                target=tuple(position[i]+(end[i]-position[i])*distance/remaining for i in range(3))
                segments.append((position,target));position=target
            break
        if remaining>0:segments.append((position,tuple(end)))
        position=tuple(end);distance-=remaining
        if index==len(points)-2:
            done=True;break
        index+=1
    else:raise ValueError('Exact waypoint budget exceeded')
    return dict(position=position,index=index,done=done,segments=segments,
                can_send_packets=False,live_movement_verified=False)
