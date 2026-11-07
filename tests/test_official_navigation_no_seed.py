import unittest
from unittest.mock import Mock,patch
from wlre.core.state import State
from wlre.network.wire import ProtocolError
from wlre.services.world.movement import Movement
from wlre.services.world.roaming import Roaming


class OfficialNavigationNoSeedTests(unittest.TestCase):
    def test_default_movement_and_roaming_reject_before_legacy_reads(self):
        state=State();state.player=dict(role_id=1,scene=10001)
        state.confirm_location(10001,10,10,'S3-1');movement=Movement()
        with patch('wlre.storage.bundled_database.load_bundled_bytes',side_effect=AssertionError('seed read')) as read:
            for action in (lambda:movement.start(state,20,20,0),lambda:Roaming().start(state,movement)):
                with self.assertRaisesRegex(ProtocolError,'官方導航僅供預覽'):action()
            read.assert_not_called()
        self.assertFalse(movement.active)
        self.assertEqual(movement.tick(state,1),[])
        self.assertIsNone(movement.converter)
        self.assertIsNone(movement.repository)

    def test_cli_missing_official_runtime_does_not_fall_back_to_seed(self):
        from wlre.__main__ import main
        with (patch('wlre.services.world.dynamic_bundle_runtime.prepare_dynamic_runtime',side_effect=ValueError('official missing')),
              patch('wlre.storage.bundled_database.load_bundled_bytes',side_effect=AssertionError('seed read')) as read,
              patch('builtins.print')):
            self.assertEqual(main(['nav-list']),2)
            self.assertEqual(main(['map-route','10001','--start','10','10','--end','20','20']),2)
            read.assert_not_called()
