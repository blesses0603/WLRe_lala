import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from wlre.services.world.navigation_shadow import compare


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.stage = dict(model_id=13221, map_width=200, map_height=200, small_offset_x=0, small_offset_y=0)
        self.runtime = SimpleNamespace(catalog_identity=SimpleNamespace(key='test'), stages={1:self.stage})
        self.state = {'navigation':{'revision':1}}
        self.coordinates = Mock()
        self.coordinates.mapping.return_value = (self.stage, 'M13221', (0,0,0))
        self.coordinates.route.return_value = dict(packet_points_xy_float=[[1,2],[3,4]], points=['not exported'])
        self.official = Mock()
        self.official.route.return_value = dict(packet_points_xy_float=[[1,2],[3,4]], can_send_packets=False, catalog_key='test')
        self.kw = dict(runtime_getter=lambda:self.runtime, state_getter=lambda:self.state,
                       coordinates_factory=lambda:self.coordinates, legacy_factory=lambda:object(),
                       official_factory=lambda *args:self.official)

    def run_comparison(self, **kwargs):
        return compare(1, (1,2), (3,4), **{**self.kw, **kwargs})

    def test_comparison_is_diagnostic_and_download_disabled(self):
        report=self.run_comparison(travel_mode='sky')
        self.assertEqual(report['status'],'compared')
        self.assertTrue(report['exact_xy_sequence_match'])
        self.assertIs(report['can_send_packets'],False)
        self.assertNotIn('points',report)
        self.assertNotIn('points',report['legacy'])
        self.assertIs(self.official.route.call_args.kwargs['download'],False)
        self.assertEqual(self.official.route.call_args.kwargs['travel_mode'],'sky')

    def test_missing_authority_marker_or_wrong_version(self):
        for change in ({'can_send_packets':True},{'catalog_key':'other'}):
            self.official.route.return_value.update(change)
            self.assertEqual(self.run_comparison()['official']['status'],'error')

    def test_failure_is_not_match(self):
        self.coordinates.route.side_effect=ValueError('legacy unavailable')
        report=self.run_comparison()
        self.assertEqual(report['status'],'incomplete')
        self.assertNotIn('exact_xy_sequence_match',report)
        self.assertEqual(report['official']['status'],'ready')

    def test_legacy_metadata_mismatch(self):
        self.coordinates.mapping.return_value=({'model_id':9},'M00009',(0,0,0))
        self.assertEqual(self.run_comparison()['legacy']['status'],'error')
        self.coordinates.route.assert_not_called()

    def test_state_change_discards_both_sides(self):
        def route(*args,**kwargs):
            self.state['navigation']['revision']=2
            return dict(packet_points_xy_float=[[1,2]],can_send_packets=False,catalog_key='test')
        self.official.route.side_effect=route
        report=self.run_comparison()
        self.assertEqual(report['status'],'stale')
        self.assertNotIn('legacy',report)
        self.assertNotIn('official',report)

    def test_runtime_change_discards_results(self):
        def route(*args,**kwargs):
            self.runtime=SimpleNamespace(catalog_identity=self.runtime.catalog_identity,stages=self.runtime.stages)
            return dict(packet_points_xy_float=[[1,2]])
        self.coordinates.route.side_effect=route
        self.assertEqual(self.run_comparison()['status'],'stale')
        self.official.route.assert_not_called()

    def test_invalid_points_and_limits(self):
        for points in ([[float('nan'),0]], [[0,0]]*4097, [], [[-1,0]]):
            self.official.route.return_value['packet_points_xy_float']=points
            self.assertEqual(self.run_comparison()['official']['status'],'error')

    def test_house_and_stale_state_rejected(self):
        with self.assertRaises(ValueError):
            compare(63501,(1,2),(3,4),**self.kw)
        self.state['navigation']['stale']=True
        with self.assertRaises(ValueError):self.run_comparison()
        self.official.route.assert_not_called()

    def test_invalid_inputs_rejected(self):
        for map_id,start in ((True,(1,2)),(1,(float('nan'),2)),(1,(1,2,3))):
            with self.assertRaises(ValueError):compare(map_id,start,(3,4),**self.kw)
