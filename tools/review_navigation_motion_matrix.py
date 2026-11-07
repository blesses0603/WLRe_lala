"""Bounded planar motion diagnostics across pinned official graphs; no live authority.

Travel mode controls graph eligibility only. Speed, grounded physics and timing
are hypothetical sensitivity inputs, not verified sea/sky controller behavior.
"""
import argparse
from collections import Counter
import itertools
import json
import math
from pathlib import Path
from tools.review_navigation_corner_following import CATALOG
from tools.review_navigation_mode_matrix import reference_graph
from tools.navigation_same_geometry_control import independent_cost
from wlre.services.world.catalog_identity import OfficialCatalogIdentity,PackageRevision
from wlre.services.world.navigation import NavigationError
from wlre.services.world.navigation_database import REVIEWED_MODELS,database_path,load_cache
from wlre.services.world.navigation_preview import PreviewMesh,NoPreviewRoute
from wlre.services.world.navigation_funnel import covered
from wlre.services.world.navigation_motion_safety import check_preview,exact_waypoint_step


def motion(points,fps):
    """Nav integer coordinates: 1000 units/world, speed 3.5, radius 0.4.

    Retain complete straight runs between waypoint changes, including the final
    update after removal, matching the previously reviewed Lua loop ordering.
    """
    if fps not in (30,60,120) or not 2<=len(points)<=512:raise ValueError('Unreviewed motion input')
    if any(len(p)!=3 or any(not math.isfinite(v) for v in p) for p in points):raise ValueError('Invalid point')
    if max(p[1] for p in points)-min(p[1] for p in points)>1e-7:raise ValueError('Planar model only')
    position=tuple(points[0]);pending=list(points[1:]);segments=[];begin=position;prior=None
    for frame in range(180*fps):
        if not pending:
            if begin!=position:segments.append((begin,position))
            return dict(segments=segments,stop=position,frames=frame,complete=True)
        target=pending[0]
        while pending and math.dist(position,target)<400:
            target=pending[1] if len(pending)>1 else pending[0];pending.pop(0)
        if target!=prior:
            if begin!=position:segments.append((begin,position))
            begin=position;prior=target
        length=math.dist(position,target);step=min(1,3500/fps/length) if length else 0
        position=tuple(position[i]+step*(target[i]-position[i]) for i in range(3))
    return dict(complete=False,reason='180_second_model_budget',frames=180*fps)


def departure_sample(segment,triangles):
    """Lower-bound departure on nine points of ONE rejected segment, not max clearance."""
    a,b=segment;largest=0.
    for step in range(9):
        p=tuple(a[i]+(b[i]-a[i])*step/8 for i in range(3))
        if covered(p,p,triangles):continue
        closest=float('inf')
        for tri in triangles:
            for u,v in zip(tri,tri[1:]+tri[:1]):
                delta=tuple(v[i]-u[i] for i in range(3));length=sum(x*x for x in delta)
                t=max(0,min(1,sum((p[i]-u[i])*delta[i] for i in range(3))/length)) if length else 0
                closest=min(closest,math.dist(p,tuple(u[i]+t*delta[i] for i in range(3))))
        largest=max(largest,closest)
    return largest/10


