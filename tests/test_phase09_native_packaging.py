"""Regression contracts for real native desktop release verification.

These checks do not confuse a Nuitka dry-run with a successful compiled app.
Native compilation and startup are exercised by desktop-packaging.yml.
"""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

from tools.build import build_macos, build_nuitka


ROOT = Path(__file__).resolve().parents[1]


class NativeArchitectureTests(unittest.TestCase):
    def test_matching_macho_architecture_is_accepted(self):
        with patch.object(build_macos.subprocess, 'run',
                          return_value=Mock(stdout='arm64\n')) as run:
            self.assertEqual(build_macos.verify_binary_arch('app-binary', 'arm64'), ['arm64'])
        self.assertEqual(run.call_args.args[0], ['lipo', '-archs', 'app-binary'])
        self.assertTrue(run.call_args.kwargs['check'])

    def test_intel_arch_is_checked_independently_of_apple_silicon(self):
        with patch.object(build_macos.subprocess, 'run',
                          return_value=Mock(stdout='x86_64\n')):
            self.assertEqual(build_macos.verify_binary_arch('app-binary', 'x64'), ['x86_64'])
            with self.assertRaisesRegex(ValueError, '架構不符'):
                build_macos.verify_binary_arch('app-binary', 'arm64')

    def test_incorrect_arch_and_lipo_errors_cannot_pass(self):
        with patch.object(build_macos.subprocess, 'run',
                          return_value=Mock(stdout='arm64\n')):
            with self.assertRaisesRegex(ValueError, 'x86_64'):
                build_macos.verify_binary_arch('app-binary', 'x64')
        with patch.object(build_macos.subprocess, 'run',
                          side_effect=subprocess.CalledProcessError(1, 'lipo')):
            with self.assertRaises(subprocess.CalledProcessError):
                build_macos.verify_binary_arch('app-binary', 'arm64')

    def test_both_plans_package_same_required_resources(self):
        windows = build_nuitka.make_command('python', compiler='msvc')
        mac_arm = build_macos.make_command('python', arch='arm64')
        mac_intel = build_macos.make_command('python', arch='x64')
        def resource_targets(command):
            return {
                option.split('=', 2)[-1]
                for option in command
                if option.startswith('--include-data-files=')
            }
        # Paths vary by host but each build plan uses the exact same shipped assets.
        self.assertEqual(resource_targets(windows), resource_targets(mac_arm))
        self.assertEqual(resource_targets(mac_arm), resource_targets(mac_intel))
        for target in ('wlre/resources/item_icons.zip',
                       'wlre/resources/navigation_data.zip',
                       'wlre/resources/emoji_images.zip',
                       'wlre/resources/assets/exp_background.png'):
            self.assertIn(target, resource_targets(windows))


class WorkflowVerificationTests(unittest.TestCase):
    def test_native_compilation_is_manual_only_and_remains_fully_tested(self):
        workflow = (ROOT / '.github/workflows/desktop-packaging.yml').read_text(encoding='utf8')
        event_block = workflow.split('on:\n', 1)[1].split('\npermissions:', 1)[0]
        self.assertIn('workflow_dispatch:', event_block)
        self.assertNotIn('pull_request:', event_block)
        self.assertNotIn('push:', event_block)
        daily = (ROOT / '.github/workflows/test.yml').read_text(encoding='utf8')
        self.assertIn('pull_request:', daily)
        self.assertIn('os: [ubuntu-latest, windows-2022, macos-15]', daily)

        for runner in ('windows-2022', 'macos-15', 'macos-15-intel'):
            self.assertIn('runner: ' + runner, workflow)
        self.assertIn('python -m unittest discover -s tests -q', workflow)
        self.assertIn('tools.build.build_nuitka --mode standalone --compiler msvc', workflow)
        self.assertIn('tools.build.build_macos --arch', workflow)
        self.assertIn('tools.build.release_nuitka --tag', workflow)
        self.assertIn('tools.build.release_macos --tag', workflow)
        self.assertIn('if-no-files-found: error', workflow)

    def test_compiled_executables_are_launched_not_just_planned(self):
        windows_source = (ROOT / 'tools/build/build_nuitka.py').read_text(encoding='utf8')
        mac_source = (ROOT / 'tools/build/build_macos.py').read_text(encoding='utf8')
        self.assertIn("run_logged([str(executable),'--self-test'],log)", windows_source)
        self.assertIn("run_logged([str(executable),'--smoke-test-gui'],log)", windows_source)
        self.assertIn("run_logged([str(executable), '--self-test'], log)", mac_source)
        self.assertIn("run_logged([str(executable), '--smoke-test-gui'], log)", mac_source)
        self.assertIn('verify_binary_arch(executable, arch)', mac_source)
        self.assertIn("run_logged(['codesign', '--verify', '--deep', '--strict', str(bundle)], log)", mac_source)


if __name__ == '__main__':
    unittest.main()
