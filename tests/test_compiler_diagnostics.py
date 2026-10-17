"""Opt-in compiler investigation preserves normal and release build defaults."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from tools.build import build_nuitka


class CompilerDiagnosticsTests(unittest.TestCase):
    def test_defaults_keep_cache_and_quiet_scons(self):
        for compiler in ('auto', 'msvc', 'mingw64'):
            command = build_nuitka.make_command('python', compiler=compiler)
            self.assertNotIn('--disable-cache=ccache', command)
            self.assertNotIn('--show-scons', command)

    def test_diagnostic_modes_keep_resources_and_entry_point(self):
        for mode in ('standalone', 'onefile'):
            normal = build_nuitka.make_command('python', mode, compiler='msvc')
            diagnostic = build_nuitka.make_command('python', mode, compiler='msvc', diagnose_compiler=True)
            self.assertEqual(diagnostic[-1], normal[-1])
            self.assertIn('--disable-cache=ccache', diagnostic)
            self.assertIn('--show-scons', diagnostic)
            self.assertEqual([item for item in diagnostic if item not in
                              ('--disable-cache=ccache', '--show-scons')], normal)

    def test_cli_dry_run_applies_diagnostic_options_without_compiling(self):
        with patch.object(build_nuitka, 'run_logged') as run, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(build_nuitka.main(['--dry-run', '--compiler', 'msvc', '--diagnose-compiler']), 0)
        command = json.loads(output.getvalue())['command']
        self.assertIn('--disable-cache=ccache', command)
        self.assertIn('--show-scons', command)
        run.assert_not_called()
