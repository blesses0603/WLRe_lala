"""Real Recast regressions: slope, radius, overhead clearance and floor separation."""
import os
from pathlib import Path
import tempfile
import unittest
from tools.navigation.scan import bake,validate,ScanError,to_offline_mesh
from wlre.services.world.navigation import NavigationError


def settings():
    return {'cell_size':.1,'cell_height':.05,'agent_height':1.8,'agent_climb':.3,
        'agent_radius':.3,'max_slope':45,'max_edge_length':12,'max_simplification_error':1.3,
        'min_region_area':0,'merge_region_area':0,'detail_sample_distance':.6,
        'detail_sample_max_error':.05,'bounds_min':[-1,-1,-1],'bounds_max':[11,9,11]}


def floors(heights):
    vertices=[];triangles=[]
    for y in heights:
        i=len(vertices);vertices.extend([[0,y,0],[0,y,10],[10,y,0],[10,y,10]])
        triangles.extend([[i,i+1,i+2],[i+2,i+1,i+3]])
    return {'coordinate_space':'unity_world_y_up','vertices':vertices,'triangles':triangles}


class ScanInput(unittest.TestCase):
    def test_missing_agent_parameters_are_rejected(self):
        config=settings();config.pop('agent_radius')
        with self.assertRaises(ScanError):validate(floors([0]),config)
    def test_nonfinite_vertices_are_rejected(self):
        geometry=floors([0]);geometry['vertices'][0][0]=float('nan')
        with self.assertRaises(ScanError):validate(geometry,settings())
    def test_unbounded_voxel_grid_is_rejected(self):
        config=settings();config['cell_size']=.00001
        with self.assertRaises(ScanError):validate(floors([0]),config)


