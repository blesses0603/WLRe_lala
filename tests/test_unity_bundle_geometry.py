"""Terrain normalization, sampling and Transform regressions for real bundle extraction."""
import math
from types import SimpleNamespace as NS
import unittest
from tools.navigation.unity_bundle_geometry import terrain_surface,local_matrix,point,multiply,determinant
from tools.navigation.scan import ScanError


class TerrainGeometry(unittest.TestCase):
    def heightmap(self):
        return {'m_Resolution':2,'m_Heights':[0,32766,0,32766],
            'm_MinMaxPatchHeights':[0.,1.],'m_Scale':{'x':2.,'y':4.,'z':2.},'m_Holes':[],'m_HolesLOD':[]}
    def test_height_samples_match_patch_bounds_and_world_scale(self):
        vertices,triangles=terrain_surface(self.heightmap(),1)
        self.assertEqual(vertices,[[0,0,0],[2,4,0],[0,0,2],[2,4,2]])
        self.assertEqual(triangles,[[0,2,1],[1,2,3]])
    def test_terrain_normalization_cannot_be_guessed(self):
        h=self.heightmap();h['m_MinMaxPatchHeights']=[0.,.5]
        with self.assertRaises(ScanError):terrain_surface(h,1)
    def test_unknown_holes_are_not_ignored(self):
        h=self.heightmap();h['m_Holes']=[0]
        with self.assertRaises(ScanError):terrain_surface(h,1)
    def test_sampling_keeps_last_boundary_when_stride_does_not_divide_resolution(self):
        h=self.heightmap();h.update(m_Resolution=5,m_Heights=[0]*25,m_MinMaxPatchHeights=[0.,0.])
        vertices,_=terrain_surface(h,3)
        self.assertEqual(len(vertices),9);self.assertEqual(vertices[-1],[8.,0.,8.])
    def test_parent_rotation_scale_and_translation_are_composed(self):
        child=NS(m_LocalRotation=NS(x=0,y=0,z=0,w=1),m_LocalPosition=NS(x=1,y=0,z=0),m_LocalScale=NS(x=1,y=1,z=1))
        parent=NS(m_LocalRotation=NS(x=0,y=math.sqrt(.5),z=0,w=math.sqrt(.5)),m_LocalPosition=NS(x=5,y=0,z=5),m_LocalScale=NS(x=2,y=2,z=2))
        value=point(multiply(local_matrix(parent),local_matrix(child)),[0,0,0])
        for actual,expected in zip(value,[5,0,3]):self.assertAlmostEqual(actual,expected)
        parent.m_LocalScale.x=-2
        self.assertLess(determinant(local_matrix(parent)),0)


import importlib.util
import os
from pathlib import Path
import tempfile
from tools.navigation.unity_bundle_geometry import rebuild
from tools.navigation.scan import to_offline_mesh

@unittest.skipUnless(os.environ.get('LALA_1275_SCENES_ZIP') and os.environ.get('LALA_1275_SELECT_JSON')
                     and os.environ.get('WLRE_RECAST_SCANNER') and importlib.util.find_spec('UnityPy'),
                     'Requires verified private scene sources, UnityPy and native Recast scanner')
