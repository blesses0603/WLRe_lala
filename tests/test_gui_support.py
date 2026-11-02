"""GUI fixture cleanup must preserve unittest's class lifecycle state."""
import unittest
from gui_support import isolate_gui_background_checks


class GuiFixtureLifecycleTests(unittest.TestCase):
    def test_class_cleanup_keeps_unittest_exception_list_and_offline_gate(self):
        class Fixture(unittest.TestCase):
            pass
        isolate_gui_background_checks(Fixture)
        Fixture.fixture_graph = object()
        from wlre.ui.version_gate_controller import run_prelogin_check
        self.assertTrue(run_prelogin_check()['blocked'])
        Fixture.doClassCleanups()
        self.assertEqual(Fixture.tearDown_exceptions, [])
        self.assertIsNone(Fixture.fixture_graph)
