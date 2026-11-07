"""Deterministic synthetic vectors executed by the retained Python navigation core.

No game assets, network, database reads, movement transport or live accounts.
Regenerate from repository root: python dotnet/Lala.Core.Tests/World/generate_navigation_vectors.py
"""
from copy import deepcopy
from pathlib import Path
import json
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from wlre.services.world.navigation import Mesh
from wlre.services.world.navigation_preview import PreviewMesh
from wlre.services.world.navigation_funnel import covered, smooth_corridor
from wlre.services.world.navigation_motion_safety import check_preview, exact_waypoint_step

cases = []


def tile(triangles, metadata=None):
    vertices = [list(v) for tri in triangles for v in tri]
    result = dict(vertices_b_int3=vertices, triangles=[list(range(i, i + 3)) for i in range(0, len(vertices), 3)])
    if metadata is not None:
        result['node_metadata'] = metadata
    return result


def data(triangles, flags=None, penalties=None):
    count = len(triangles)
    metadata = None if flags is None else [[p, f] for p, f in zip(penalties or [0] * count, flags)]
    return dict(tiles=[tile(triangles, metadata)])


def official(triangles, flags=None, penalties=None):
    mesh = data(triangles, flags if flags is not None else [1] * len(triangles), penalties)
    base = Mesh(mesh)
    connections = [[[target, 100, 0] for target in targets] for targets in base.adjacency.values()]
    return dict(mesh=mesh, connections=connections)


def create(case):
    result = PreviewMesh(case['official'], travel_mode=case.get('mode', 'land')) if 'official' in case else Mesh(case['mesh'])
    result.scene_id = 'M00042'
    return result


def add(name, operation, **input):
    case = dict(name=name, operation=operation, **deepcopy(input))
    try:
        if operation in ('mesh', 'locate', 'route', 'safety'):
            mesh = create(case)
        if operation == 'mesh':
            expected = dict(faces=mesh.faces, metadata=mesh.metadata, centers=mesh.centers,
                            adjacency=mesh.adjacency, nonmanifold_edges=mesh.nonmanifold_edges)
            if isinstance(mesh, PreviewMesh):
                expected['walkable'] = sorted(mesh.walkable)
                expected['travel_mode'] = mesh.travel_mode
        elif operation == 'locate':
            face, point = mesh.locate(*case['coordinate'], height=case.get('height'))
            expected = dict(face=face, point=point)
        elif operation == 'route':
            options = dict(start_height=case.get('start_height'), end_height=case.get('end_height'))
            if isinstance(mesh, PreviewMesh):
                options['smooth'] = case.get('smooth', False)
            expected = mesh.route(case['start'], case['end'], **options)
        elif operation == 'covered':
            expected = covered(case['a'], case['b'], case['triangles'])
        elif operation == 'smooth':
            expected = smooth_corridor(case['triangles'], case['start'], case['end'])
        elif operation == 'step':
            expected = exact_waypoint_step(case['points'], case['index'], case['position'], case['distance'])
        elif operation == 'safety':
            expected = check_preview(mesh, case['route'], case['segments'], catalog_key=case.get('catalog', 'synthetic'),
                                     expected_catalog_key=case.get('expected_catalog', 'synthetic'))
        else:
            raise AssertionError(operation)
        case['expected'] = expected
    except ValueError as error:
        case['error'] = str(error)
        if hasattr(error, 'details'):
            case['details'] = error.details
    cases.append(case)


square = [[(0, 0, 0), (1000, 0, 0), (0, 0, 1000)], [(1000, 0, 0), (1000, 0, 1000), (0, 0, 1000)]]
base = data(square)
add('square-mesh', 'mesh', mesh=base)
add('cross-tile-shared-edge', 'mesh', mesh=dict(tiles=[tile([square[0]]), tile([square[1]])]))
add('empty-mesh', 'mesh', mesh=data([]))
add('empty-location', 'locate', mesh=data([]), coordinate=[0, 0])
for coordinate in ([100, 100], [900, 900], [500, 500], [0, 0], [1000, 1000], [-0.000001, 0], [-0.1, 0]):
    add(f'locate-{coordinate}', 'locate', mesh=base, coordinate=coordinate)
