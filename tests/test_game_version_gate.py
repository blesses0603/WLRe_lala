"""Current runtime identity replaces fixed package revision login diagnostics."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from wlre.services.game_version_gate import configured_sources, run_prelogin_check, compare_database_identity
from wlre.services.official_version import RESOURCE_MAP_URL


def response():
    return {'status':'resources_changed','resource_path':'1.3.22.1',
            'official_exe_version':'1.3.0','newer_official_client':False,
            'packages':{
                'DataPackage':{'remote':'1286_2026_10_29_13_42_37_94','comparison':'newer'},
                'MainPackage':{'remote':'1284_2026_10_28_19_50_04_11','comparison':'newer'}},
            'protocol_compatibility':'unverified'}


def identity(remote):
    return {'schema_version':1,'data_ver':remote['resource_path'],
            'exe_version':remote['official_exe_version'],
            'packages':[{'name':p,'full_version':row['remote']} for p,row in remote['packages'].items()]}


class RemoteGameVersionTests(unittest.TestCase):
    def setUp(self):
        self.remote=response()
        self.runtime=SimpleNamespace(
            catalog_identity=SimpleNamespace(as_dict=lambda:identity(self.remote)),
            record_counts={'npc':11009,'shops':1636,'crafting':1026,'scenes':1337,'items':11326})
        self.check=self.start_patch('wlre.services.game_version_gate.check_official_game_resources',return_value=self.remote)
        self.activate=self.start_patch('wlre.services.world.dynamic_bundle_runtime.activate_for_official',return_value=self.runtime)
        self.invalidate=self.start_patch('wlre.services.world.dynamic_bundle_runtime.invalidate_runtime')
        self.matches=self.start_patch('wlre.services.world.resource_database.database_matches_runtime',return_value=True)
        self.read=self.start_patch('wlre.services.world.resource_database.read_active_database_identity',side_effect=lambda _:identity(self.remote))
    def start_patch(self,*args,**kwargs):
        item=patch(*args,**kwargs)
        result=item.start()
        self.addCleanup(item.stop)
        return result

    def test_source_is_official_resource_map(self):
        self.assertEqual(configured_sources(),{'ResourcePath_PC.dat':RESOURCE_MAP_URL})

    def test_independent_live_pair_matches_runtime_without_1275_rejection(self):
        with patch('wlre.services.world.runtime_1275.ready') as legacy:
            result=run_prelogin_check()
        self.activate.assert_called_once_with(self.remote)
        legacy.assert_not_called()
        self.assertEqual(result['status'],'database_matches_official')
        self.assertEqual(result['dynamic_runtime'],'verified')
        self.assertEqual(result['data_compatibility'],'compatible')
        self.assertEqual(result['database_comparison'],'same')
        self.assertEqual(result['baseline']['MainPackage'],self.remote['packages']['MainPackage']['remote'])
        self.assertNotIn('1275',result['message'])
        self.assertNotIn('等待 LaLa 更新',result['message'])
        self.assertEqual(result['record_counts']['crafting'],1026)

    def test_protocol_label_does_not_block_matching_data(self):
        self.remote['protocol_compatibility']='verified'
        self.remote['can_send_packets']=True
        result=run_prelogin_check()
        self.assertFalse(result['blocked'])
        self.assertTrue(result['login_allowed'])
        self.assertEqual(result['protocol_compatibility'],'unverified')
        self.assertIsNone(result['block_reason'])

    def test_current_data_and_old_database_are_independent(self):
        old=identity(self.remote)
        old['packages'][0]['full_version']='old'
        self.read.side_effect=None
        self.read.return_value=old
        self.matches.return_value=False
        result=run_prelogin_check()
        self.assertEqual(result['database_comparison'],'different')
        self.assertEqual(result['dynamic_runtime'],'verified')
        self.assertEqual(result['status'],'database_mismatch')
        self.assertTrue(result['blocked'])

    def test_new_official_executable_is_allowed_when_runtime_and_database_match(self):
        self.remote['newer_official_client']=True
        self.remote['official_exe_version']='1.4.0'
        result=run_prelogin_check()
        self.assertEqual(result['status'],'database_matches_official')
        self.assertFalse(result['blocked'])
        self.activate.assert_called_once_with(self.remote)

    def test_matching_metadata_does_not_hide_missing_or_corrupt_database_bytes(self):
        self.matches.return_value=False
        result=run_prelogin_check()
        self.assertEqual(result['database_comparison'],'different')
        self.assertEqual(result['status'],'database_mismatch')
        self.assertFalse(result['login_allowed'])
        self.assertTrue(result['blocked'])

    def test_offline_or_partial_identity_does_not_reuse_stale_runtime(self):
        for remote in ({'status':'unverified','packages':{}},
                       {**response(),'status':'unverified'},
                       {**response(),'packages':{'DataPackage':response()['packages']['DataPackage']}}):
            self.check.return_value=remote
            result=run_prelogin_check()
            self.assertTrue(result['blocked'])
            self.assertEqual(result['status'],'unverified')
            self.assertEqual(result['dynamic_runtime'],'unavailable')
        self.activate.assert_not_called()

    def test_runtime_failure_is_not_a_fixed_version_update_error(self):
        self.activate.side_effect=ValueError('private-path fixture')
        result=run_prelogin_check()
        self.assertEqual(result['status'],'runtime_unavailable')
        self.assertIn('完整 Runtime 未通過驗證',result['message'])
        self.assertNotIn('private-path',result['message'])
        self.assertNotIn('1275',result['message'])
        self.assertTrue(result['blocked'])
        self.invalidate.assert_not_called()

    def test_republished_manifest_pair_cannot_reuse_previous_runtime(self):
        wrong=identity(self.remote)
        wrong['packages'][0]['full_version']+='1'
        self.runtime.catalog_identity=SimpleNamespace(as_dict=lambda:wrong)
        result=run_prelogin_check()
        self.assertEqual(result['status'],'runtime_unavailable')
        self.assertTrue(result['blocked'])
        self.invalidate.assert_not_called()

    def test_database_identity_requires_both_exact_packages_and_client(self):
        observed=response()
        saved=identity(observed)
        self.assertEqual(compare_database_identity(observed,saved),'same')
        saved['exe_version']='1.2.0'
        self.assertEqual(compare_database_identity(observed,saved),'different')
        saved=identity(observed)
        saved['packages'][1]['full_version']+='1'
        self.assertEqual(compare_database_identity(observed,saved),'different')
        observed['packages']['MainPackage']['remote']=None
        self.assertEqual(compare_database_identity(observed,saved),'unverified')

    def test_explicit_historical_fixture_does_not_activate_dynamic_runtime(self):
        remote={'status':'same_resources','packages':{
            p:{'remote':'1275','comparison':'same'} for p in ('MainPackage','DataPackage')}}
        result=run_prelogin_check({},checker=lambda _:remote)
        self.assertFalse(result['blocked'])
        self.assertEqual(result['status'],'version_identifiers_match')
        self.activate.assert_not_called()

    def test_incomplete_fixture_cannot_authorize_login(self):
        result=run_prelogin_check({},checker=lambda _:{
            'status':'same_resources','packages':{'MainPackage':{'comparison':'same'}}})
        self.assertTrue(result['blocked'])

    def test_connect_never_uses_account_before_gate(self):
        from wlre.ui.gui import App
        fake=SimpleNamespace(assert_ui_thread=Mock(),can_login_after_version_check=Mock(return_value=False))
        with patch('wlre.ui.gui.run_client') as client:
            self.assertIsNone(App.connect(fake))
        client.assert_not_called()
