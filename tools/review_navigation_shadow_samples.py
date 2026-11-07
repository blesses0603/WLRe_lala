"""Bounded offline diagnostics against an explicitly supplied historical snapshot.

Does not establish current CDN identity or official runtime equivalence.
Uses at most five sampled walkable nodes per reviewed model and travel mode.
"""
import argparse
from pathlib import Path
import json,itertools
from types import SimpleNamespace
from wlre.services.world.navigation_preview import PreviewRepository, NoPreviewRoute
from wlre.services.world.navigation_database import REVIEWED_MODELS, load_cache, database_path
from wlre.services.world.catalog_identity import OfficialCatalogIdentity,PackageRevision
from wlre.services.world.navigation_shadow import compare
from tools.navigation_same_geometry_control import compare_algorithms

def verify_disconnected(mesh, details):
    """Independent unweighted reachability check; no cost/search-queue reuse."""
    source, target = details['source_node'], details['target_node']
    pending = [source]; seen = {source}
    while pending:
        node = pending.pop()
        for neighbor, _, _ in mesh.serialized_connections[node]:
            if neighbor in mesh.adjacency[node] and neighbor not in seen:
                seen.add(neighbor); pending.append(neighbor)
    if target in seen or len(seen) != details['reachable_nodes']:
        raise AssertionError('No-route result disagrees with independent reachability')
    return dict(source_node=source, target_node=target, reachable_nodes=len(seen),
                target_reachable=False, method='unweighted_graph_traversal')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True,help='Directory containing current-identity.json and current-stages.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    base=args.snapshot;saved=json.loads((base/'current-identity.json').read_text());identity=OfficialCatalogIdentity(saved['data_ver'],saved['exe_version'],tuple(PackageRevision(**p) for p in saved['packages']))
    stages={int(k):v for k,v in json.loads((base/'current-stages.json').read_text()).items()};repo=PreviewRepository(identity,stages);rows=[];comparisons=[]
    runtime=SimpleNamespace(catalog_identity=identity,stages=stages)
    for model in (m for m in REVIEWED_MODELS if m not in (10000,10004,10005)):
     for mode in ('land','sea','sky'):
      mesh,origin=repo.load(model,travel_mode=mode);nodes=sorted(mesh.walkable);sample=nodes[::max(1,len(nodes)//4)][:5];ok=0;rejected={}
      for a,b in itertools.combinations(sample,2):
       start,end=mesh.centers[a],mesh.centers[b]
       try:
        route=mesh.route((start[0],start[2]),(end[0],end[2]),start[1],end[1])
        assert route['can_send_packets'] is False and route['travel_mode']==mode
        assert all(n in mesh.walkable for n in route['faces'])
        ok+=1
       except NoPreviewRoute as error:
        verify_disconnected(mesh,error.details)
        rejected['verified_preview_graph_disconnected']=rejected.get('verified_preview_graph_disconnected',0)+1
      rows.append(dict(model=model,mode=mode,nodes=len(nodes),successful=ok,rejected=rejected))
      if len(sample)>1:
       map_id=next(k for k,v in stages.items() if v['model_id']==model)
       offset=6992 if stages[map_id]['map_height']==65535 else stages[map_id]['map_height']
       def packet(node):
        p=mesh.centers[node];return ((p[0]+origin[0])/10,offset-(p[2]+origin[2])/10)
       try:
        result=compare(map_id,packet(sample[0]),packet(sample[-1]),travel_mode=mode,runtime_getter=lambda:runtime)
        result['input_xy']={'start':packet(sample[0]),'end':packet(sample[-1])}
        if result.get('official',{}).get('status')=='no_route':
         result['no_route_check']=verify_disconnected(mesh,result['official']['details'])
        if result.get('status')=='incomplete':
         decoded=load_cache(database_path(),identity.key,model)
         result['same_geometry_control']=compare_algorithms(decoded,stages[map_id],packet(sample[0]),packet(sample[-1]),travel_mode=mode)
        comparisons.append(result)
       except ValueError as e:comparisons.append(dict(map_id=map_id,mode=mode,error=str(e)))
    report=dict(context='Historical pinned cached identity and stages; no current CDN or live state claim',catalog_key=identity.key,rows=rows,comparisons=comparisons)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(dict(models=17,mode_rows=len(rows),successful=sum(r['successful'] for r in rows),rejected=sum(sum(r['rejected'].values()) for r in rows),comparisons=len(comparisons),comparison_statuses={s:sum(r.get('status')==s for r in comparisons) for s in ('compared','incomplete','stale')})))


if __name__ == "__main__":
    main()
