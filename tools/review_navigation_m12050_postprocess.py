"""Bounded full-search-to-player XYZ diagnostic; never authorizes movement."""
import argparse
import json
import math
from pathlib import Path
from tools.review_navigation_m12050_prepare import review as prepare_review
from tools.review_navigation_path_pipeline import oracle
from tools.review_navigation_rotation import IL2CPP_SHA, UNITY_SHA
from tools.review_navigation_player_points import SOURCE_SHA
from wlre.services.world.navigation_surface_3d import segment_on_surface


def endpoint_assessment(requested, corrected):
    if any(len(p)!=3 or any(not math.isfinite(v) for v in p) for p in (requested,corrected)):
        raise ValueError('Invalid endpoint')
    delta=[b-a for a,b in zip(requested,corrected)]
    return dict(requested_xyz=requested,corrected_xyz=corrected,
                adjustment_3d=math.dist(requested,corrected),
                adjustment_horizontal=math.hypot(delta[0],delta[2]),adjustment_vertical=delta[1],
                requested_destination_reached=None,live_movement_verified=False,can_send_packets=False)



def validate_report(report):
    """Pinned fixture acceptance; failures must retain no player candidates."""
    if len(report['rows'])!=16:raise AssertionError('Incomplete case coverage')
    for row in report['rows']:
        result=row['result'];candidates=result['postprocess'].get('candidates',[])
        if result['status']!='complete_prepared_search':
            if candidates:raise AssertionError('Failure produced candidates')
            continue
        if len(candidates)!=2:raise AssertionError('Missing modifier profile')
        for candidate in candidates:
            if math.dist(candidate['funnel']['vector_path'][-1],result['prepared']['points'][-1])>1e-5:
                raise AssertionError('Modifier changed prepared destination')
            surface=candidate['surface_assessment']
            if candidate['profile']['split_at_every_portal'] and (surface['funnel_rejected_segments'] or surface['player_rejected_segments']):
                raise AssertionError('Split path left XYZ surface')
            assessment=candidate['endpoint_assessment']
            if assessment['can_send_packets'] or assessment['requested_destination_reached'] is not None:
                raise AssertionError('Unverified arrival or authority')
    return report


def review(il2cpp,unity,source,cache):
    run=oracle(il2cpp,unity,move_source=source,capacity=1024)
    # Reuse precisely the full-graph Phase 71 inputs and negative controls.
    def evaluate(**fixture):
        # Prepare fixture connections omit portal edge identifiers. Recover these
        # only from the verified same-version graph, preserving removed edges.
        from tools.review_navigation_corner_following import CATALOG
        from wlre.services.world.navigation_database import load_cache,database_path
        graph=load_cache(database_path(),CATALOG,12050)
        edges=graph['connections']
        fixture['connections']=[[[n,c,next(e for t,cost,e in edges[i] if t==n and cost==c)] for n,c in row]
                                for i,row in enumerate(fixture['connections'])]
        output=run(**fixture);result=dict(output['search'])
        result['postprocess']=output
        if result['status']!='complete_prepared_search':
            if output.get('candidates'):raise AssertionError('Failure produced player path')
            return result
        route=result['path_nodes']
        triangles=[[[v/1000 for v in fixture['vertices'][j]] for j in fixture['faces'][i]] for i in route]
        for candidate in output['candidates']:
            funnel=candidate['funnel'];points=funnel['vector_path'];player=funnel['player_callback']['current_path']
            if not points or player!=points[1:]:raise AssertionError('Player callback mismatch')
            # The callback removes the first point. Retain it explicitly as the
            # modeled start; no assumption about the live actor transform.
            player_segments=[points[0]]+player
            candidate['surface_assessment']=dict(
                funnel_rejected_segments=[i for i,(a,b) in enumerate(zip(points,points[1:])) if not segment_on_surface(a,b,triangles)],
                player_rejected_segments=[i for i,(a,b) in enumerate(zip(player_segments,player_segments[1:])) if not segment_on_surface(a,b,triangles)],
                modeled_start_xyz=points[0],actor_collision_verified=False)
            candidate['endpoint_assessment']=endpoint_assessment(fixture['end_point'],points[-1])
        return result
    report=prepare_review(il2cpp,cache,evaluator=evaluate)
    report.update(il2cpp_sha256=IL2CPP_SHA,unity_sha256=UNITY_SHA,move_source_sha256=SOURCE_SHA)
    report['limitations']=[
        'Full 844-node Prepare/search; exact selected corridor compacted only for modifier VMs.',
        'Guarded native register/sort/StartEnd/Funnel composition across VMs, not full client lifecycle.',
        'Two explicit split profiles; actual runtime overrides and delegates remain unverified.',
        'Pinned MoveController callback on host Lua with modeled managed list; not official Lua binding.',
        'XYZ surface containment is not actor clearance, collision, grounding or actual arrival.',
        'Original requested end and adjusted end preserved; no destination arrival asserted.']
    return validate_report(report)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('libil2cpp','libunity','move-source','cache','output'):p.add_argument('--'+key,required=True)
    a=p.parse_args();result=review(a.libil2cpp,a.libunity,a.move_source,a.cache)
    Path(a.output).write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}))
