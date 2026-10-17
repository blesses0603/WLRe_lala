import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.build import build_nuitka


class BuildEnvironmentRepairTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = self.root / 'py3.14'
        self.python = self.environment / 'Scripts/python.exe'
        self.log = self.root / 'build.log'

    def existing_environment(self):
        self.python.parent.mkdir(parents=True)
        self.python.write_bytes(b'fixture')

    def test_healthy_environment_is_reused_without_reinstall(self):
        self.existing_environment()
        with patch.object(build_nuitka, 'run_logged') as run, patch.object(build_nuitka.venv, 'EnvBuilder') as builder:
            self.assertEqual(build_nuitka.prepare_environment(self.environment, self.log), self.python)
            builder.assert_not_called()
            run.assert_called_once_with([str(self.python), '-m', 'pip', '--version'], self.log)

    def test_broken_pip_rebuilds_and_checks_again_before_use(self):
        self.existing_environment()
        marker = self.environment / 'dependencies.sha256'
        marker.write_text('obsolete')
        def rebuild(directory):
            # Model venv clear=True deleting the prior dependency signature.
            self.assertEqual(directory, self.environment)
            marker.unlink()
        with patch.object(build_nuitka, 'run_logged', side_effect=[RuntimeError('ImportError: Traceback'), None]) as run, patch.object(build_nuitka.venv, 'EnvBuilder') as builder:
            builder.return_value.create.side_effect = rebuild
            self.assertEqual(build_nuitka.prepare_environment(self.environment, self.log), self.python)
            builder.assert_called_once_with(with_pip=True, clear=True)
            builder.return_value.create.assert_called_once_with(self.environment)
            self.assertEqual(run.call_count, 2)
            self.assertFalse(marker.exists())
            self.assertIn('重新建立專用環境', self.log.read_text(encoding='utf8'))

    def test_repair_failure_stops_without_retry_loop(self):
        self.existing_environment()
        with patch.object(build_nuitka, 'run_logged', side_effect=RuntimeError('broken')) as run, patch.object(build_nuitka.venv, 'EnvBuilder') as builder:
            with self.assertRaises(RuntimeError):
                build_nuitka.prepare_environment(self.environment, self.log)
            self.assertEqual(run.call_count, 2)
            builder.return_value.create.assert_called_once_with(self.environment)

    def test_new_environment_is_created_and_verified(self):
        with patch.object(build_nuitka, 'run_logged') as run, patch.object(build_nuitka.venv, 'EnvBuilder') as builder:
            build_nuitka.prepare_environment(self.environment, self.log)
            builder.assert_called_once_with(with_pip=True)
            builder.return_value.create.assert_called_once_with(self.environment)
            run.assert_called_once_with([str(self.python), '-m', 'pip', '--version'], self.log)
