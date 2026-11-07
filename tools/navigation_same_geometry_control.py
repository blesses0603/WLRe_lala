"""Offline algorithm control on one verified official geometry, never legacy parity."""
from collections import deque
from wlre.services.world.navigation import Mesh, NavigationError
from wlre.services.world.navigation_preview import PreviewMesh, NoPreviewRoute


def independent_cost(mesh, source, target, *, max_relaxations=2_000_000):
    """FIFO label correction, independent of the preview's priority queue."""
    distance = {source: 0}; pending = deque([source]); queued = {source}; operations = 0
    while pending:
        node = pending.popleft(); queued.remove(node)
        for neighbor, cost, _ in mesh.serialized_connections[node]:
            operations += 1
            if operations > max_relaxations:
                raise ValueError('Independent control exceeded its fixed work budget')
            if neighbor not in mesh.adjacency[node]:
                continue
            value = distance[node] + cost + mesh.metadata[neighbor][0]
            if value < distance.get(neighbor, float('inf')):
                distance[neighbor] = value
                if neighbor not in queued:
                    pending.append(neighbor); queued.add(neighbor)
    return dict(cost=distance.get(target), reachable_nodes=len(distance), relaxations=operations)


def compare_algorithms(decoded, stage, start, end, *, travel_mode):
    """Both algorithms receive the same geometry and coordinate conversion.

    This cannot supply the missing historical baseline or official client output.
    """
    origin = decoded['origin']; height = stage['map_height']
    offset = 6992 if height == 65535 else height
    def convert(p):
        return p[0]*10-origin[0], (offset-p[1])*10-origin[2]
    start, end = convert(start), convert(end)
    plain = Mesh(decoded['mesh']); official = PreviewMesh(decoded, travel_mode=travel_mode)
    source, _ = official.locate(*start); target, _ = official.locate(*end)
    check = independent_cost(official, source, target)
    report = dict(comparison_kind='same_official_geometry_algorithm_control',
                  historical_parity_verified=False, official_runtime_verified=False,
                  can_send_packets=False, source_node=source, target_node=target,
                  independent_preview_cost=check)
    try:
        route = official.route(start, end)
        if route['cost'] != check['cost'] or route['can_send_packets'] is not False:
            raise AssertionError('Preview route disagrees with independent minimum cost')
        report['official'] = dict(status='ready', minimum_cost_checked=True,
                                  cost=route['cost'], face_count=len(route['faces']))
    except NoPreviewRoute:
        if check['cost'] is not None:
            raise AssertionError('Preview rejected an independently reachable target')
        route = None
        report['official'] = dict(status='no_route', disconnection_checked=True)
    try:
        legacy_algorithm = plain.route(start, end)
    except NavigationError as error:
        report['unfiltered_algorithm'] = dict(status='rejected', detail=str(error))
        return report
    faces = legacy_algorithm['faces']
    forbidden_nodes = [n for n in faces if n not in official.walkable]
    forbidden_edges = [[a,b] for a,b in zip(faces, faces[1:]) if b not in official.adjacency[a]]
    report['unfiltered_algorithm'] = dict(status='ready', face_count=len(faces),
        forbidden_nodes=forbidden_nodes, forbidden_edges=forbidden_edges,
        allowed_by_preview_graph=not forbidden_nodes and not forbidden_edges)
    if route is not None:
        report['same_face_sequence'] = faces == route['faces']
    return report
