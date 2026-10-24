"""Repeatable offline acceptance checks; this tool never authorizes movement."""
import argparse
import hashlib
import json
from pathlib import Path

from tools.navigation.scan import ScanError, to_offline_mesh, validate, verify_sources
from tools.navigation.unity_bundle_geometry import candidate_settings
from tools.navigation.verify_evidence import audit as audit_evidence
from tools.resources.extract_1275_recast_settings import extract


def settings_review(candidate, graph):
    """Distinguish copied official parameters from unverified conversions."""
    config = candidate['settings']
    expected = candidate_settings(graph, config['cell_height'])
    mismatches = [key for key in expected if config.get(key) != expected[key]]
    return {
        'official_parameter_mapping_matches': not mismatches,
        'mismatched_parameters': mismatches,
        'agent': {key: config[key] for key in
                  ('agent_height', 'agent_climb', 'agent_radius', 'max_slope')},
        'unverified_conversions': [
            'cell_height', 'min_region_area', 'merge_region_area',
            'detail_sample_distance', 'detail_sample_max_error',
            'Astar 4.3.60 versus upstream Recast 1.6.0 scan behavior',
        ],
        'settings_equivalence_verified': False,
    }


def component_routes(candidate):
    """Query a nonzero route inside each connected component where possible."""
    mesh = to_offline_mesh(candidate)
    if not mesh.faces:
        raise ScanError('Candidate has no walkable faces')
    if mesh.nonmanifold_edges:
        raise ScanError('Candidate has nonmanifold edges')
    remaining = set(range(len(mesh.faces)))
    reports = []
    while remaining:
        seed = min(remaining)
        connected = {seed}
        stack = [seed]
        while stack:
            for neighbor in mesh.adjacency[stack.pop()]:
                if neighbor not in connected:
                    connected.add(neighbor)
                    stack.append(neighbor)
        remaining.difference_update(connected)
        start = mesh.centers[seed]
        goal = mesh.centers[max(connected, key=lambda i: sum(
            (mesh.centers[i][axis] - start[axis]) ** 2 for axis in range(3)))]
        route = mesh.route([start[0], start[2]], [goal[0], goal[2]], start[1], goal[1])
        reports.append({'faces': len(connected), 'length_metres': route['length'] / 1000,
                        'path_points': len(route['points'])})
    return {'faces': len(mesh.faces), 'nonmanifold_edges': mesh.nonmanifold_edges,
            'components': reports}


def review(geometry, candidate, evidence, archive, selection=None):
    if (candidate.get('kind') != 'offline_recast_candidate'
            or candidate.get('resource_revision') != 1275
            or candidate.get('can_send_packets') is not False
            or candidate.get('coordinate_space') != 'unity_world_y_up'):
        raise ScanError('Expected a 1275 offline world-space candidate')
    validate(geometry, candidate['settings'])
    validate({'coordinate_space': 'unity_world_y_up', 'vertices': candidate['vertices'],
              'triangles': candidate['triangles']}, candidate['settings'])
    digest = hashlib.sha256(json.dumps(geometry, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if candidate.get('input_sha256') != digest or candidate.get('source') != geometry.get('source'):
        raise ScanError('Candidate does not match the supplied geometry and provenance')
    provenance = verify_sources(geometry, archive, selection)
    model = provenance['model_id']
    graph = next(row for row in extract(archive, selection)['scenes'] if row['model_id'] == model)
    settings = settings_review(candidate, graph['settings'])
    if not settings['official_parameter_mapping_matches']:
        raise ScanError('Candidate settings differ from the declared conversion')
    evidence_report = audit_evidence(evidence, {model}, {model: candidate})
    blockers = ['official_scan_equivalence', 'geometry_export_fidelity',
                'runtime_obstacle_rebuild_and_detour', 'server_confirmed_movement']
    references = evidence_report['coordinate_reference_checks']
    scenes = {row['scene'] for row in evidence_report['scene_candidate_coverage']}
    if (not scenes or scenes != {row['scene'] for row in references
                                 if row['reference_consistency'] == 'consistent'}
            or evidence_report['recording_truncated']):
        blockers.append('independent_coordinate_references')
    if any(row['candidate_available'] is False for row in evidence_report['scene_candidate_coverage']):
        blockers.append('scene_candidate_coverage')
    if any(not row['formula_prediction_on_candidate'] for row in evidence_report['candidate_surface_checks']):
        blockers.append('position_outside_candidate')
    return {'schema_version': 1, 'resource_revision': 1275, 'model_id': model,
            'source': provenance, 'settings': settings, 'mesh': component_routes(candidate),
            'evidence': evidence_report, 'remaining_blockers': blockers,
            'status': 'offline_checks_completed_live_acceptance_pending',
            'source_geometry_verified': False, 'dynamic_geometry_verified': False,
            'live_movement_verified': False, 'can_send_packets': False}


def main():
    parser = argparse.ArgumentParser(description='核對來源、設定、連通區與定位；不啟用行走')
    for name in ('geometry', 'candidate', 'evidence', 'scenes-zip', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--select', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    read = lambda path: json.loads(path.read_text(encoding='utf8'))
    result = review(read(args.geometry), read(args.candidate), read(args.evidence),
                    args.scenes_zip, args.select)
    with args.output.open('x', encoding='utf8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({'model_id': result['model_id'], 'status': result['status'],
                      'remaining_blockers': result['remaining_blockers']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
