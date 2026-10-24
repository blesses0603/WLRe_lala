"""LaLa version-screen auto candidate worker contracts without display/network."""
import queue
import threading
import unittest
from unittest.mock import Mock, patch

from wlre.ui.version_gate_controller import VersionGateController


class AutoCatalogUiTests(unittest.TestCase):
    def stub(self):
        c = Mock()
        c._closing = False
        c._auto_catalog_generation = 4
        c._auto_catalog_busy = False
        c._auto_catalog_messages = queue.SimpleQueue()
        c._auto_catalog_status = '尚未啟動'
        c._version_gate_result = {
            'source': 'official_remote_only',
            'remote': {'status': 'resources_changed'}}
        return c

    def test_prelogin_starts_bounded_worker_only_once(self):
        c = self.stub()
        with patch.object(threading, 'Thread') as spawn:
            VersionGateController._start_auto_catalog(c)
            VersionGateController._start_auto_catalog(c)
        self.assertEqual(spawn.call_count, 1)
        self.assertTrue(c._auto_catalog_busy)
        self.assertIn('Manifest', c._auto_catalog_status)
        spawn.return_value.start.assert_called_once()

    def test_completed_candidate_never_approves_login(self):
        c = self.stub()
        c._auto_catalog_messages.put((4, 'done', 'new_private_candidate'))
        VersionGateController._drain_auto_catalog_messages(c)
        self.assertIn('待相容性審核', c._auto_catalog_status)
        self.assertFalse(c._auto_catalog_busy)
        self.assertNotIn('_version_gate_entry_approved', c.__dict__)

    def test_failed_candidate_preserves_login_gate(self):
        c = self.stub()
        c._auto_catalog_messages.put((4, 'error', 'bad official bundle'))
        VersionGateController._drain_auto_catalog_messages(c)
        self.assertIn('登入限制', c._auto_catalog_status)

    def test_stale_worker_does_not_replace_new_status(self):
        c = self.stub()
        c._auto_catalog_messages.put((3, 'done', 'new_private_candidate'))
        c._start_auto_catalog = Mock()
        VersionGateController._drain_auto_catalog_messages(c)
        self.assertEqual(c._auto_catalog_status, '尚未啟動')
        c._start_auto_catalog.assert_called_once()

    def test_stale_worker_not_restarted_for_unverified_source(self):
        c = self.stub()
        c._version_gate_result = {'source': 'official_remote_only',
                                  'remote': {'status': 'unverified'}}
        c._auto_catalog_messages.put((3, 'done', 'new_private_candidate'))
        c._start_auto_catalog = Mock()
        VersionGateController._drain_auto_catalog_messages(c)
        c._start_auto_catalog.assert_not_called()


if __name__ == '__main__':
    unittest.main()
