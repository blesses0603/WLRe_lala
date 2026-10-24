"""Do not confuse local destinations, reversible formulas or invalidations with live proof."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from wlre.core.state import State
from wlre.services.world.navigation_evidence import export,LIMIT
from tools.navigation.verify_evidence import audit,EvidenceError


class PassiveCapture(unittest.TestCase):
    def setUp(self):
        self.state=State()
        self.state.apply({'type':'world_player','player':{'role_id':1,'name':'PRIVATE','scene':10000,'x':100,'y':200}})
    def test_only_own_fixes_are_captured_and_export_has_no_identity(self):
        self.state.apply({'type':'position_snapshot','role_id':2,'scene':10000,'x':300,'y':400,'source':'S7-1'})
        self.state.apply({'type':'position_snapshot','role_id':1,'scene':10000,'x':300,'y':400,'source':'S7-1'})
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=SimpleNamespace(stages={10000:{'model_id':13216,'offset_y':1000}})):
            doc=export(self.state.snapshot())
        self.assertEqual(len(doc['events']),2)
        self.assertNotIn('PRIVATE',str(doc));self.assertNotIn('role_id',str(doc))
        self.assertNotIn('player',doc);self.assertFalse(doc['can_send_packets'])
    def test_requests_and_s6_notices_do_not_count_as_position_fixes(self):
        self.state.apply({'type':'movement_request','x':300,'y':400})
        self.state.apply({'type':'walk','role_id':1,'x':300,'y':400})
        with patch('wlre.services.world.runtime_1275.active_runtime',side_effect=ValueError('missing')):
            result=audit(export(self.state.snapshot()))
        self.assertEqual(result['position_fixes'],1)
        self.assertEqual(result['local_requests_and_notices'],2)
        self.assertEqual(result['status'],'needs_live_evidence')
    def test_geometry_invalidates_but_does_not_claim_rebuilt_mesh(self):
        self.state.apply({'type':'navigation_geometry_change','reason':'furniture_moved','geometry_scope':'house',
                          'affects_geometry':True,'details_parsed':False})
        with patch('wlre.services.world.runtime_1275.active_runtime',side_effect=ValueError('missing')):
            result=audit(export(self.state.snapshot()))
        self.assertTrue(result['geometry_invalidation_observed'])
        self.assertFalse(result['dynamic_geometry_verified'])
    def test_stale_flag_without_revision_advance_is_not_proof_of_new_invalidation(self):
        self.state.apply({'type':'navigation_geometry_change','reason':'furniture_moved',
                          'geometry_scope':'house','affects_geometry':True,'details_parsed':False})
        snapshot=self.state.snapshot()
        snapshot['navigation_evidence']['events'][-1]['navigation_revision']=1
        with patch('wlre.services.world.runtime_1275.active_runtime',side_effect=ValueError('missing')):
            result=audit(export(snapshot))
        self.assertFalse(result['geometry_invalidation_observed'])

    def test_capture_is_bounded_and_reset_on_role_selection(self):
        for i in range(LIMIT+10):self.state.apply({'type':'position_snapshot','role_id':1,'scene':10000,'x':i,'y':200,'source':'S7-1'})
        self.assertEqual(len(self.state.navigation_evidence['events']),LIMIT)
        self.assertGreater(self.state.navigation_evidence['dropped'],0)
        self.state.apply({'type':'role_list_available','roles':[]})
        self.assertEqual(self.state.navigation_evidence['events'],[])


class CoordinateReferences(unittest.TestCase):
    def document(self):
        rows=[{'kind':'position_fix','source':'S7-1','sequence':i+1,'scene':10000,'x':x,'y':y}
              for i,(x,y) in enumerate(((100,100),(200,100),(100,200)))]
        return {'schema_version':1,'resource_revision':1275,'capture_type':'lala_passive_navigation_events',
            'events':rows,'stages':{'10000':{'model_id':13216,'offset_y':1000}},
            'reference_points':[{'sequence':r['sequence'],'reference_source':'independent_game_world_reference',
                                 'world_xz':[r['x']*.01,(1000-r['y'])*.01]} for r in rows]}
    def test_three_independent_references_can_be_consistent_without_enabling_movement(self):
        result=audit(self.document())
        self.assertEqual(result['coordinate_reference_checks'][0]['reference_consistency'],'consistent')
        self.assertFalse(result['can_send_packets']);self.assertFalse(result['live_movement_verified'])
    def test_wrong_axis_or_offset_is_detected(self):
        doc=self.document();doc['stages']['10000']['offset_y']=1100
        self.assertEqual(audit(doc)['coordinate_reference_checks'][0]['reference_consistency'],'mismatch')
    def test_duplicate_or_notice_references_are_rejected(self):
        doc=self.document();doc['reference_points'][1]['sequence']=1
        with self.assertRaises(EvidenceError):audit(doc)
        doc=self.document();doc['events'][0]['kind']='destination_notice'
        with self.assertRaises(EvidenceError):audit(doc)
    def test_reversed_or_duplicate_packet_order_is_rejected(self):
        doc=self.document();doc['events'][1]['sequence']=1
        with self.assertRaises(EvidenceError):audit(doc)
    def test_collinear_reference_points_do_not_validate_a_two_dimensional_mapping(self):
        doc=self.document()
        for i,row in enumerate(doc['events']):row['x']=100+i*100;row['y']=100
        self.assertEqual(audit(doc)['coordinate_reference_checks'][0]['reference_consistency'],'insufficient_points')


class EvidenceExportUI(unittest.TestCase):
    def test_explicit_export_writes_only_the_passive_report(self):
        import json,tempfile
        from pathlib import Path
        from unittest.mock import Mock
        from wlre.ui.navigation_evidence_ui import save
        state=State();state.apply({'type':'world_player','player':{'role_id':1,'name':'PRIVATE','scene':10000,'x':100,'y':200}})
        snapshot=state.snapshot();snapshot['password']='MUST_NOT_EXPORT'
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'evidence.json'
            with patch('wlre.ui.navigation_evidence_ui.filedialog.asksaveasfilename',return_value=str(path)),patch('wlre.services.world.runtime_1275.active_runtime',side_effect=ValueError('missing')):
                self.assertTrue(save(Mock(),snapshot))
            doc=json.loads(path.read_text())
        self.assertEqual(doc['capture_type'],'lala_passive_navigation_events')
        self.assertNotIn('MUST_NOT_EXPORT',str(doc));self.assertNotIn('PRIVATE',str(doc))
    def test_no_observations_do_not_open_save_dialog(self):
        from unittest.mock import Mock
        from wlre.ui.navigation_evidence_ui import save
        with patch('wlre.ui.navigation_evidence_ui.messagebox.showinfo'),patch('wlre.ui.navigation_evidence_ui.filedialog.asksaveasfilename') as dialog:
            self.assertFalse(save(Mock(),State().snapshot()));dialog.assert_not_called()


class CurrentSceneCoverage(unittest.TestCase):
    def test_other_models_cannot_validate_the_current_scene(self):
        doc=CoordinateReferences().document()
        result=audit(doc,candidate_models={12910,13217})
        self.assertEqual(result['status'],'needs_scene_candidate')
        self.assertFalse(result['scene_candidate_coverage'][0]['candidate_available'])
        self.assertFalse(result['can_send_packets'])
    def test_ignored_house_updates_are_counted_separately(self):
        doc=CoordinateReferences().document()
        doc['events'].append({'sequence':4,'scene':10000,'kind':'geometry_change',
            'affects_current_map':False,'navigation_revision':1,'stale':False})
        result=audit(doc)
        self.assertEqual(result['geometry_changes'],0)
        self.assertEqual(result['non_current_map_geometry_events'],1)


class CandidateSurfaceCheck(unittest.TestCase):
    def candidate(self):
        from test_recast_scan import settings,floors
        return {'kind':'offline_recast_candidate','resource_revision':1275,'can_send_packets':False,
                'source':{'model_id':'13216'},'settings':settings(),**floors([0])}
    def test_on_mesh_is_only_a_formula_prediction_not_live_verification(self):
        result=audit(CoordinateReferences().document(),{13216},{13216:self.candidate()})
        self.assertTrue(all(r['formula_prediction_on_candidate'] for r in result['candidate_surface_checks']))
        self.assertFalse(result['live_movement_verified']);self.assertFalse(result['can_send_packets'])
        self.assertTrue(all(not r['independent_world_reference_verified'] for r in result['candidate_surface_checks']))
    def test_wrong_offset_moves_predicted_points_outside_mesh(self):
        doc=CoordinateReferences().document();doc['stages']['10000']['offset_y']=6000
        result=audit(doc,{13216},{13216:self.candidate()})
        self.assertTrue(all(not r['formula_prediction_on_candidate'] for r in result['candidate_surface_checks']))
    def test_wrong_candidate_revision_cannot_match_by_filename_alone(self):
        candidate=self.candidate();candidate['resource_revision']=1262
        with self.assertRaises(EvidenceError):audit(CoordinateReferences().document(),{13216},{13216:candidate})
