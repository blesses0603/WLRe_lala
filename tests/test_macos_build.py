import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.build import build_macos, release_macos
from wlre import __version__


class MacBuildPlanning(unittest.TestCase):
    def test_native_architecture_aliases_and_rejection(self):
        for machine, arch in [('arm64', 'arm64'), ('aarch64', 'arm64'), ('x86_64', 'x64')]:
            self.assertEqual(build_macos.native_arch(machine), arch)
        with self.assertRaises(ValueError):
            build_macos.native_arch('unknown')

    def test_app_command_contains_resources_without_windows_options(self):
        for arch, target in [('arm64', 'arm64'), ('x64', 'x86_64')]:
            command = build_macos.make_command('python', arch=arch)
            self.assertIn('--macos-create-app-bundle', command)
            self.assertIn('--output-folder-name=WLRe_LaLa', command)
            self.assertIn('--output-filename=WLRe_LaLa', command)
            self.assertIn('--macos-app-name=WLRe_LaLa', command)
            self.assertIn('--macos-target-arch=' + target, command)
            self.assertIn('--macos-app-version=' + __version__, command)
            self.assertIn('--enable-plugin=tk-inter', command)
            self.assertFalse(any(item.startswith(('--windows-', '--msvc', '--mingw')) for item in command))
            self.assertEqual(sum(item.startswith('--include-data-files=') for item in command),
                             len(build_macos.data_files()))
            self.assertEqual(Path(command[-1]).name, 'WLRE_Client.py')
        with self.assertRaises(ValueError):
            build_macos.make_command('python', arch='universal')

    def test_dry_run_never_runs_compiler(self):
        with patch.object(build_macos, 'run_logged') as run, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(build_macos.main(['--arch', 'arm64', '--dry-run']), 0)
        self.assertEqual(json.loads(output.getvalue())['arch'], 'arm64')
        run.assert_not_called()

    def test_wrong_host_and_cross_arch_build_fail_before_compiler(self):
        with patch.object(build_macos, 'run_logged') as run, patch.object(build_macos.sys, 'platform', 'linux'), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_macos.main(['--arch', 'arm64'])
            run.assert_not_called()
        with patch.object(build_macos, 'run_logged') as run, patch.object(build_macos.sys, 'platform', 'darwin'), patch.object(build_macos, 'native_arch', return_value='x64'), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_macos.main(['--arch', 'arm64'])
            run.assert_not_called()


class MacReleasePackaging(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bundle = self.root / 'dist_nuitka/macos_arm64/WLRe_LaLa.app'
        (self.bundle / 'Contents/MacOS').mkdir(parents=True)
        self.executable = self.bundle / 'Contents/MacOS/fixture-client'
        self.executable.write_bytes(b'fixture executable')
        self.executable.chmod(0o755)
        with (self.bundle / 'Contents/Info.plist').open('wb') as stream:
            plistlib.dump({'CFBundleExecutable': 'fixture-client'}, stream)

    def fake_ditto(self, command, check):
        self.assertTrue(check)
        self.assertEqual(command[:5], ['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent'])
        with zipfile.ZipFile(command[-1], 'w') as bundle:
            for item in self.bundle.rglob('*'):
                if item.is_file():
                    bundle.write(item, self.bundle.name + '/' + item.relative_to(self.bundle).as_posix())

    def test_plist_controls_executable_and_cannot_escape_bundle(self):
        self.assertEqual(build_macos.bundle_executable(self.bundle), self.executable)
        with (self.bundle / 'Contents/Info.plist').open('wb') as stream:
            plistlib.dump({'CFBundleExecutable': '../outside'}, stream)
        with self.assertRaises(ValueError):
            build_macos.bundle_executable(self.bundle)

    def test_ditto_zip_and_arch_specific_checksum(self):
        with patch.object(release_macos.subprocess, 'run', side_effect=self.fake_ditto):
            archive, checksum = release_macos.package_release('v' + __version__, 'arm64', self.root)
        self.assertIn('_macos_arm64.zip', archive.name)
        self.assertEqual(checksum.name, 'SHA256SUMS_macos_arm64.txt')
        self.assertEqual(checksum.read_text(), hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
        with zipfile.ZipFile(archive) as bundle:
            self.assertIn('WLRe_LaLa.app/Contents/MacOS/fixture-client', bundle.namelist())
            self.assertIsNone(bundle.testzip())
        self.assertFalse(archive.with_suffix('.zip.tmp').exists())

    def test_missing_entry_point_and_wrong_arch_prevent_packaging(self):
        with patch.object(release_macos.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                release_macos.package_release('v' + __version__, 'universal', self.root)
            self.executable.unlink()
            with self.assertRaises(ValueError):
                release_macos.package_release('v' + __version__, 'arm64', self.root)
            run.assert_not_called()

    def test_failed_crc_preserves_previous_archive(self):
        with patch.object(release_macos.subprocess, 'run', side_effect=self.fake_ditto):
            archive, checksum = release_macos.package_release('v' + __version__, 'arm64', self.root)
            previous = archive.read_bytes(), checksum.read_bytes()
            with patch.object(zipfile.ZipFile, 'testzip', return_value='bad-entry'):
                with self.assertRaises(ValueError):
                    release_macos.package_release('v' + __version__, 'arm64', self.root)
        self.assertEqual((archive.read_bytes(), checksum.read_bytes()), previous)
        self.assertFalse(archive.with_suffix('.zip.tmp').exists())

    @unittest.skipUnless(sys.platform == 'darwin', 'Requires native macOS ditto')
    def test_native_ditto_preserves_symlinks_and_executable_bits(self):
        link = self.bundle / 'Contents/MacOS/client-link'
        link.symlink_to('fixture-client')
        archive, _ = release_macos.package_release('v' + __version__, 'arm64', self.root)
        with zipfile.ZipFile(archive) as bundle:
            info = bundle.getinfo('WLRe_LaLa.app/Contents/MacOS/client-link')
            self.assertTrue(stat.S_ISLNK(info.external_attr >> 16))
            self.assertEqual(bundle.read(info), b'fixture-client')
            executable = bundle.getinfo('WLRe_LaLa.app/Contents/MacOS/fixture-client')
            self.assertTrue((executable.external_attr >> 16) & stat.S_IXUSR)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin',
                     'Requires a desktop')
class BundledGuiSmokeTest(unittest.TestCase):
    def test_cli_creates_dashboard_and_cleans_up_child_callbacks(self):
        import subprocess
        result = subprocess.run([sys.executable, str(build_macos.ROOT / 'WLRE_Client.py'),
                                 '--smoke-test-gui'], capture_output=True, text=True,
                                encoding='utf8', timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