for start, end in (([100, 100], [900, 900]), ([900, 900], [100, 100]), ([500, 500], [500, 500]), ([100, 100], [200, 200])):
    add(f'base-route-{start}-{end}', 'route', mesh=base, start=start, end=end)

raised = [[(x, 500, z) for x, _, z in t] for t in square]
stacked = data(square + raised)
for height in (None, 10, 250, 490, 900):
    add(f'stacked-height-{height}', 'locate', mesh=stacked, coordinate=[100, 100], height=height)
add('different-floors-disconnected', 'route', mesh=stacked, start=[100, 100], end=[900, 900], start_height=0, end_height=500)
sloped = data([[(0, 0, 0), (1000, 500, 0), (0, 1000, 1000)]])
add('slope-interpolates-height', 'locate', mesh=sloped, coordinate=[200, 300])
add('skip-degenerate-and-retain-metadata', 'mesh', mesh=data([[(0, 0, 0), (0, 1, 0), (0, 0, 1)]] + square,
    [1, 1, 1], [7, 20, 30]))
nonmanifold = square + [[(1000, 0, 0), (0, 0, 1000), (900, 0, 900)]]
add('ambiguous-edge-not-connected', 'mesh', mesh=data(nonmanifold))
add('nonmanifold-no-route', 'route', mesh=data(nonmanifold), start=[100, 100], end=[950, 950])
add('overlap-not-shared-edge', 'mesh', mesh=data([square[0], [(0, 1, 0), (1000, 1, 0), (0, 1, 1000)]]))

for mode in ('land', 'sea', 'sky', 'unsupported'):
    for tag in range(5):
        model = official(square, [1 | (tag << 19)] * 2, [31, 17])
        add(f'mode-{mode}-tag-{tag}', 'mesh', official=model, mode=mode)
        if mode != 'unsupported':
            add(f'route-{mode}-tag-{tag}', 'route', official=model, mode=mode, start=[100, 100], end=[900, 900])
for bits in (0, 1, (1 << 31) | 1, (31 << 19) | 1):
    add(f'flag-bits-{bits}', 'mesh', official=official(square, [bits, 1]))
add('official-degenerate-count', 'mesh', official=dict(mesh=data([[(0, 0, 0), (0, 1, 0), (0, 0, 1)]], [1]), connections=[[]]))
add('blocked-shared-edge-first-hit', 'locate', official=official(square, [0, 1]), coordinate=[500, 500])
directed = official(square)
directed['connections'][1] = []
for start, end in (([100, 100], [900, 900]), ([900, 900], [100, 100])):
    add(f'directed-{start}', 'route', official=directed, start=start, end=end)
for cost, penalty in ((0xffffffff, 0), (0xffffffff, 1), (100, 0xffffffff)):
    model = official(square, penalties=[9, penalty]); model['connections'][0][0][1] = cost
    add(f'cost-boundary-{cost}-{penalty}', 'route', official=model, start=[100, 100], end=[900, 900])
model = official(square, penalties=[900, 17]); model['connections'][0] = [[1, 100, 0], [1, 3, 0], [999, 1, 0]]
add('duplicate-arcs-cheapest-and-ignore-nongeometric', 'route', official=model, start=[100, 100], end=[900, 900])

# Deterministic small grids exercise A*, alternative routes, heap ties, stale queue entries and directed costs.
for seed in range(16):
    rng = random.Random(seed)
    triangles = []
    for z in range(3):
        for x in range(3):
            a, b, c, d = (x*100, 0, z*100), ((x+1)*100, 0, z*100), (x*100, 0, (z+1)*100), ((x+1)*100, 0, (z+1)*100)
            triangles.extend([[a, b, c], [b, d, c]])
    start = [rng.randint(1, 99), rng.randint(1, 99)]; end = [rng.randint(201, 299), rng.randint(201, 299)]
    add(f'grid-base-{seed}', 'route', mesh=data(triangles), start=start, end=end)
    model = official(triangles, penalties=[rng.randint(0, 300) for _ in triangles])
    for row in model['connections']:
        for arc in row:
            arc[1] = rng.randint(0, 200)
        if seed % 3 == 0 and row:
            row.pop(0)
    add(f'grid-official-{seed}', 'route', official=model, start=start, end=end, smooth=seed % 2 == 0)

