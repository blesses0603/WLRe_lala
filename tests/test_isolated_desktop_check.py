"""Offline regressions for the isolated desktop tool's integrated startup wait."""
import heapq
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.check_isolated_application import check


def official_result(verified):
    return {
        'status': 'version_identifiers_match' if verified else 'unverified',
        'blocked': not verified,
        'remote': {'status': 'same_resources' if verified else 'unverified',
                   'packages': {name: {'comparison': 'same'}
                                for name in ('MainPackage', 'DataPackage')}}}


class FakeRoot:
    def __init__(self):
        self.now = 0
        self.jobs = []
        self.sequence = 0
        self.closed = False

    def after(self, delay, callback):
        self.sequence += 1
        heapq.heappush(self.jobs, (self.now + delay, self.sequence, callback))

    def update_idletasks(self):
        pass

    def mainloop(self):
        for _ in range(2000):
            if self.closed or not self.jobs:
                return
            self.now, _, callback = heapq.heappop(self.jobs)
            callback()
        raise AssertionError('Unbounded desktop diagnostic poll')


class IsolatedDesktopCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        (self.workspace / 'isolation.json').write_text('{}')
        self.root = FakeRoot()
        self.apps = []

    def run_check(self, *, online, receipt=None, verified=False,
                  preparation_error=False, never_deliver=False, unmonitored=False):
        import WLRE_Client
        from wlre.ui import gui, version_gate_controller as gate
        from wlre.ui import official_navigation_preview

        root = self.root
        apps = self.apps
        result = official_result(verified)

        class FakeApp:
            def __init__(self, parent):
                self._startup_prepared = threading.Event()
                self._version_worker_done = threading.Event()
                self.version_gate_state = 'checking'
                self._version_gate_result = None
                self.overview_panel = SimpleNamespace(winfo_ismapped=lambda: True)
                self.snapshot = {}
                self.show_time = None
                apps.append(self)
                parent.after(200, self.prepare)

            def prepare(self):
                try:
                    if not unmonitored:
                        # This is the same lookup used by the real App worker.
                        gate.prepare_on_launch(progress=lambda *args: None)
                except Exception:
                    pass  # App still runs its independent official check.
                self._startup_prepared.set()
                root.after(200, self.official)

            def official(self):
                self._version_worker_done.set()
                if not never_deliver:
                    root.after(100, self.deliver)

            def deliver(self):
                self._version_gate_result = result
                self.version_gate_state = 'ready' if verified else 'blocked'

            def show_main(self):
                self.show_time = root.now

            def open_navigation(self):
                official_navigation_preview.OfficialNavigationPreview(root, lambda: self.snapshot, suggested_scene=12050)

            def close(self):
                root.closed = True

        class FakePreview:
            def __init__(self, *args, suggested_scene=None):
                if suggested_scene != 12050:
                    raise AssertionError("Preview entry keywords were not forwarded")
                self.validation_error = None

            def run(self, download):
                self.validation_error = 'Runtime 尚未同步'

            def close(self):
                pass

        def prepare(*, progress):
            progress('runtime_bundle_plan', {})
            if preparation_error:
                raise RuntimeError('private diagnostic error')
            return receipt

        def main():
            gui.App(root)
            root.mainloop()
            return 0

        with (patch.object(gui, 'App', FakeApp),
              patch.object(WLRE_Client, 'main', side_effect=main),
              patch.object(gate, 'prepare_on_launch', side_effect=prepare) as preparation,
              patch('wlre.services.world.launcher_catalog.prepare_on_launch',
                    side_effect=AssertionError('Wrong preparation lookup')),
              patch.object(official_navigation_preview, 'OfficialNavigationPreview', FakePreview),
              patch('wlre.services.world.dynamic_bundle_runtime.current_runtime', return_value=None),
              patch('tools.check_isolated_application.time.monotonic', side_effect=lambda: root.now / 1000),
              patch('tools.check_isolated_application.sys.addaudithook'),
              patch.dict('os.environ', {'https_proxy': '', 'HTTPS_PROXY': ''})):
            value = check(self.workspace, 'desktop', online)
        preparation.assert_called_once()
        return value

    def test_online_monitors_actual_lookup_and_waits_for_tk_result(self):
        value = self.run_check(online=True, receipt={'status': 'verified_official'}, verified=True)
        observations = value['observations']
        self.assertEqual(observations['launcher_phases'], ['runtime_bundle_plan'])
        self.assertEqual(observations['launcher_result']['status'], 'verified_official')
        self.assertTrue(observations['startup_checks_completed'])
        self.assertTrue(observations['official_login_verified'])
        self.assertGreaterEqual(self.apps[0].show_time, 500)
        self.assertFalse(value['actual_game_login'])

    def test_offline_expected_block_is_explicit_not_official_success(self):
        value = self.run_check(online=False, receipt={'status': 'skipped'})
        self.assertTrue(value['observations']['startup_checks_completed'])
        self.assertTrue(value['observations']['official_result']['blocked'])
        self.assertFalse(value['observations']['official_login_verified'])
        self.assertGreaterEqual(self.apps[0].show_time, 500)

    def assert_failed_report(self):
        value = json.loads((self.workspace / 'cold-start.json').read_text())
        self.assertEqual(value['status'], 'failed')
        self.assertFalse(value['actual_game_login'])
        self.assertIsNone(self.apps[0].show_time)
        return value

    def test_online_preparation_failure_cannot_pass_on_verified_official_result(self):
        with self.assertRaises(AssertionError):
            self.run_check(online=True, receipt={'status': 'error'}, verified=True)
        value = self.assert_failed_report()
        self.assertEqual(value['observations']['launcher_result']['status'], 'error')

    def test_online_official_failure_is_saved_and_fails_smoke(self):
        with self.assertRaises(AssertionError):
            self.run_check(online=True, receipt={'status': 'verified_official'})
        value = self.assert_failed_report()
        self.assertTrue(value['observations']['official_result']['blocked'])

    def test_online_skipped_preparation_cannot_pass(self):
        with self.assertRaises(AssertionError):
            self.run_check(online=True, receipt={'status': 'skipped'}, verified=True)
        value = self.assert_failed_report()
        self.assertIn('unexpectedly skipped', str(value['errors']))

    def test_preparation_exception_is_recorded_without_private_detail(self):
        with self.assertRaises(AssertionError):
            self.run_check(online=True, verified=True, preparation_error=True)
        value = self.assert_failed_report()
        self.assertEqual(value['observations']['launcher_error'], 'RuntimeError')
        self.assertNotIn('private diagnostic error', json.dumps(value))

    def test_unmonitored_preparation_cannot_silently_pass(self):
        with self.assertRaises(AssertionError):
            self.run_check(online=False, receipt={'status': 'skipped'}, unmonitored=True)
        value = self.assert_failed_report()
        self.assertIn('monitored entry', str(value['errors']))

    def test_missing_official_receipt_times_out_without_opening_dashboard(self):
        with self.assertRaises(AssertionError):
            self.run_check(online=False, receipt={'status': 'skipped'}, never_deliver=True)
        value = self.assert_failed_report()
        self.assertIn('TimeoutError', str(value['errors']))
        self.assertFalse(value['observations'].get('startup_checks_completed', False))


if __name__ == '__main__':
    unittest.main()
