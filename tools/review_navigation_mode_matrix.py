"""Offline, bounded all-mode graph checks and bidirectional route cost controls."""
import argparse
from collections import Counter
import itertools
import json
from pathlib import Path
from types import SimpleNamespace
from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision
from wlre.services.world.navigation import Mesh
from wlre.services.world.navigation_database import REVIEWED_MODELS, database_path, load_cache
from wlre.services.world.navigation_preview import PreviewMesh, NoPreviewRoute
from tools.navigation_same_geometry_control import independent_cost


def reference_graph(decoded, mode):
    """Build allowed arcs independently of PreviewMesh's filtering implementation."""
    base = Mesh(decoded['mesh'])
    tags = {'land': {0, 3}, 'sea': {2}, 'sky': {0, 1, 2, 3}}[mode]
    allowed = {i for i, (_, flags) in enumerate(base.metadata)
               if flags % 2 == 1 and (flags // 524288) % 32 in tags}
    adjacency = {i: {} for i in range(len(base.faces))}
    for source, arcs in enumerate(decoded['connections']):
        for target, _, _ in arcs:
            if source in allowed and target in allowed and target in base.adjacency[source]:
                adjacency[source][target] = base.adjacency[source][target]
    return SimpleNamespace(walkable=allowed, adjacency=adjacency,
                           serialized_connections=decoded['connections'], metadata=base.metadata)


def audit_model(decoded, model, mode):
    mesh = PreviewMesh(decoded, travel_mode=mode)
    reference = reference_graph(decoded, mode)
    if mesh.walkable != reference.walkable or mesh.adjacency != reference.adjacency:
        raise AssertionError('Preview eligibility or connectivity differs from reference graph')
    nodes = sorted(reference.walkable)
    sampled = nodes[::max(1, len(nodes)//4)][:5]
    successes = rejected = 0
    for a,b in itertools.permutations(sampled, 2):
        start,end = mesh.centers[a],mesh.centers[b]
        # The geometric locator may choose a shared-boundary face; check actual choices.
        source,_=mesh.locate(start[0],start[2],height=start[1])
        target,_=mesh.locate(end[0],end[2],height=end[1])
        check = independent_cost(reference, source, target)
        try:
            route=mesh.route((start[0],start[2]),(end[0],end[2]),start[1],end[1])
        except NoPreviewRoute:
            if check['cost'] is not None:raise AssertionError('Reachable route rejected')
            rejected += 1
            continue
        if route['cost'] != check['cost'] or route['can_send_packets'] is not False:
            raise AssertionError('Wrong cost or unsafe route authority')
        if any(n not in reference.walkable for n in route['faces']):
            raise AssertionError('Route contains a forbidden node')
        if any(b not in reference.adjacency[a] for a,b in zip(route['faces'],route['faces'][1:])):
            raise AssertionError('Route contains a forbidden directed arc')
        successes += 1
    return dict(model=model,mode=mode,nodes=len(mesh.faces),allowed_nodes=len(nodes),
                allowed_arcs=sum(map(len,reference.adjacency.values())),
                tag_counts=dict(Counter(str((f//524288)%32) for _,f in mesh.metadata)),
                blocked_walkability=sum(not (f%2) for _,f in mesh.metadata),
                sampled_nodes=sampled,successful=successes,unreachable=rejected,
                status='no_eligible_nodes' if not nodes else 'checked',can_send_packets=False)


def explain_forbidden(decoded, nodes, edges, mode):
    tags={'land':{0,3},'sea':{2},'sky':{0,1,2,3}}[mode]
    base=Mesh(decoded['mesh']); reasons=Counter()
    for node in nodes:
        flags=base.metadata[node][1]
        if flags%2==0:reasons['walkability_bit_disabled']+=1
        if (flags//524288)%32 not in tags:reasons['travel_tag_excluded']+=1
    for a,b in edges:
        if b not in {t for t,_,_ in decoded['connections'][a]}:
            reasons['serialized_arc_missing']+=1
        if b not in base.adjacency[a]:reasons['shared_edge_missing']+=1
    return dict(reasons)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--controls',type=Path,required=True,help='Phase 58 shadow report')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    saved=json.loads((args.snapshot/'current-identity.json').read_text())
    identity=OfficialCatalogIdentity(saved['data_ver'],saved['exe_version'],tuple(PackageRevision(**p) for p in saved['packages']))
    stages=json.loads((args.snapshot/'current-stages.json').read_text())
    controls=json.loads(args.controls.read_text())
    if controls['catalog_key']!=identity.key:raise ValueError('Control report version mismatch')
    rows=[];causes=[]
    for model in sorted(set(REVIEWED_MODELS)-{10000,10004,10005}):
        decoded=load_cache(database_path(),identity.key,model)
        if decoded is None:raise ValueError('Verified official model unavailable')
        rows.extend(audit_model(decoded,model,mode) for mode in ('land','sea','sky'))
        for item in controls['comparisons']:
            result=item.get('same_geometry_control',{}).get('unfiltered_algorithm',{})
            if result.get('allowed_by_preview_graph') is not False:continue
            if stages[str(item['map_id'])]['model_id']!=model:continue
            causes.append(dict(map_id=item['map_id'],mode=item['travel_mode'],
                reasons=explain_forbidden(decoded,result['forbidden_nodes'],result['forbidden_edges'],item['travel_mode'])))
    report=dict(catalog_key=identity.key,can_send_packets=False,official_runtime_verified=False,
                rows=rows,forbidden_case_causes=causes)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(models=len(rows)//3,mode_rows=len(rows),successful=sum(r['successful'] for r in rows),
                         unreachable=sum(r['unreachable'] for r in rows),empty_modes=sum(r['status']=='no_eligible_nodes' for r in rows),causes=causes)))


if __name__=='__main__':main()