@unittest.skipUnless(os.environ.get('WLRE_RECAST_SCANNER'),'Build pinned Recast scanner for native integration tests')
class NativeRecast(unittest.TestCase):
    def scan(self,geometry,config=None):
        return bake(geometry,config or settings(),os.environ['WLRE_RECAST_SCANNER'])
    def test_plane_has_route_but_eroded_boundary_does_not(self):
        result=self.scan(floors([0]));self.assertTrue(result['triangles'])
        self.assertFalse(result['can_send_packets'])
        mesh=to_offline_mesh(result)
        self.assertTrue(mesh.route([2000,2000],[8000,8000])['points'])
        with self.assertRaises(NavigationError):mesh.locate(10,10)
    def test_separate_floors_do_not_join_in_xz(self):
        mesh=to_offline_mesh(self.scan(floors([0,4])))
        self.assertNotEqual(mesh.locate(5000,5000,height=0),mesh.locate(5000,5000,height=4000))
        with self.assertRaises(NavigationError):mesh.route([2000,2000],[8000,8000],0,4000)
    def test_low_ceiling_removes_lower_floor(self):
        mesh=to_offline_mesh(self.scan(floors([0,1])))
        heights=[center[1] for center in mesh.centers]
        self.assertTrue(heights);self.assertGreater(min(heights),900)
    def test_steep_slope_is_not_walkable(self):
        geometry=floors([0]);geometry['vertices'][2][1]=8;geometry['vertices'][3][1]=8
        config=settings();config['max_slope']=20
        self.assertEqual(self.scan(geometry,config)['triangles'],[])
    def test_downward_triangles_are_not_reinterpreted_as_walkable(self):
        geometry=floors([0]);geometry['triangles']=[list(reversed(t)) for t in geometry['triangles']]
        self.assertEqual(self.scan(geometry)['triangles'],[])

    def test_climb_limit_disconnects_a_high_step(self):
        geometry={'coordinate_space':'unity_world_y_up','vertices':[
            [0,0,0],[0,0,10],[5,0,0],[5,0,10],
            [5,2,0],[5,2,10],[10,2,0],[10,2,10]],
            'triangles':[[0,1,2],[2,1,3],[4,5,6],[6,5,7]]}
        mesh=to_offline_mesh(self.scan(geometry))
        with self.assertRaises(NavigationError):mesh.route([2000,5000],[8000,5000],0,2000)
    def test_low_step_within_climb_limit_remains_connected(self):
        geometry={'coordinate_space':'unity_world_y_up','vertices':[
            [0,0,0],[0,0,10],[5,0,0],[5,0,10],
            [5,.2,0],[5,.2,10],[10,.2,0],[10,.2,10]],
            'triangles':[[0,1,2],[2,1,3],[4,5,6],[6,5,7]]}
        mesh=to_offline_mesh(self.scan(geometry))
        self.assertTrue(mesh.route([2000,5000],[8000,5000],0,200)['points'])
    def test_radius_rejects_a_corridor_that_only_a_smaller_agent_can_pass(self):
        geometry={'coordinate_space':'unity_world_y_up','vertices':[
            [0,0,4.5],[0,0,5.5],[10,0,4.5],[10,0,5.5]],'triangles':[[0,1,2],[2,1,3]]}
        config=settings();config['agent_radius']=.1
        self.assertTrue(self.scan(geometry,config)['triangles'])
        config['agent_radius']=.6
        self.assertEqual(self.scan(geometry,config)['triangles'],[])

    def test_obstacle_addition_detours_and_removal_restores_the_route(self):
        from types import SimpleNamespace
        from tools.navigation.unity_bundle_geometry import box_surface
        geometry=floors([0])
        original=self.scan(geometry)
        direct=to_offline_mesh(original).route([2000,5000],[8000,5000])
        vertices,triangles=box_surface(SimpleNamespace(
            m_Center=SimpleNamespace(x=5,y=1.5,z=5),
            m_Size=SimpleNamespace(x=1,y=3,z=5)))
        offset=len(geometry['vertices'])
        blocked={'coordinate_space':'unity_world_y_up',
                 'vertices':geometry['vertices']+vertices,
                 'triangles':geometry['triangles']+[[i+offset for i in tri] for tri in triangles]}
        rebuilt=self.scan(blocked)
        detour=to_offline_mesh(rebuilt).route([2000,5000],[8000,5000],0,0)
        self.assertNotEqual(original['input_sha256'],rebuilt['input_sha256'])
        self.assertGreater(detour['length'],direct['length']+1000)
        self.assertTrue(any(point[2]<2500 or point[2]>7500 for point in detour['points']))
        restored=self.scan(geometry)
        restored_route=to_offline_mesh(restored).route([2000,5000],[8000,5000])
        self.assertEqual(original['input_sha256'],restored['input_sha256'])
        self.assertAlmostEqual(direct['length'],restored_route['length'])
        self.assertFalse(rebuilt['can_send_packets'])


class SourceVerification(unittest.TestCase):
    def test_wrong_export_provenance_cannot_claim_source_verification(self):
        from unittest.mock import patch
        from tools.navigation.scan import verify_sources
        report={'scenes':{'12910':{'scene':{'sha256':'a'*64},'dependency':{'sha256':'b'*64}}}}
        graph={'scenes':[{'model_id':12910,'embedded_zip_sha256':'c'*64}]}
        geometry={'source':{'model_id':'12910','scene_bundle_sha256':'a'*64,
                           'dependency_bundle_sha256':'b'*64,'graph_settings_sha256':'d'*64}}
        with patch('tools.resources.audit_1275_scene_collision.inspect',return_value=report),patch('tools.resources.extract_1275_recast_settings.extract',return_value=graph):
            with self.assertRaises(ScanError):verify_sources(geometry,'scene.zip','selection.json')
            geometry['source']['graph_settings_sha256']='c'*64
            evidence=verify_sources(geometry,'scene.zip','selection.json')
        self.assertTrue(evidence['source_files_verified'])
        self.assertFalse(evidence['geometry_export_verified'])