def audit(decoded,model,mode):
    mesh=PreviewMesh(decoded,travel_mode=mode);reference=reference_graph(decoded,mode)
    if mesh.walkable!=reference.walkable:raise AssertionError('Mode eligibility mismatch')
    nodes=sorted(mesh.walkable);chosen=[nodes[i] for i in sorted({0,len(nodes)//2,len(nodes)-1})] if nodes else []
    cases=[]
    for a,b in itertools.permutations(chosen,2):
        row=dict(source=a,target=b);cases.append(row);start,end=mesh.centers[a],mesh.centers[b]
        try:
            source,_=mesh.locate(start[0],start[2],height=start[1]);target,_=mesh.locate(end[0],end[2],height=end[1])
            control=independent_cost(reference,source,target)
            try:raw=mesh.route((start[0],start[2]),(end[0],end[2]),start[1],end[1])
            except NoPreviewRoute:
                if control['cost'] is not None:raise AssertionError('Reachable graph rejected')
                row['status']='disconnected';continue
            if raw['cost']!=control['cost'] or raw['can_send_packets'] is not False:raise AssertionError('Invalid graph result')
            row['graph_faces']=len(raw['faces'])
            try:route=mesh.route((start[0],start[2]),(end[0],end[2]),start[1],end[1],smooth=True)
            except NavigationError as e:
                row.update(status='smoothing_refused',reason=str(e));continue
        except NavigationError as e:
            row.update(status='endpoint_refused',reason=str(e));continue
        points=route['points'];row.update(status='planar',corners=len(points),motion=[])
        if len(points)<2:
            row['status']='coincident_points';continue
        # Exclude other floors even if their projected geometry overlaps.
        triangles=[mesh.faces[n] for n in sorted(mesh.walkable)
                   if all(abs(v[1]-points[0][1])<=1e-7 for v in mesh.faces[n])]
        for fps in (30,60,120):
            result=motion(points,fps)
            if not result['complete']:
                row['motion'].append(dict(fps=fps,**result));continue
            unsafe=[(x,y) for x,y in result['segments'] if not covered(x,y,triangles)]
            error=math.dist(result['stop'],points[-1])/10
            if error>40.000001:raise AssertionError('Modeled stop exceeds source threshold')
            safety=check_preview(mesh,route,result['segments'],catalog_key=CATALOG,expected_catalog_key=CATALOG)
            if safety['can_send_packets'] is not False:raise AssertionError('Safety audit granted authority')
            if safety['fallback']:
                exact=exact_waypoint_step(points,0,points[0],sum(math.dist(a,b) for a,b in zip(points,points[1:]))+1)
                if not exact['done'] or math.dist(exact['position'],points[-1])>1e-7 or any(not covered(a,b,triangles) for a,b in exact['segments']):
                    raise AssertionError('Exact-waypoint preview fallback failed geometry check')
            row['motion'].append(dict(safety_status=safety['status'],safety_reason=safety['reason'],
                fallback_policy=safety['fallback']['policy'] if safety['fallback'] else None,
                fps=fps,frames=result['frames'],segments=len(result['segments']),
                stop_error_packet=error,containment_rejected_segments=len(unsafe),
                first_crossing=unsafe[0] if unsafe else None,
                first_crossing_sample_departure_packet=departure_sample(unsafe[0],triangles) if unsafe else 0,complete=True))
    return dict(model=model,mode=mode,eligible=len(nodes),sampled_nodes=chosen,cases=cases,can_send_packets=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    v=json.loads((a.snapshot/'current-identity.json').read_text())
    identity=OfficialCatalogIdentity(v['data_ver'],v['exe_version'],tuple(PackageRevision(**x) for x in v['packages']))
    if identity.key!=CATALOG:raise ValueError('Unreviewed catalog')
    rows=[]
    for model in sorted(set(REVIEWED_MODELS)-{10000,10004,10005}):
        decoded=load_cache(database_path(),identity.key,model)
        if decoded is None:raise ValueError('Missing same-version geometry')
        rows.extend(audit(decoded,model,mode) for mode in ('land','sea','sky'))
    cases=[c for r in rows for c in r['cases']];runs=[m for c in cases for m in c.get('motion',[])]
    summary=dict(models=len(rows)//3,mode_rows=len(rows),empty_modes=sum(not r['eligible'] for r in rows),
        cases=len(cases),statuses=dict(Counter(c['status'] for c in cases)),motion_runs=len(runs),
        incomplete=sum(not m['complete'] for m in runs),
        safety_statuses=dict(Counter(m.get('safety_status','incomplete') for m in runs)),
        fallback_rejections=dict(Counter(m['safety_reason'] for m in runs if m.get('safety_reason'))),
        containment_rejected_runs=sum(m.get('containment_rejected_segments',0)>0 for m in runs),
        sampled_departure_over_one_unit_runs=sum(m.get('first_crossing_sample_departure_packet',0)>1 for m in runs),
        max_stop_error_packet=max((m.get('stop_error_packet',0) for m in runs),default=None))
    report=dict(summary=summary,rows=rows,catalog_key=identity.key,can_send_packets=False,official_runtime_verified=False,
        scope=__doc__,limitations=['Only three sampled nodes per model/mode; not every path.',
        'Exact planar segment coverage of modeled motion, not physical collision testing.',
        'Sea/sky masks tested; their actual movement controllers and speed are not verified.'])
    a.output.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(summary))


if __name__=='__main__':main()
