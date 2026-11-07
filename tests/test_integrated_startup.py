"""All desktop entries share resource preparation and fail-closed login checks."""
import threading
import unittest
from unittest.mock import ANY, Mock, patch

from test_background_version_observer import identity
from wlre.ui.gui import App
from wlre.ui.version_gate_controller import VersionGateController


class Var:
    def __init__(self, value=''):
        self.value = value
    def set(self, value):
        self.value = value
    def get(self):
        return self.value


def blocked_result():
    return {'blocked': True, 'status': 'unverified', 'message': '尚未驗證',
            'remote': {'status': 'unverified'}}


def verified_result():
    return {'blocked': False, 'status': 'version_identifiers_match',
            'runtime_identity': identity(),
            'message': '官方版本已驗證', 'remote': {
                'status': 'same_resources', 'packages': {
                    name: {'comparison': 'same'}
                    for name in ('MainPackage', 'DataPackage')}}}


class StartupHarness(VersionGateController):
    close = App.close

    def __init__(self):
        self._closing = False
        self.root = Mock()
        self.login_window = None
        self.live_active = False
        self.stop_event = threading.Event()
        self.password = Mock()
        self.diagnostics = Mock()
        with patch('wlre.ui.version_gate_controller.tk.StringVar', Var), \
             patch('wlre.ui.version_gate_controller._launcher_status_text', return_value='舊紀錄'):
            self.initialize_version_gate()
        for name in ('start_lala_release_check', '_drain_lala_update_messages',
                     '_render_version_window', '_set_login_gate_button',
                     'show_version_check', 'show_login', 'hide_version_check'):
            setattr(self, name, Mock())


