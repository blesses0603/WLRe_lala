"""Startup failures remain failures even when diagnostics cannot be written."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import WLRE_Client as entrypoint


class StartupErrorLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.log = Path(self.temp) / 'logs' / 'error.log'
        self.enterContext(patch('wlre.storage.paths.error_log_file', return_value=self.log))
        self.enterContext(patch.object(sys, 'argv', ['WLRE_Client.py', '--self-test']))
        self.stderr = io.StringIO()
        self.enterContext(patch.object(sys, 'stderr', self.stderr))
        self.start = self.enterContext(patch.object(entrypoint, 'self_test',
                                                   side_effect=RuntimeError('original startup failure')))

    def test_read_only_directory_does_not_mask_startup_failure(self):
        with patch.object(Path, 'mkdir', side_effect=PermissionError('read-only directory')):
            self.assertEqual(entrypoint.main(), 1)
        self.start.assert_called_once()
        self.assertIn('RuntimeError: original startup failure', self.stderr.getvalue())
        self.assertNotIn('PermissionError', self.stderr.getvalue())

    def test_unwritable_error_log_preserves_original_console_traceback(self):
        with patch.object(Path, 'open', side_effect=PermissionError('unwritable log')):
            self.assertEqual(entrypoint.main(), 1)
        self.assertIn('RuntimeError: original startup failure', self.stderr.getvalue())
        self.assertNotIn('PermissionError', self.stderr.getvalue())

    def test_consoleless_failure_with_unwritable_log_returns_one(self):
        with patch.object(sys, 'stderr', None), \
             patch.object(Path, 'open', side_effect=PermissionError('unwritable log')):
            self.assertEqual(entrypoint.main(), 1)
        self.start.assert_called_once()

    def test_broken_console_does_not_mask_failure(self):
        console = Mock()
        console.write.side_effect = OSError('broken pipe')
        with patch.object(sys, 'stderr', console):
            self.assertEqual(entrypoint.main(), 1)
        self.assertIn('original startup failure', self.log.read_text(encoding='utf8'))

    def test_consoleless_writable_log_retains_diagnostics(self):
        with patch.object(sys, 'stderr', None):
            try:
                self.assertEqual(entrypoint.main(), 1)
                self.assertIsNotNone(sys.stderr)
                sys.stderr.flush()
                self.assertIn('RuntimeError: original startup failure',
                              self.log.read_text(encoding='utf8'))
            finally:
                if sys.stderr is not None:
                    sys.stderr.close()

    def test_unavailable_logging_does_not_prevent_successful_startup(self):
        self.start.side_effect = None
        self.start.return_value = 0
        with patch.object(sys, 'stderr', None), \
             patch.object(Path, 'mkdir', side_effect=PermissionError('read-only directory')):
            self.assertEqual(entrypoint.main(), 0)
        self.start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
