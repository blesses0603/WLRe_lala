"""Login gate displays Launcher receipt but cannot start resource downloads."""
import inspect
import unittest
from unittest.mock import Mock, patch

from wlre.ui.version_gate_controller import VersionGateController


class LauncherResourceUiTests(unittest.TestCase):
    def test_version_ui_does_not_download_or_extract(self):
        source = inspect.getsource(VersionGateController)
        self.assertNotIn('run_auto_catalog(', source)
        self.assertNotIn('lala-catalog-auto-prepare', source)
        self.assertNotIn('_start_auto_catalog', source)
        self.assertIn('read_launcher_status()', source)

    def test_main_version_check_only_starts_remote_version_worker(self):
        c = Mock()
        c._closing = False
        c.login_window = None
        c._version_gate_generation = 0
        c.version_gate_text = Mock()
        c._version_gate_messages = Mock()
        c._version_gate_result = None
        c._version_gate_entry_approved = False
        with patch('wlre.ui.version_gate_controller.threading.Thread') as thread:
            VersionGateController.start_version_check(c)
        self.assertEqual(thread.call_count, 1)
        self.assertEqual(thread.call_args.kwargs['name'], 'official-version-check')

    def test_launcher_receipt_is_display_only(self):
        from wlre.services.world.launcher_catalog import read_launcher_status
        self.assertNotIn('approved', inspect.getsource(read_launcher_status))
        remote = inspect.getsource(VersionGateController.can_login_after_version_check)
        self.assertNotIn('launcher_catalog', remote)
        self.assertNotIn('assets_ready', remote)


if __name__ == '__main__':
    unittest.main()
