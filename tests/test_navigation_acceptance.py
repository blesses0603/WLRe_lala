import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from tools.navigation.acceptance import review, settings_review
from tools.navigation.scan import ScanError
from tools.navigation.unity_bundle_geometry import candidate_settings
from test_recast_scan import floors


def graph():
    return {'rotation': dict(x=0, y=0, z=0), 'cellSize': .1, 'walkableHeight': 1.8,
            'walkableClimb': .3, 'characterRadius': .3, 'maxSlope': 45,
            'maxEdgeLength': 12, 'contourMaxError': 1.3,
            'forcedBoundsCenter': dict(x=5, y=4, z=5),
            'forcedBoundsSize': dict(x=12, y=10, z=12)}


class Acceptance(unittest.TestCase):
    def inputs(self):
        geometry = floors([0])
        geometry['source'] = {'model_id': '12170'}
        candidate = {'kind': 'offline_recast_candidate', 'resource_revision': 1275,
                     'can_send_packets': False, 'coordinate_space': 'unity_world_y_up',
                     'settings': candidate_settings(graph(), .05),
                     'source': copy.deepcopy(geometry['source']),
                     'vertices': geometry['vertices'], 'triangles': geometry['triangles'],
                     'input_sha256': hashlib.sha256(json.dumps(geometry, sort_keys=True).encode()).hexdigest()}
        evidence = {'schema_version': 1, 'resource_revision': 1275,
                    'capture_type': 'lala_passive_navigation_events', 'events': [], 'stages': {}}
        return geometry, candidate, evidence

    def run_review(self, geometry, candidate, evidence):
        with patch('tools.navigation.acceptance.verify_sources', return_value={'model_id': 12170}), \
             patch('tools.navigation.acceptance.extract', return_value={
                 'scenes': [{'model_id': 12170, 'settings': graph()}]}):
            return review(geometry, candidate, evidence, 'private.zip')

    def test_official_agent_parameters_do_not_prove_scan_equivalence(self):
        _, candidate, _ = self.inputs()
        result = settings_review(candidate, graph())
        self.assertTrue(result['official_parameter_mapping_matches'])
        self.assertFalse(result['settings_equivalence_verified'])
        candidate['settings']['agent_radius'] = 0
        self.assertIn('agent_radius', settings_review(candidate, graph())['mismatched_parameters'])

    def test_empty_evidence_cannot_satisfy_coordinate_acceptance(self):
        result = self.run_review(*self.inputs())
        self.assertIn('independent_coordinate_references', result['remaining_blockers'])
        self.assertIn('runtime_obstacle_rebuild_and_detour', result['remaining_blockers'])
        self.assertFalse(result['live_movement_verified'])
        self.assertFalse(result['can_send_packets'])
        self.assertEqual(result['mesh']['faces'], 2)

    def test_changed_geometry_and_changed_settings_are_rejected(self):
        geometry, candidate, evidence = self.inputs()
        geometry['vertices'] = copy.deepcopy(geometry['vertices'])
        geometry['vertices'][0][0] = .5
        with self.assertRaises(ScanError): self.run_review(geometry, candidate, evidence)
        geometry, candidate, evidence = self.inputs()
        candidate['settings']['agent_height'] = 1.7
        with self.assertRaises(ScanError): self.run_review(geometry, candidate, evidence)

    def test_outdated_or_executable_candidates_are_rejected(self):
        for key, value in [('resource_revision', 1262), ('can_send_packets', True)]:
            geometry, candidate, evidence = self.inputs()
            candidate[key] = value
            with self.assertRaises(ScanError): self.run_review(geometry, candidate, evidence)
