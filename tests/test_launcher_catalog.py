"""Launcher owns auto Catalog; offline tests for source/frozen entry parity."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import WLRE_Client
from wlre import launcher
from wlre.services.world.launcher_catalog import (
    prepare_on_launch, read_launcher_status, status_path,
)


class LauncherCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_success_writes_unapproved_private_receipt(self):
        runner = Mock(return_value={
            'status': 'review_required',
            'catalog_key': 'f' * 64,
            'assets_ready': False,
            'can_send_packets': False,
        })
        result = prepare_on_launch(root=self.root, runner=runner, environ={})
        runner.assert_called_once_with(download=True, parse=True)
        self.assertEqual(result['status'], 'review_required')
        self.assertFalse(result['assets_ready'])
        self.assertEqual(result['data_compatibility'], 'unverified')
        self.assertEqual(result['protocol_compatibility'], 'unverified')
        self.assertEqual(read_launcher_status(root=self.root), result)
        self.assertTrue(status_path(self.root).is_file())

    def test_explicit_schema_compatible_still_never_approves_login(self):
        runner = Mock(return_value={
            'status': 'review_required',
            'catalog_key': 'a' * 64,
            'data_compatibility': 'compatible',
            'protocol_compatibility': 'unverified',
            'assets_ready': False,
            'can_send_packets': False,
            'approved': False,
        })
        result = prepare_on_launch(root=self.root, runner=runner, environ={})
        self.assertEqual(result['schema_version'], 2)
        self.assertEqual(result['data_compatibility'], 'compatible')
        self.assertEqual(result['protocol_compatibility'], 'unverified')
        self.assertFalse(result['assets_ready'])
        self.assertFalse(result['can_send_packets'])
        self.assertEqual(read_launcher_status(root=self.root), result)

    def test_unverified_protocol_or_omitted_authorization_cannot_claim_compatibility(self):
        runner = Mock(return_value={
            'status': 'review_required', 'catalog_key': 'b'*64,
            'data_compatibility': 'compatible',
            'protocol_compatibility': 'compatible',
            'assets_ready': False, 'can_send_packets': False, 'approved': False})
        result = prepare_on_launch(root=self.root, runner=runner, environ={})
        self.assertEqual(result['data_compatibility'], 'unverified')

    def test_invalid_receipt_cannot_claim_protocol_approval(self):
        runner = Mock(return_value={
            'status': 'review_required', 'catalog_key': 'c'*64,
            'data_compatibility': 'compatible',
            'protocol_compatibility': 'unverified',
            'assets_ready': False, 'can_send_packets': False, 'approved': False})
        prepare_on_launch(root=self.root, runner=runner, environ={})
        path = status_path(self.root)
        receipt = json.loads(path.read_text(encoding='utf-8'))
        receipt['protocol_compatibility'] = 'compatible'
        path.write_text(json.dumps(receipt), encoding='utf-8')
        self.assertIsNone(read_launcher_status(root=self.root))

    def test_network_failure_never_creates_approved_receipt(self):
        runner = Mock(side_effect=OSError('private game path'))
        result = prepare_on_launch(root=self.root, runner=runner, environ={})
        self.assertEqual(result['status'], 'error')
        self.assertIsNone(result['catalog_key'])
        self.assertNotIn('private game path', status_path(self.root).read_text())
        self.assertFalse(read_launcher_status(root=self.root)['assets_ready'])

    def test_skip_prevents_network_and_writes(self):
        runner = Mock()
        result = prepare_on_launch(
            root=self.root, runner=runner,
            environ={'WLRE_DISABLE_AUTO_CATALOG': '1'})
        runner.assert_not_called()
        self.assertEqual(result['status'], 'skipped')
        self.assertFalse(status_path(self.root).exists())

    def test_invalid_status_receipts_fail_closed(self):
        path = status_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        for content in (
            b'not json',
            b'X' * 5000,
            json.dumps({'schema_version': 1, 'status': 'review_required',
                        'checked_at_utc': '2026-10-24',
                        'catalog_key': 'f' * 64,
                        'assets_ready': True,
                        'can_send_packets': False}).encode(),
        ):
            path.write_bytes(content)
            self.assertIsNone(read_launcher_status(root=self.root))

    def test_launcher_source_runs_preparation_before_gui(self):
        with patch.object(launcher, 'ensure_extractor_environment',
                          side_effect=lambda python, root: python):
            # PIL is present in CI (this case exercises that normal branch).
            with patch.object(launcher.subprocess, 'run',
                              side_effect=[Mock(returncode=0), Mock(returncode=0)]) as run:
                self.assertEqual(launcher.main(), 0)
        self.assertIn('wlre.services.world.launcher_catalog',
                      run.call_args_list[0].args[0])
        self.assertIn('--progress', run.call_args_list[0].args[0])
        self.assertEqual(run.call_args_list[1].args[0][1:],
                         ['-m', 'wlre.ui.gui'])

    def test_native_entry_invokes_same_service_before_tk(self):
        # A compiled EXE must not spawn a private Python launcher.
        import inspect
        source = inspect.getsource(WLRE_Client.main)
        self.assertLess(source.index('run_with_progress(prepare_on_launch)'),
                        source.index('from wlre.ui.gui import main as run_gui'))

    def test_progress_relay_keeps_unapproved_status(self):
        events = []
        def fake_runner(**kwargs):
            kwargs['progress']('official_version', {})
            kwargs['progress']('bundle_sync', {'count': 2, 'bytes': 1024})
            return {'status': 'review_required', 'catalog_key': 'a'*64}
        result = prepare_on_launch(
            root=self.root, runner=fake_runner, environ={},
            progress=lambda phase, details: events.append((phase, details)))
        self.assertEqual([x[0] for x in events], ['official_version', 'bundle_sync'])
        self.assertFalse(result['assets_ready'])

    def test_unrecognized_runner_output_is_not_approval(self):
        result = prepare_on_launch(
            root=self.root, environ={},
            runner=Mock(return_value={'status': 'approved', 'catalog_key': 'f'*64}))
        self.assertEqual(result['status'], 'error')


if __name__ == '__main__':
    unittest.main()
