"""Launcher splash view-model tests: no official network and no real Tk required."""
import io
import os
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
import unittest

from wlre.launcher_progress import (
    STEPS, _format_stage, progress_message, run_with_progress,
)
from wlre.services.world import launcher_catalog


class LauncherProgressTests(unittest.TestCase):
    def test_real_stage_text_is_not_a_fake_percentage(self):
        self.assertIn('DataPackage',
                      progress_message('manifest', {'package': 'DataPackage'}))
        self.assertIn('2 個 Bundle',
                      progress_message('bundle_sync',
                                       {'count': 2, 'bytes': 4*1024*1024}))
        self.assertIn('4.0 MiB',
                      progress_message('bundle_sync',
                                       {'count': 2, 'bytes': 4*1024*1024}))
        self.assertIn('本機快取',
                      progress_message('bundle_sync',
                                       {'count': 0, 'bytes': 0}))
        self.assertIn('商店', progress_message('extract', {'feature': 'shops'}))
        self.assertIn('Eve 二進位事件', progress_message(
            'extract_failed', {'feature': 'npc', 'stage': 'Eve 二進位事件'}))
        self.assertNotIn('secret', progress_message(
            'extract_failed', {'feature': 'npc', 'stage': 'C:/secret'}))
        self.assertIn('1 / 3', progress_message(
            'bundle_item', {'completed': 1, 'total': 3}))
        self.assertIn('21767', progress_message(
            'classification_ready', {'total': 21767, 'existing': 160}))
        self.assertIn('現有官方資源索引分類',
                      _format_stage('classification_ready'))
        self.assertNotIn('12345678', progress_message(
            'classification_ready', {'total': '12345678', 'existing': 160}))
        self.assertEqual(_format_stage('bundle_item'), _format_stage('bundle_sync'))

        self.assertEqual(_format_stage('official_version'), f'第 1 / {len(STEPS)} 階段')
        self.assertEqual(_format_stage('candidate_write'),
                         f'第 {len(STEPS)} / {len(STEPS)} 階段')
        self.assertNotIn('%', progress_message('bundle_sync', {'count': 1, 'bytes': 10}))

    def test_untrusted_event_details_are_not_displayed(self):
        self.assertNotIn('C:\\secret', progress_message(
            'manifest', {'package': 'C:\\secret'}))
        self.assertNotIn('evil', progress_message('extract', {'feature': 'evil'}))
        self.assertNotIn('999999', progress_message(
            'bundle_sync', {'count': '999999', 'bytes': 123}))

    def test_headless_fallback_is_interpretable(self):
        phases = []
        def task(*, progress=None):
            progress('official_version', {})
            progress('manifest', {'package': 'MainPackage'})
            phases.append('complete')
            return {'status': 'review_required'}
        with patch.dict(os.environ, {'WLRE_DISABLE_AUTO_CATALOG': ''}, clear=False), \
             patch('wlre.launcher_progress.sys.platform', 'linux'), \
             patch.dict(os.environ, {'DISPLAY': ''}), \
             redirect_stdout(io.StringIO()) as output:
            outcome = run_with_progress(task)
        self.assertEqual(outcome['status'], 'review_required')
        self.assertEqual(phases, ['complete'])
        self.assertIn('MainPackage', output.getvalue())

    def test_explicit_test_mode_skips_window_and_callbacks(self):
        task = Mock(return_value={'status': 'skipped'})
        with patch.dict(os.environ, {'WLRE_DISABLE_AUTO_CATALOG': '1'}):
            result = run_with_progress(task)
        task.assert_called_once_with()
        self.assertEqual(result['status'], 'skipped')

    def test_progress_cli_uses_same_launcher_service(self):
        with patch('wlre.launcher_progress.run_with_progress',
                   return_value={'status': 'review_required'}) as view, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(launcher_catalog.main(['--progress']), 0)
        self.assertIs(view.call_args.args[0], launcher_catalog.prepare_on_launch)

    @unittest.skipUnless(os.name == 'nt' or bool(os.environ.get('DISPLAY')),
                         'Requires an active desktop / Xvfb')
    def test_real_tk_splash_finishes_and_returns_candidate(self):
        """Isolate actual Tk creation/destruction in a bounded child process.

        Tk's native handlers can outlive a unittest fixture when many roots
        are created in the parent process; a failed splash must not hang CI.
        """
        import subprocess
        import sys
        code = """
from wlre.launcher_progress import run_with_progress
def task(*, progress):
    progress('official_version', {})
    progress('manifest', {'package': 'DataPackage'})
    progress('bundle_sync', {'count': 1, 'bytes': 4096})
    progress('bundle_item', {'completed': 1, 'total': 1, 'action': 'cached'})
    progress('candidate_ready', {})
    return {'status': 'review_required', 'assets_ready': False}
result = run_with_progress(task)
assert result['status'] == 'review_required'
assert result['assets_ready'] is False
"""
        env = dict(os.environ, WLRE_DISABLE_AUTO_CATALOG='')
        result = subprocess.run(
            [sys.executable, '-c', code], env=env, capture_output=True,
            text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bad_cli_arguments_refused_without_download(self):
        with patch.object(launcher_catalog, 'prepare_on_launch') as prepare, \
             redirect_stdout(io.StringIO()), \
             patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(launcher_catalog.main(['--wrong']), 2)
        prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