class Real1275Rebuild(unittest.TestCase):
    def test_all_available_models_build_and_route_without_fabricating_missing_builtin_mesh(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'candidates'
            result=rebuild(os.environ['LALA_1275_SCENES_ZIP'],os.environ['LALA_1275_SELECT_JSON'],
                           output,os.environ['WLRE_RECAST_SCANNER'],.05)
            self.assertEqual(result['built'],12);self.assertEqual(result['blocked'],1)
            blocked=[r for r in result['scenes'] if r['status']=='blocked']
            self.assertEqual(blocked[0]['model_id'],12910)
            self.assertIn('unity default resources',blocked[0]['reason'])
            for row in result['scenes']:
                if row['status']!='candidate_built':continue
                candidate=json.loads((output/f"{row['model_id']}_candidate.json").read_text())
                self.assertFalse(candidate['can_send_packets']);self.assertTrue(candidate['source_files_verified'])
                mesh=to_offline_mesh(candidate);self.assertTrue(mesh.faces)
                connected={0};stack=[0]
                while stack:
                    for neighbor in mesh.adjacency[stack.pop()]:
                        if neighbor not in connected:connected.add(neighbor);stack.append(neighbor)
                a=mesh.centers[0];b=mesh.centers[max(connected,key=lambda i:sum((mesh.centers[i][j]-a[j])**2 for j in range(3)))]
                route=mesh.route([a[0],a[2]],[b[0],b[2]],a[1],b[1])
                self.assertTrue(route['points'])

    @unittest.skipUnless(os.environ.get('LALA_1275_BUILTIN_RESOURCES'),'Requires reviewed Unity builtin resources')
    def test_builtin_mesh_source_completes_all_thirteen_real_scene_candidates(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'all-candidates'
            result=rebuild(os.environ['LALA_1275_SCENES_ZIP'],os.environ['LALA_1275_SELECT_JSON'],
                output,os.environ['WLRE_RECAST_SCANNER'],.05,os.environ['LALA_1275_BUILTIN_RESOURCES'])
            self.assertEqual(result['built'],13);self.assertEqual(result['blocked'],0)
            for row in result['scenes']:
                candidate=json.loads((output/f"{row['model_id']}_candidate.json").read_text())
                self.assertFalse(candidate['can_send_packets'])
                self.assertFalse(candidate['settings_equivalence_verified'])
                self.assertEqual(candidate['source']['builtin_resources']['unity_version'],'2021.3.43f1')
                mesh=to_offline_mesh(candidate)
                self.assertTrue(mesh.faces);self.assertEqual(mesh.nonmanifold_edges,0)
                connected={0};stack=[0]
                while stack:
                    for neighbor in mesh.adjacency[stack.pop()]:
                        if neighbor not in connected:connected.add(neighbor);stack.append(neighbor)
                a=mesh.centers[0]
                b=mesh.centers[max(connected,key=lambda i:sum((mesh.centers[i][j]-a[j])**2 for j in range(3)))]
                self.assertTrue(mesh.route([a[0],a[2]],[b[0],b[2]],a[1],b[1])['points'])


class BuiltinSourceValidation(unittest.TestCase):
    def test_unknown_builtin_source_cannot_complete_a_scene(self):
        from tools.navigation.unity_bundle_geometry import read_builtin
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'unity default resources';path.write_bytes(b'not the reviewed builtin source')
            with self.assertRaises(ScanError):read_builtin(path)


@unittest.skipUnless(os.environ.get('LALA_1275_CURRENT_SCENE_ZIP') and os.environ.get('LALA_1275_BUILTIN_RESOURCES')
                     and os.environ.get('WLRE_RECAST_SCANNER') and importlib.util.find_spec('UnityPy'),
                     'Requires private current-scene ZIP, builtin resources and scanner')
class RealCurrentScene(unittest.TestCase):
    def test_12170_source_rebuild_and_login_point_membership(self):
        import json
        from tools.navigation.verify_evidence import audit
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'current'
            result=rebuild(os.environ['LALA_1275_CURRENT_SCENE_ZIP'],None,output,
                os.environ['WLRE_RECAST_SCANNER'],.05,os.environ['LALA_1275_BUILTIN_RESOURCES'])
            self.assertEqual(result['built'],1);self.assertEqual(result['blocked'],0)
            candidate=json.loads((output/'12170_candidate.json').read_text())
            doc={'schema_version':1,'resource_revision':1275,'capture_type':'lala_passive_navigation_events',
                'events':[{'sequence':1,'kind':'position_fix','source':'S3-1','scene':12170,'x':6000,'y':3303}],
                'stages':{'12170':{'model_id':12170,'offset_y':6433}},'reference_points':[]}
            review=audit(doc,{12170},{12170:candidate})
            self.assertTrue(review['candidate_surface_checks'][0]['formula_prediction_on_candidate'])
            self.assertFalse(review['live_movement_verified']);self.assertFalse(review['can_send_packets'])
            mesh=to_offline_mesh(candidate);face,a=mesh.locate(60000,31300)
            connected={face};stack=[face]
            while stack:
                for neighbor in mesh.adjacency[stack.pop()]:
                    if neighbor not in connected:connected.add(neighbor);stack.append(neighbor)
            b=mesh.centers[max(connected,key=lambda i:sum((mesh.centers[i][j]-a[j])**2 for j in range(3)))]
            self.assertGreater(mesh.route([a[0],a[2]],[b[0],b[2]],a[1],b[1])['length'],1000)
            from tools.navigation.acceptance import review as acceptance_review
            acceptance=acceptance_review(json.loads((output/'12170_geometry.json').read_text()),candidate,doc,
                                         os.environ['LALA_1275_CURRENT_SCENE_ZIP'])
            self.assertTrue(acceptance['settings']['official_parameter_mapping_matches'])
            self.assertEqual(acceptance['mesh']['faces'],len(candidate['triangles']))
            self.assertIn('independent_coordinate_references',acceptance['remaining_blockers'])
            self.assertFalse(acceptance['can_send_packets'])
