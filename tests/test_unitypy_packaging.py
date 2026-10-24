"""Keep UnityFS decoder inside native distributions, not as a user's pip step."""
import contextlib
import importlib.util
import io
from pathlib import Path
import unittest

import WLRE_Client
from tools.build import build_nuitka, build_macos

ROOT = Path(__file__).resolve().parents[1]


class ExtractorBuildContractTests(unittest.TestCase):
    def test_nuitka_windows_and_both_macos_architectures_bundle_unitypy(self):
        plans = (
            build_nuitka.make_command('python', mode='standalone'),
            build_nuitka.make_command('python', mode='onefile'),
            build_macos.make_command('python', arch='arm64'),
            build_macos.make_command('python', arch='x64'),
        )
        for command in plans:
            with self.subTest(command=command[1:4]):
                self.assertIn('--include-package=UnityPy', command)
                self.assertIn('--include-package-data=UnityPy', command)
                self.assertIn('--include-package=wlre', command)
                self.assertEqual(command.count('--include-package=UnityPy'), 1)
                self.assertTrue(command[-1].endswith('WLRE_Client.py'))

    def test_build_dependency_is_pinned_and_ci_cache_tracks_it(self):
        spec = (ROOT / 'requirements-extractor.txt').read_text(encoding='utf-8')
        self.assertIn('UnityPy==1.25.4', spec)
        self.assertIn('-r requirements-extractor.txt',
                      (ROOT / 'requirements-build.txt').read_text(encoding='utf-8'))
        for path in (
            '.github/workflows/test.yml',
            '.github/workflows/desktop-packaging.yml',
            '.github/workflows/release-windows.yml',
        ):
            content = (ROOT / path).read_text(encoding='utf-8')
            self.assertIn('requirements-extractor.txt', content)
            self.assertIn('WLRE_DISABLE_AUTO_CATALOG:', content)
        source = (ROOT / '.github/workflows/test.yml').read_text(encoding='utf-8')
        self.assertIn('python WLRE_Client.py --self-test-unityfs', source)
        win_source = (ROOT / 'tools/build/build_nuitka.py').read_text(encoding='utf-8')
        mac_source = (ROOT / 'tools/build/build_macos.py').read_text(encoding='utf-8')
        self.assertIn("run_logged([str(executable),'--self-test-unityfs'],log)", win_source)
        self.assertIn("run_logged([str(executable), '--self-test-unityfs'], log)", mac_source)
        self.assertIn('requirements-extractor.txt', win_source)

    @unittest.skipUnless(importlib.util.find_spec('UnityPy') is not None,
                         'Optional source dependency not installed; native build always installs it')
    def test_actual_unitypy_native_codec_roundtrip(self):
        with contextlib.redirect_stdout(io.StringIO()) as buffer:
            self.assertEqual(WLRE_Client.self_test_unityfs(), 0)
        self.assertIn('UnityFS runtime self-test passed', buffer.getvalue())

    @unittest.skipUnless(importlib.util.find_spec('UnityPy') is not None,
                         'Optional source dependency not installed')
    def test_native_codec_corruption_fails_closed(self):
        from unittest.mock import patch
        with patch('lz4.block.decompress', return_value=b'corrupt'):
            with self.assertRaisesRegex(RuntimeError, 'LZ4'):
                WLRE_Client.self_test_unityfs()


if __name__ == '__main__':
    unittest.main()