corner = [[(0, 0, 0), (2, 0, 0), (0, 0, 1)], [(2, 0, 0), (1, 0, 1), (0, 0, 1)],
          [(2, 0, 0), (2, 0, 1), (1, 0, 1)], [(1, 0, 1), (2, 0, 1), (2, 0, 3)]]
for triangles, start, end, label in ((square, (100, 0, 100), (900, 0, 900), 'square'),
    (list(reversed(square)), (900, 0, 900), (100, 0, 100), 'reverse'),
    ([list(reversed(t)) for t in square], (100, 0, 100), (900, 0, 900), 'winding'),
    (corner, (.1, 0, .5), (1.9, 0, 2.8), 'corner'),
    (list(reversed(corner)), (1.9, 0, 2.8), (.1, 0, .5), 'reverse-corner')):
    add(f'funnel-{label}', 'smooth', triangles=triangles, start=start, end=end)
    add(f'coverage-{label}', 'covered', triangles=triangles, a=start, b=end)
for label, triangles, start, end in (
    ('empty', [], (0, 0, 0), (0, 0, 0)),
    ('too-many', [square[0]] * 513, (0, 0, 0), (0, 0, 0)),
    ('nonplanar', [[(0, 0, 0), (1, 1, 0), (0, 0, 1)]], (0, 0, 0), (.1, 0, .1)),
    ('degenerate', [[(0, 0, 0), (1, 0, 0), (2, 0, 0)]], (0, 0, 0), (1, 0, 0)),
    ('outside', square, (-1, 0, -1), (900, 0, 900)),
    ('disconnected', [square[0], [(2000, 0, 2000), (3000, 0, 2000), (2000, 0, 3000)]], (100, 0, 100), (2100, 0, 2100)),
    ('duplicate-triangles', [square[0], square[0]], (100, 0, 100), (200, 0, 200))):
    add(f'funnel-reject-{label}', 'smooth', triangles=triangles, start=start, end=end)
for a, b in (((0, 0, 0), (1000, 0, 0)), ((100, 0, 100), (2000, 0, 2000)), ((0, 0, 0), (0, 0, 0))):
    add(f'coverage-edge-{a}-{b}', 'covered', triangles=[square[0]], a=a, b=b)
add('coverage-empty', 'covered', triangles=[], a=(0, 0, 0), b=(0, 0, 0))
add('coverage-gap', 'covered', triangles=[[(0, 0, 0), (1, 0, 0), (0, 0, 1)], [(2, 0, 0), (3, 0, 0), (2, 0, 1)]], a=(0, 0, 0), b=(3, 0, 0))

points = [(0, 0, 0), (100, 0, 0), (100, 0, 100)]
for distance in (0, .25, 99.999, 100, 101, 200, 201, 1e9, -1, 1e9 + 1):
    add(f'step-distance-{distance}', 'step', points=points, index=0, position=points[0], distance=distance)
for index in (-1, 1, 2):
    add(f'step-index-{index}', 'step', points=points, index=index, position=points[min(max(0,index),2)], distance=50)
add('step-position-outside', 'step', points=points, index=0, position=(50, 0, 1), distance=10)
add('step-position-midway', 'step', points=points, index=0, position=(50, 0, 0), distance=125)
add('step-duplicate-waypoints', 'step', points=[points[0], points[0], *points[1:]], index=0, position=points[0], distance=110)
add('step-all-duplicates', 'step', points=[points[0]]*512, index=0, position=points[0], distance=0)
add('step-too-many', 'step', points=[points[0]]*513, index=0, position=points[0], distance=1)
add('step-short-path', 'step', points=[points[0]], index=0, position=points[0], distance=0)
add('step-nonplanar', 'step', points=[points[0], (100, 1, 0)], index=0, position=points[0], distance=10)

