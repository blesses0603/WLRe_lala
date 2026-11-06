import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from wlre.core.state import State
from wlre.network.wire import ProtocolError
from wlre.services.world.house_navigation import require_general_navigation
from wlre.services.world.navigation import NavigationError
from wlre.services.world.navigation_preview import PreviewRepository, REVIEWED_COORDINATE_CATALOGS
from wlre.services.world.navigation_sync import sync_model
from wlre.services.world.movement import Movement
from wlre.services.world.tent import command


class HouseNavigationScopeTests(unittest.TestCase):
    def test_houses_rejected_before_download_or_movement(self):
        identity=SimpleNamespace(key=next(iter(REVIEWED_COORDINATE_CATALOGS)))
        repo=PreviewRepository(identity,{})
        for scene in (10000,10298,10299,63501,64000,65500):
            with self.subTest(scene=scene):
                with self.assertRaisesRegex(NavigationError,'僅支援進入與離開'):
                    repo.route(scene,(0,0),(1,1),download=True)
                state=State();state.player=dict(role_id=1,scene=scene)
                state.confirm_location(scene,10,10,'S3-1')
                converter=Mock();movement=Movement(converter,Mock())
                with self.assertRaisesRegex(ProtocolError,'僅支援進入與離開'):
                    movement.start(state,20,20,0)
                converter.route.assert_not_called()
                self.assertFalse(movement.active)
        for model in (10000,10004,10005):
            observe=Mock();fetch=Mock()
            with self.assertRaises(NavigationError):
                sync_model(identity,model,observe=observe,fetch=fetch)
            observe.assert_not_called();fetch.assert_not_called()
            with self.assertRaises(NavigationError):repo.load(model,download=True)

    def test_general_maps_and_instance_range_not_excluded(self):
        for scene in (10001,10004,10297,10300,61501,62000,63500,65501):
            require_general_navigation(scene=scene)
        for model in (10001,12600,58001,12050,13216,11139):
            require_general_navigation(model=model)

    def test_enter_and_leave_do_not_call_navigation(self):
        state=State(phase='world_ready',initial_data_complete=True)
        state.player=dict(role_id=91,scene=12170)
        state.tent.update(visible=True,scene=12170)
        with patch('wlre.services.world.house_navigation.require_general_navigation',side_effect=AssertionError('navigation invoked')):
            packets=command(state,dict(action='enter'),now=0)
            self.assertEqual([(p.main,p.sub) for p in packets],[(65,1)])
            state.player['scene']=63501
            state.tent.update(pending=None,inside=True,interior_scene=63501,return_scene=12170)
            with patch('wlre.services.world.tent.exit_door_index',return_value=7) as exit_index:
                packets=command(state,dict(action='leave'),now=1)
            exit_index.assert_called_once_with(return_scene=12170)
            self.assertEqual([(p.main,p.sub,p.payload) for p in packets],[(20,8,b'\x07\x00')])