class IntegratedStartupTests(unittest.TestCase):
    def setUp(self):
        self.app = StartupHarness()
        self.prepare_patch = patch('wlre.ui.version_gate_controller.prepare_on_launch',
                                   return_value={'status': 'verified_official'})
        self.check_patch = patch('wlre.ui.version_gate_controller.run_prelogin_check',
                                 return_value=blocked_result())
        self.status_patch = patch('wlre.ui.version_gate_controller._launcher_status_text',
                                  return_value='新的資源紀錄')
        self.prepare = self.prepare_patch.start()
        self.check = self.check_patch.start()
        self.status_patch.start()
        self.addCleanup(self.prepare_patch.stop)
        self.addCleanup(self.check_patch.stop)
        self.addCleanup(self.status_patch.stop)

    def begin(self, app=None):
        app = app or self.app
        with patch('wlre.ui.version_gate_controller.threading.Thread') as thread:
            app.start_version_check()
        self.assertFalse(thread.call_args.kwargs['daemon'])
        self.assertEqual(thread.call_args.kwargs['name'], 'official-version-check')
        worker = thread.call_args.kwargs['target']
        # Background code must not retain App or any Tcl-owned objects.
        self.assertNotIn('self', worker.__code__.co_freevars)
        return worker

    def test_prepares_before_check_in_one_worker_and_receipt_never_grants_login(self):
        calls = []
        self.prepare.side_effect = lambda **kw: calls.append('prepare') or {
            'status': 'verified_official', 'assets_ready': True, 'can_send_packets': True}
        self.check.side_effect = lambda **kw: calls.append('official') or blocked_result()
        worker = self.begin()
        self.assertEqual(self.app._startup_phase, 'preparing')
        self.assertFalse(self.app._version_gate_entry_approved)
        worker()
        self.app.drain_version_checks()
        self.assertEqual(calls, ['prepare', 'official'])
        self.assertEqual(self.app._launcher_catalog_status, '新的資源紀錄')
        self.assertEqual(self.app.version_gate_state, 'blocked')
        self.assertFalse(self.app._version_gate_entry_approved)

    def test_busy_clicks_do_not_start_duplicate_preparation_or_checks(self):
        worker = self.begin()
        with patch('wlre.ui.version_gate_controller.threading.Thread') as thread:
            self.app.start_version_check()
            self.app.start_version_check()
        thread.assert_not_called()
        self.assertEqual(self.app._version_gate_generation, 1)
        worker()
        self.prepare.assert_called_once()
        self.check.assert_called_once_with(progress=ANY)

    def test_every_completed_retry_rechecks_official_but_preparation_is_once_per_app(self):
        self.begin()()
        self.app.drain_version_checks()
        self.begin()()
        self.app.drain_version_checks()
        self.prepare.assert_called_once()
        self.assertEqual(self.check.call_count, 2)
        other = StartupHarness()
        self.begin(other)()
        self.assertEqual(self.prepare.call_count, 2)
        self.assertEqual(self.check.call_count, 3)

    def test_resource_exception_still_runs_official_check_and_hides_private_error(self):
        self.prepare.side_effect = RuntimeError('C:/private/token')
        self.begin()()
        self.app.drain_version_checks()
        self.check.assert_called_once_with(progress=ANY)
        self.assertEqual(self.app.version_gate_state, 'blocked')
        self.assertIn('例外', self.app._launcher_catalog_status)
        self.assertNotIn('private', self.app._launcher_catalog_status)

    def test_preparation_failure_does_not_override_independent_verified_official_result(self):
        self.prepare.return_value = {'status': 'error'}
        self.check.return_value = verified_result()
        self.begin()()
        self.app.drain_version_checks()
        self.assertEqual(self.app.version_gate_state, 'ready')
        self.assertFalse(self.app._version_gate_entry_approved)
        self.app.continue_to_login()
        self.assertTrue(self.app._version_gate_entry_approved)
        self.app.show_login.assert_called_once_with()

    def test_official_exception_is_terminal_and_retry_is_available(self):
        self.check.side_effect = RuntimeError('C:/private/token')
        self.begin()()
        self.app.drain_version_checks()
        self.assertTrue(self.app._version_worker_done.is_set())
        self.assertEqual(self.app.version_gate_state, 'blocked')
        self.assertNotIn('private', self.app.version_gate_text.get())
        self.check.side_effect = None
        self.check.return_value = verified_result()
        self.begin()()
        self.app.drain_version_checks()
        self.assertEqual(self.app.version_gate_state, 'ready')
        self.prepare.assert_called_once()

    def test_progress_is_coalesced_and_cannot_approve_login(self):
        self.begin()  # Keep the manual worker pending while testing its mailbox.
        for i in range(10000):
            self.app._startup_progress.report('bundle_item', {'completed': i, 'total': 10000})
        self.app._startup_progress.report('extract_failed', {'feature': 'npc', 'stage': 'Eve 二進位事件'})
        self.app._startup_progress.report('bundle_item', {'completed': 10000, 'total': 10000})
        self.app.drain_version_checks()
        self.assertEqual(self.app._startup_progress_update[2], (10000, 10000))
        self.assertIn('10000 / 10000', self.app.version_gate_text.get())
        self.assertIn('Eve', self.app._startup_failure)
        self.assertEqual(self.app.version_gate_state, 'checking')
        self.assertFalse(self.app._version_gate_entry_approved)
        self.assertEqual(self.app._startup_progress.take(), (None, None, None))

    def test_phase_changes_and_terminal_failure_survive_progress_bursts(self):
        def preparation(*, progress):
            progress('extract_failed', {'feature': 'npc', 'stage': 'Eve 二進位事件'})
            for i in range(100):
                progress('bundle_item', {'completed': i, 'total': 100})
            return {'status': 'downloaded_unparsed'}
        self.prepare.side_effect = preparation
        def official(**kwargs):
            # Simulate the Tk drain at the preparation/official boundary.
            self.app.drain_version_checks()
            self.assertEqual(self.app._startup_phase, 'official')
            self.assertIn('獨立核對', self.app.version_gate_text.get())
            return blocked_result()
        self.check.side_effect = official
        self.begin()()
        self.app.drain_version_checks()
        self.assertEqual(self.app.version_gate_state, 'blocked')
        self.assertIn('Eve', self.app._launcher_catalog_status)

    def test_stale_queue_results_and_progress_are_discarded_on_retry(self):
        self.check.return_value = verified_result()
        self.begin()()  # Leave old result and progress undrained.
        self.app._startup_progress.report('bundle_item', {'completed': 8, 'total': 24})
        second = self.begin()
        self.app.drain_version_checks()
        self.assertEqual(self.app.version_gate_state, 'checking')
        self.assertIsNone(self.app._version_gate_result)
        self.assertIsNone(self.app._startup_progress_update)
        self.check.return_value = blocked_result()
        second()
        self.app.drain_version_checks()
        self.assertEqual(self.app.version_gate_state, 'blocked')
        self.assertFalse(self.app._version_gate_entry_approved)

    def test_elapsed_uses_existing_poll_only_and_updates_at_most_once_per_second(self):
        self.app._startup_elapsed = Mock()
        with patch('wlre.ui.version_gate_controller.time.monotonic', return_value=100.0):
            self.begin()
        self.assertEqual(self.app._startup_elapsed.set.call_count, 1)
        with patch('wlre.ui.version_gate_controller.time.monotonic', return_value=100.9):
            for _ in range(200):
                self.app.drain_version_checks()
        self.assertEqual(self.app._startup_elapsed.set.call_count, 1)
        with patch('wlre.ui.version_gate_controller.time.monotonic', return_value=101.1):
            for _ in range(200):
                self.app.drain_version_checks()
        self.assertEqual(self.app._startup_elapsed.set.call_count, 2)
        self.assertIn('已用 1 秒', self.app._startup_elapsed.set.call_args.args[0])
        self.app.root.after.assert_not_called()
        self.assertEqual(self.app._version_gate_checked, 0)
        self.assertFalse(self.app._version_gate_entry_approved)

    def test_formal_phase_and_elapsed_are_not_collection_approval(self):
        with patch('wlre.ui.version_gate_controller.time.monotonic', return_value=100.0):
            self.begin()
        for phase, title, elapsed in (('official_metadata', '官方版本查詢', 2),
                                      ('official_runtime', '正式 Runtime 驗證', 10),
                                      ('official_database', '資料庫內容比對', 27)):
            with patch('wlre.ui.version_gate_controller.time.monotonic', return_value=100.0 + elapsed):
                self.app._official_progress.report(phase, {})
                self.app.drain_version_checks()
            self.assertEqual(self.app._startup_phase, 'official')
            self.assertEqual(self.app._startup_progress_update[0], title)
            self.assertIn(f'已用 {elapsed} 秒', self.app._startup_elapsed.get())
            self.assertEqual(self.app.version_gate_state, 'checking')
            self.assertFalse(self.app._version_gate_entry_approved)
        self.app._startup_progress.report('bundle_item', {'completed': 7, 'total': 7})
        self.app.drain_version_checks()
        self.assertEqual(self.app._startup_progress_update[0], '資料庫內容比對')

    def test_terminal_elapsed_freezes_and_retry_resets_without_repreparation(self):
        self.check.return_value = verified_result()
        self.app._version_progress = Mock()
        with patch('wlre.ui.version_gate_controller.time.monotonic', return_value=100.0):
            self.begin()()
        with patch('wlre.ui.version_gate_controller.time.monotonic', return_value=127.5):
            self.app.drain_version_checks()
        self.assertIn('完成 · 共用 27 秒', self.app._startup_elapsed.get())
        checked = self.app._version_gate_checked
        self.app._version_progress.finish.assert_called_once()
        with patch('wlre.ui.version_gate_controller.time.monotonic', return_value=300.0):
            self.app._official_progress.report('official_runtime', {})
            self.app.drain_version_checks()
            self.assertIn('完成 · 共用 27 秒', self.app._startup_elapsed.get())
            self.assertEqual(self.app._version_gate_checked, checked)
            self.begin()()
            self.assertIn('已用 0 秒', self.app._startup_elapsed.get())
        self.prepare.assert_called_once()
        self.assertEqual(self.check.call_count, 2)
        self.assertEqual(self.app._version_progress.reset.call_count, 2)

    def test_error_freezes_elapsed_and_finishes_progress(self):
        self.app._version_progress = Mock()
        self.check.side_effect = OSError('private error')
        with patch('wlre.ui.version_gate_controller.time.monotonic', return_value=100.0):
            self.begin()()
        with patch('wlre.ui.version_gate_controller.time.monotonic', return_value=102.0):
            self.app.drain_version_checks()
        self.app._version_progress.finish.assert_called_once()
        self.assertEqual(self.app.version_gate_state, 'blocked')
        self.assertIn('未通過 · 共用 2 秒', self.app._startup_elapsed.get())
        with patch('wlre.ui.version_gate_controller.time.monotonic', return_value=200.0):
            self.app.drain_version_checks()
        self.assertIn('未通過 · 共用 2 秒', self.app._startup_elapsed.get())

    def test_failed_thread_start_fails_closed_and_can_retry(self):
        with patch('wlre.ui.version_gate_controller.threading.Thread') as thread:
            thread.return_value.start.side_effect = RuntimeError('private failure')
            self.app.start_version_check()
        self.app.drain_version_checks()
        self.assertTrue(self.app._version_worker_done.is_set())
        self.assertEqual(self.app.version_gate_state, 'blocked')
        self.assertNotIn('private', self.app.version_gate_text.get())
        self.prepare.assert_not_called()
        self.begin()()
        self.prepare.assert_called_once()

    def test_close_waits_for_preparation_write_then_exits_without_official_or_login(self):
        entered, release, written = threading.Event(), threading.Event(), threading.Event()
        def preparation(**kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test timed out')
            written.set()
            return {'status': 'verified_official'}
        self.prepare.side_effect = preparation
        try:
            self.app.start_version_check()
            self.assertTrue(entered.wait(2))
            self.app.close()
            self.assertFalse(self.app._closing)
            self.assertTrue(self.app._startup_exit_requested.is_set())
            self.app.root.destroy.assert_not_called()
            self.app.diagnostics.close.assert_not_called()
            self.assertFalse(self.app.can_login_after_version_check())
            self.app.continue_to_login()
            self.app.show_login.assert_not_called()
            self.app.close()
            self.app.root.after.assert_called_once()
            self.app.start_version_check()
        finally:
            release.set()
            self.assertTrue(self.app._version_worker_done.wait(3))
        self.assertTrue(written.is_set())
        self.check.assert_not_called()
        self.app._finish_startup_close()
        self.assertTrue(self.app._closing)
        self.app.root.destroy.assert_called_once()
        self.app.diagnostics.close.assert_called_once()
        self.app.close()
        self.app.root.destroy.assert_called_once()

    def test_close_during_official_check_waits_but_ignores_late_success(self):
        entered, release = threading.Event(), threading.Event()
        def official(**kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test timed out')
            return verified_result()
        self.check.side_effect = official
        try:
            self.app.start_version_check()
            self.assertTrue(entered.wait(2))
            self.app.close()
            self.app.root.destroy.assert_not_called()
        finally:
            release.set()
            self.assertTrue(self.app._version_worker_done.wait(3))
        self.app.drain_version_checks()
        self.assertIsNone(self.app._version_gate_result)
        self.assertFalse(self.app._version_gate_entry_approved)
        self.app._finish_startup_close()
        self.app.root.destroy.assert_called_once()


if __name__ == '__main__':
    unittest.main()