# A corridor with an elbow: exact waypoint segments stay inside; a diagonal cuts the missing square.
a,b,c,d,e,f,g,h=(0,0,0),(800,0,0),(800,0,200),(0,0,200),(1000,0,0),(1000,0,200),(800,0,1000),(1000,0,1000)
surface = official([[a,b,c],[a,c,d],[b,e,f],[b,f,c],[c,f,h],[c,h,g]])
route = dict(points=[(100,0,100),(900,0,200),(900,0,900)], faces=[1,0,3,4,5], can_send_packets=False)
segments = list(zip(route['points'],route['points'][1:]))

def safety(name, mutate=None, **options):
    values = dict(official=deepcopy(surface), route=deepcopy(route), segments=deepcopy(segments))
    values.update(options)
    if mutate:
        mutate(values)
    add('safety-'+name, 'safety', **values)

safety('contained')
safety('unsafe-modeled-shortcut', segments=[(route['points'][0],route['points'][-1])])
safety('catalog-mismatch', catalog='old', expected_catalog='new')
safety('catalog-empty', catalog='')
safety('claims-authority', lambda v: v['route'].update(can_send_packets=True))
safety('missing-authority', lambda v: v['route'].pop('can_send_packets'))
safety('invalid-points', lambda v: v['route'].update(points=[]))
safety('too-many-points', lambda v: v['route'].update(points=[route['points'][0]]*513))
safety('forbidden-face', lambda v: v['route'].update(faces=[99]))
safety('empty-faces', lambda v: v['route'].update(faces=[]))
safety('too-many-faces', lambda v: v['route'].update(faces=[0]*513))
safety('forbidden-connection', lambda v: v['route'].update(faces=[1,4]))
safety('nonplanar', lambda v: v['route'].update(points=[(100,0,100),(900,1,200),(900,0,900)]))
safety('wrong-plane', lambda v: v['route'].update(points=[(x,1,z) for x,y,z in route['points']]))
safety('too-many-segments', segments=[segments[0]]*513)
safety('endpoint-outside', lambda v: v['route'].update(points=[(-10,0,100),*route['points'][1:]]))
safety('ideal-shortcut', lambda v: v['route'].update(points=[route['points'][0],route['points'][-1]]))
safety('empty-motion', segments=[])
safety('nonplanar-motion', segments=[(route['points'][0],(900,1,900))])
safety('discontinuous-start', segments=[((110,0,100),route['points'][-1])])
safety('discontinuous-middle', segments=[segments[0],((900,0,201),route['points'][-1])])
safety('endpoint-too-far', segments=[(route['points'][0],route['points'][1])])
for short in (400, 400.000001, 400.00001):
    safety(f'endpoint-threshold-{short}', segments=[segments[0],(route['points'][1],(900,0,900-short))])
# Compact case expansion keeps the checked-in C# vector file small while testing geometry budgets.
for count, point_count in ((10001,2),(4000,501)):
    values=dict(official=official([square[0]]*count), route=dict(points=[(100,0,100)]*point_count,faces=[0],can_send_packets=False), segments=[((100,0,100),(100,0,100))])
    add(f'safety-geometry-budget-{count}-{point_count}', 'safety', **values)
    cases[-1]['official'] = official([square[0]])
    cases[-1]['repeat_triangles'] = count

lines = ['// Generated by generate_navigation_vectors.py from retained Python and synthetic data only.',
         'namespace Lala.Core.Tests.World;', 'public static class PythonNavigationVectors', '{',
         '    public static IEnumerable<object[]> Cases()', '    {']
for case in cases:
    encoded = json.dumps(case, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    lines.append('        yield return new object[] { '+json.dumps(case['name'], ensure_ascii=False)+', '+json.dumps(encoded, ensure_ascii=False)+' };')
lines.extend(['    }', '}'])
Path(__file__).with_name('PythonNavigationVectors.cs').write_text('\n'.join(lines)+'\n', encoding='utf-8')
from collections import Counter
print(f'{len(cases)} synthetic navigation vectors: {dict(Counter(c["operation"] for c in cases))}')
