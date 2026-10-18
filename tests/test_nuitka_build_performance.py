"""Guard safe Nuitka build acceleration without dropping release content."""
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.build import build_macos, build_nuitka

ROOT = Path(__file__).resolve().parents[1]


class NuitkaPerformanceOptions(unittest.TestCase):
    def test_parallel_default_is_cpu_bounded(self):
        self.assertEqual(build_nuitka.compiler_jobs(cpu_count=1), 1)
        self.assertEqual(build_nuitka.compiler_jobs(cpu_count=4), 4)
        self.assertEqual(build_nuitka.compiler_jobs(cpu_count=32), 6)
        self.assertEqual(build_nuitka.compiler_jobs(cpu_count=0), 1)

    def test_explicit_jobs_preserved_and_invalid_values_fail_fast(self):
        for jobs in (1, 4, 8, 16):
            self.assertEqual(build_nuitka.compiler_jobs(jobs, cpu_count=2), jobs)
        for jobs in (0, -1, 17, '8'):
            with self.assertRaises(ValueError):
                build_nuitka.compiler_jobs(jobs, cpu_count=16)

    def test_windows_dry_run_uses_configured_parallel_jobs(self):
        with patch.object(build_nuitka, 'run_logged') as run, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(build_nuitka.main(['--dry-run', '--jobs', '8']), 0)
        self.assertIn('--jobs=8', json.loads(output.getvalue())['command'])
        run.assert_not_called()

    def test_macos_dry_run_keeps_ccache_and_custom_jobs(self):
        with patch.object(build_macos, 'run_logged') as run, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(build_macos.main(['--dry-run', '--arch', 'arm64', '--jobs', '8']), 0)
        command = json.loads(output.getvalue())['command']
        self.assertIn('--jobs=8', command)
        self.assertNotIn('--disable-cache=ccache', command)
        self.assertIn('--enable-plugin=tk-inter', command)
        run.assert_not_called()

    def test_build_flags_keep_every_asset_and_required_module(self):
        windows = build_nuitka.make_command('python', jobs=8)
        mac = build_macos.make_command('python', arch='arm64', jobs=8)
        for command in (windows, mac):
            self.assertIn('--include-package=wlre', command)
            included = [option for option in command if option.startswith('--include-data-files=')]
            self.assertEqual(len(included), len(build_nuitka.data_files()))
            self.assertIn('--jobs=8', command)
        self.assertEqual(
            {option.split('=', 2)[2] for option in windows if option.startswith('--include-data-files=')},
            {option.split('=', 2)[2] for option in mac if option.startswith('--include-data-files=')},
        )

    def test_ci_caches_are_scoped_by_arch_and_requirements(self):
        desktop = (ROOT / '.github/workflows/desktop-packaging.yml').read_text(encoding='utf8')
        release = (ROOT / '.github/workflows/release-windows.yml').read_text(encoding='utf8')
        for workflow in (desktop, release):
            self.assertIn('NUITKA_CACHE_DIR:', workflow)
            self.assertIn('actions/cache@v4', workflow)
            self.assertIn('requirements-build-macos.txt', workflow)
            self.assertIn('cache: pip', workflow)
        self.assertIn('matrix.label', desktop)
        self.assertIn('macos-${{ matrix.arch }}-py312', release)
        self.assertIn('windows-x64-py312', release)


if __name__ == '__main__':
    unittest.main()
