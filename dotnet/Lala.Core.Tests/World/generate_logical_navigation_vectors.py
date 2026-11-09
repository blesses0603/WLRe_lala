"""Real PreviewRepository.route oracle over injected synthetic cache results only.

No assets, database/network access, cache integrity/provenance claim, or downloads.
The fixed coordinate key is a CLAIM on synthetic data, not trusted provenance.
Alias success privately substitutes a synthetic order digest in Python and the C#
internal test constructor. Production pins and all public APIs remain unchanged.
Run from repository root with PYTHONDONTWRITEBYTECODE=1 python <this file>.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from wlre.services.world import house_navigation, navigation_preview
from wlre.services.world.navigation import NavigationError
from wlre.services.world import navigation_funnel
from wlre.storage import paths

KEY = next(iter(navigation_preview.REVIEWED_COORDINATE_CATALOGS))
cases = []


def geometry(height=0, flags=1, connected=True, stacked=False):
    vertices = [[0, height, 0], [100, height, 0], [100, height, 100], [0, height, 100]]
    triangles = [[0, 1, 2], [0, 2, 3]]
    metadata = [[3, flags], [7, flags]]
    connections = [[[1, 23, 0]], [[0, 41, 0]]] if connected else [[], []]
    if stacked:
        vertices += [[x, y+100, z] for x, y, z in vertices]
        triangles += [[4, 5, 6], [4, 6, 7]]
        metadata *= 2
        connections += [[[3, 23, 0]], [[2, 41, 0]]]
    return dict(mesh=dict(tiles=[dict(vertices_b_int3=vertices, triangles=triangles,
                                    node_metadata=metadata)]), connections=connections)


def add(name, *, stages=None, logical_map=200, origin=(0, 0, 0), map_height=100,
        model=42, key=KEY, cache=True, mode='land', flags=1, connected=True,
        mesh_height=0, stacked=False, smooth=False, navigation=None,
        start_mesh=(80, 20), end_mesh=(20, 80), start_height=None, end_height=None,
        synthetic_order=False, expected_order=None):
    rows = stages or [dict(id=200, model_id=model, map_height=map_height, max_members=0, room_capacity=0)]
    rows = deepcopy(rows)
    for row in rows:
        row.setdefault('model_id', 42); row.setdefault('map_height', map_height)
        row.setdefault('max_members', 0); row.setdefault('room_capacity', 0)
    order = hashlib.sha256(json.dumps([s['id'] for s in rows], separators=(',', ':')).encode()).hexdigest()
    offset = 6992 if map_height == 65535 else map_height
    logical = lambda point: [(point[0]+origin[0])/10, offset-(point[1]+origin[2])/10]
    result = geometry(mesh_height, flags, connected, stacked)
    result['origin'] = list(origin)
    case = dict(name=name, claimed_manifest_key=key, data_version='synthetic-1.2.3', stages=rows,
                logical_map=logical_map, model=model, origin=list(origin), geometry=result,
                cache=cache, mode=mode, smooth=smooth, navigation=navigation,
                start=logical(start_mesh), end=logical(end_mesh),
                start_height=start_height, end_height=end_height)
    if synthetic_order:
        case['synthetic_reviewed_order'] = expected_order or order
    requested = []

    def load_cache(path, catalog_key, requested_model):
        requested.append([catalog_key, requested_model])
        assert str(path) == '/__offline_synthetic_no_io__/derived_catalogs/navigation.sqlite3'
        return deepcopy(result) if cache and catalog_key == key and requested_model == model else None

    def forbidden(*args, **kwargs):
        raise AssertionError('Oracle attempted I/O')

    with ExitStack() as stack:
        stack.enter_context(patch.object(navigation_preview, 'load_cache', load_cache))
        stack.enter_context(patch('builtins.open', forbidden))
        stack.enter_context(patch.object(Path, 'open', forbidden))
        stack.enter_context(patch.object(sqlite3, 'connect', forbidden))
        stack.enter_context(patch.object(socket, 'socket', forbidden))
        if synthetic_order:
            stack.enter_context(patch.object(house_navigation, 'REVIEWED_STAGE_ORDER', expected_order or order))
        repository = navigation_preview.PreviewRepository(SimpleNamespace(key=key, data_ver=case['data_version']),
            {s['id']: {k: v for k, v in s.items() if k != 'id'} for s in rows}, root='/__offline_synthetic_no_io__')
        try:
            answer = repository.route(logical_map, case['start'], case['end'], download=False,
                start_height=start_height, end_height=end_height, navigation_state=navigation,
                travel_mode=mode, smooth=smooth)
            case['expected'] = {k: answer[k] for k in ('logical_map', 'catalog_key', 'scene_resource', 'points', 'faces',
                'length', 'cost', 'travel_mode', 'smoothing_applied', 'packet_points_xy_float', 'can_send_packets',
                'live_movement_verified', 'network_coordinates_verified', 'runtime_obstacles_applied')}
        except NavigationError as error:
            case['error'] = str(error)
    case['cache_reads'] = requested
    cases.append(case)


add('ordinary')
add('fractional-nonzero-origin', origin=(123.5, 987.25, -456.25), start_mesh=(83.125, 22.75), end_mesh=(21.25, 81.875))
for height in (0, 65534, 65535):
    add(f'map-height-{height}', map_height=height, origin=(-123.5, -400, 93.25))
add('negative-logical-coordinates', origin=(-200, 20, 200), map_height=0)
add('mesh-height-hints-unshifted', origin=(10, 900, 20), stacked=True, start_height=100, end_height=100)
add('stacked-without-height-rejected', stacked=True)
add('smooth', smooth=True)
add('same-point', end_mesh=(80, 20))
add('sea', mode='sea', flags=1 | (2 << 19))
add('sky', mode='sky', flags=1 | (1 << 19))
add('land-forbids-sea', flags=1 | (2 << 19))
add('unwalkable', flags=0)
add('disconnected', connected=False)
add('outside-mesh', end_mesh=(200, 200))
add('missing-cache', cache=False)
add('missing-stage', logical_map=201)
add('missing-exact-model', stages=[dict(id=200, model_id=43)])
add('unknown-coordinate-key', key='0'*64)
add('key-before-house', key='0'*64, logical_map=63501)
add('matching-stale', navigation=dict(scene=200, stale=True, revision=19))
add('different-scene-stale', navigation=dict(scene=201, stale=True, revision=19))
add('nonstale', navigation=dict(scene=200, stale=False, revision=20))
for scene in (10000, 10298, 10299, 63501, 65500):
    add(f'house-scene-{scene}', logical_map=scene, navigation=dict(scene=scene, stale=True))
for model in (10000, 10004, 10005):
    add(f'house-model-{model}', model=model)
add('not-house-scene-10004', logical_map=10004, stages=[dict(id=10004)])
add('direct-alias-range-row', logical_map=61501, stages=[dict(id=61501)])
add('unreviewed-alias-order', logical_map=61501, stages=[dict(id=200, max_members=4, room_capacity=2)])
alias_rows = [dict(id=200, max_members=4, room_capacity=2), dict(id=100, max_members=4, room_capacity=1)]
for scene in (61501, 61502, 61503, 61504):
    add(f'synthetic-alias-{scene}', stages=alias_rows, logical_map=scene, synthetic_order=True)
add('alias-stale-request-id', stages=alias_rows, logical_map=61501, synthetic_order=True, navigation=dict(scene=61501, stale=True))
add('alias-stale-resolved-id-ignored', stages=alias_rows, logical_map=61501, synthetic_order=True, navigation=dict(scene=200, stale=True))
original_order = hashlib.sha256(b'[200,100]').hexdigest()
add('sorted-alias-order-rejected', stages=list(reversed(alias_rows)), logical_map=61501,
    synthetic_order=True, expected_order=original_order)
add('alias-collision', stages=[dict(id=200, max_members=4, room_capacity=2), dict(id=61501)], logical_map=61502, synthetic_order=True)
add('alias-overflow', stages=[dict(id=200, max_members=4, room_capacity=255), dict(id=100, max_members=4, room_capacity=246)],
    logical_map=61501, synthetic_order=True)
add('exact-alias-limit', stages=[dict(id=200, max_members=4, room_capacity=250), dict(id=100, max_members=4, room_capacity=250)],
    logical_map=62000, synthetic_order=True)
add('zero-members-no-alias', stages=[dict(id=200, max_members=0, room_capacity=255)], logical_map=61501, synthetic_order=True)
add('alias-house-model', stages=[dict(id=200, model_id=10004, max_members=4, room_capacity=1)], logical_map=61501, synthetic_order=True)

lines = ['// Generated by generate_logical_navigation_vectors.py; synthetic claims, not trusted provenance.',
         'namespace Lala.Core.Tests.World;', 'public static class PythonLogicalNavigationVectors', '{',
         '    public static IEnumerable<object[]> Cases()', '    {']
for case in cases:
    encoded = json.dumps(case, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    lines.append('        yield return new object[] { '+json.dumps(case['name'])+', '+json.dumps(encoded, ensure_ascii=False)+' };')
lines.extend(['    }', '}'])
Path(__file__).with_name('PythonLogicalNavigationVectors.cs').write_text('\n'.join(lines)+'\n', encoding='utf-8')
print(f'{len(cases)} actual Python cache-only logical route oracle cases')
