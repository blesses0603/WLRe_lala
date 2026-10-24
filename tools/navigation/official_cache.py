"""Extract referenced official startup caches, preserving both Int3 vertex sets.

These are shipped scan snapshots, not a capture of a running client's graph.
No node flags, graph references, or coordinate-frame semantics are invented.
"""
import argparse
import base64
from collections import Counter
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from tools.resources.audit_1275_scene_collision import inspect
from tools.resources.extract_1275_recast_settings import load_scene_selection
from wlre.services.world.navigation import Mesh, NavigationError


from wlre.services.world.official_cache_format import CacheError, decode_cache, decode_extra


def compare(candidate, official):
    if (candidate.get('kind') != 'offline_recast_candidate' or candidate.get('resource_revision') != 1275
            or candidate.get('can_send_packets') is not False):
        raise CacheError('Expected a 1275 offline candidate')
    tile = official['mesh']['tiles'][0]
    vertices = [[round(v * 1000) for v in p] for p in candidate['vertices']]
    if any(len(t) != 3 or any(type(v) is not int or not 0 <= v < len(vertices) for v in t)
           for t in candidate['triangles']):
        raise CacheError('Invalid candidate triangle indices')
    def faces(points, triangles):
        return Counter(tuple(sorted(tuple(points[v]) for v in tri)) for tri in triangles)
    current = faces(vertices, candidate['triangles'])
    result = {'official_faces': len(tile['triangles']), 'candidate_faces': len(candidate['triangles']),
              'vertex_sets': {}, 'coordinate_frame_verified': False,
              'official_runtime_graph_captured': False, 'can_send_packets': False}
    candidate_mesh = Mesh({'tiles': [{'vertices_b_int3': vertices, 'triangles': candidate['triangles']}]})
    for name in ('vertices_a_int3', 'vertices_b_int3'):
        points = tile[name]
        source = faces(points, tile['triangles'])
        on_surface = 0
        height_errors = []
        mesh = Mesh({'tiles': [{'vertices_b_int3': points, 'triangles': tile['triangles']}]})
        for center in mesh.centers:
            try:
                _, predicted = candidate_mesh.locate(center[0], center[2], center[1])
                on_surface += 1
                height_errors.append(abs(predicted[1] - center[1]) / 1000)
            except NavigationError:
                pass
        result['vertex_sets'][name] = {
            'official_vertices': len(points), 'exact_matching_faces_mm': sum((source & current).values()),
            'same_triangle_geometry_mm': source == current,
            'official_face_centers_in_candidate_xz': on_surface,
            'official_non_vertical_faces': len(mesh.faces),
            'max_center_height_difference_metres': max(height_errors, default=None),
            'interpretation': 'raw serialized vertex set; coordinate frame still requires verification',
        }
    return result


def extract(archive, selection, output, candidate_dir=None):
    import UnityPy
    source_report = inspect(archive, selection)
    selection_data = load_scene_selection(archive, selection)
    root = Path(output)
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    reports = []
    with ZipFile(archive) as z:
        for model, pair in source_report['scenes'].items():
            env = UnityPy.Environment()
            for row in selection_data['bundles']:
                if row['bundle_name'] in (f'mainpackage_scene_{model}.bundle', f'mainpackage_scene_{model}_dependency.bundle'):
                    env.load_file(z.read('source/' + row['path']), name=row['bundle_name'])
            objects = list(env.objects)
            astars = []
            for obj in objects:
                if obj.type.name != 'MonoBehaviour':
                    continue
                d = obj.parse_as_dict()
                if 'scanOnStartup' in d and isinstance(d.get('data'), dict) and 'file_cachedStartup' in d['data']:
                    astars.append((obj, d))
            if len(astars) != 1:
                raise CacheError('Expected one serialized AstarPath startup cache reference')
            owner, astar = astars[0]
            data = astar['data']
            ptr = data['file_cachedStartup']
            file_id = ptr['m_FileID']
            if data.get('cacheStartup') != 1 or not 0 <= file_id <= len(owner.assets_file.externals):
                raise CacheError('No enabled, resolvable startup cache')
            cab = (owner.assets_file.name if file_id == 0 else
                   owner.assets_file.externals[file_id-1].path.replace('\\', '/').rsplit('/', 1)[-1])
            target = [obj for obj in objects if obj.assets_file.name == cab and obj.path_id == ptr['m_PathID']]
            if len(target) != 1 or target[0].type.name != 'TextAsset':
                raise CacheError('Startup cache TextAsset is not in the verified scene pair')
            text = target[0].parse_as_object()
            raw = text.m_Script.encode('utf8', 'surrogateescape') if isinstance(text.m_Script, str) else text.m_Script
            if text.m_Name != str(model):
                raise CacheError('Cache asset name does not match scene model')
            decoded = decode_cache(raw)
            embedded = base64.b64decode(data['dataString'], validate=True)
            with ZipFile(BytesIO(embedded)) as config_zip:
                scene_settings = json.loads(config_zip.read('graph0.json'))
            differences = {k: {'scene': scene_settings.get(k), 'cache': decoded['settings'].get(k)}
                           for k in scene_settings.keys() | decoded['settings'].keys()
                           if scene_settings.get(k) != decoded['settings'].get(k)}
            decoded['source'] = {'model_id': model, 'scene_bundle_sha256': pair['scene']['sha256'],
                                 'dependency_bundle_sha256': pair['dependency']['sha256'],
                                 'astar_path_id': owner.path_id, 'text_asset_path_id': target[0].path_id,
                                 'cacheStartup': data['cacheStartup'], 'scanOnStartup': astar['scanOnStartup']}
            decoded['scene_cache_settings_differences'] = differences
            (root / f'{model}_official_cache.zip').write_bytes(raw)
            (root / f'{model}_official_decoded.json').write_text(json.dumps(decoded, ensure_ascii=False, indent=2), encoding='utf8')
            row = {'model_id': model, 'cache_sha256': decoded['cache_sha256'],
                   'official_faces': len(decoded['mesh']['tiles'][0]['triangles']),
                   'settings_differences': differences, 'can_send_packets': False}
            if candidate_dir:
                candidate = json.loads((Path(candidate_dir) / f'{model}_candidate.json').read_text())
                if candidate.get('source', {}).get('scene_bundle_sha256') != pair['scene']['sha256']:
                    raise CacheError('Candidate scene source mismatch')
                row['comparison'] = compare(candidate, decoded)
            reports.append(row)
    result = {'resource_revision': 1275, 'scenes': reports, 'official_runtime_graph_captured': False,
              'serialized_connections_decoded': False, 'can_send_packets': False}
    (root / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    return result


def main():
    parser = argparse.ArgumentParser(description='提取官方場景所引用的 A* 掃描快取並對照候選網格')
    parser.add_argument('--scenes-zip', type=Path, required=True)
    parser.add_argument('--select', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--candidate-dir', type=Path)
    args = parser.parse_args()
    result = extract(args.scenes_zip, args.select, args.output, args.candidate_dir)
    print(json.dumps({'scenes': len(result['scenes']), 'can_send_packets': False}))


if __name__ == '__main__':
    main()
