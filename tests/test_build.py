"""Build planning and bundled self-test, with no compiler or server required."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.build import build_nuitka
import WLRE_Client

class BuildPlan(unittest.TestCase):
    def test_resource_list_is_complete_and_contains_no_code(self):
        files=build_nuitka.data_files()
        expected={p for p in (build_nuitka.ROOT/'wlre').rglob('*') if p.is_file() and p.suffix in build_nuitka.DATA_SUFFIXES and not p.name.startswith('.')}
        self.assertEqual(set(files),expected)
        self.assertTrue(any(p.name=='emoji_images.zip' for p in files))
        self.assertTrue(any(p.name=='navigation_data.zip' for p in files))
        self.assertFalse(any(p.suffix in ('.py','.pyc') for p in files))
    def test_direct_entry_and_shared_icon(self):
        command=build_nuitka.make_command('python.exe')
        self.assertEqual(Path(command[-1]).name,'WLRE_Client.py')
        self.assertNotIn('start_ui.py',command)
        self.assertIn('--enable-plugin=tk-inter',command)
        self.assertIn('--include-package=wlre',command)
        self.assertIn('--windows-icon-from-ico='+str(build_nuitka.ROOT/'wlre/resources/assets/app.ico'),command)
        self.assertEqual(sum(v.startswith('--include-data-files=') for v in command),len(build_nuitka.data_files()))
    def test_modes_and_compilers(self):
        self.assertIn('--mode=onefile',build_nuitka.make_command('python.exe','onefile'))
        self.assertIn('--msvc=latest',build_nuitka.make_command('python.exe',compiler='msvc'))
        self.assertIn('--mingw64',build_nuitka.make_command('python.exe',compiler='mingw64'))
    def test_msvc_bypasses_mbcs_compiler_cache_in_both_modes(self):
        for mode in ('standalone', 'onefile'):
            command = build_nuitka.make_command('python.exe', mode, compiler='msvc')
            self.assertIn('--msvc=latest', command)
            self.assertIn('--disable-cache=ccache', command)
            self.assertNotIn('--disable-cache=all', command)
        self.assertNotIn('--disable-cache=ccache',
                         build_nuitka.make_command('python.exe', compiler='mingw64'))

    def test_compiler_language_and_utf8_are_explicit_without_mutating_parent(self):
        source = {'VSLANG': '1028', 'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp950'}
        env = build_nuitka.build_environment(source)
        self.assertEqual(env['VSLANG'], '1033')
        self.assertEqual(env['PYTHONUTF8'], '1')
        self.assertEqual(env['PYTHONIOENCODING'], 'utf-8')
        self.assertEqual(source['VSLANG'], '1028')

    def test_dry_run_does_not_install_or_compile(self):
        with patch.object(build_nuitka,'run_logged') as run,contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(build_nuitka.main(['--dry-run']),0)
            self.assertEqual(json.loads(output.getvalue())['resource_count'],len(build_nuitka.data_files()))
            run.assert_not_called()
    def test_build_environment_does_not_inherit_other_python(self):
        source={'PYTHONPATH':'other-project','PYTHONHOME':'other-python','KEEP':'yes'}
        env=build_nuitka.build_environment(source)
        self.assertNotIn('PYTHONPATH',env)
        self.assertNotIn('PYTHONHOME',env)
        self.assertEqual(env['KEEP'],'yes')
        self.assertEqual(source['PYTHONHOME'],'other-python')
        self.assertEqual(env['PYTHONUNBUFFERED'],'1')
    def test_python314_uses_msvc(self):
        self.assertEqual(build_nuitka.select_compiler(version=(3,14),msvc_available=True),'msvc')
    def test_python313_uses_msvc(self):
        self.assertEqual(build_nuitka.select_compiler(version=(3,13),msvc_available=True),'msvc')
    def test_python312_can_download_mingw(self):
        self.assertEqual(build_nuitka.select_compiler(version=(3,12),msvc_available=False),'mingw64')
    def test_python314_missing_compiler_explained(self):
        with self.assertRaisesRegex(RuntimeError,r'使用 C\+\+ 的桌面開發'):
            build_nuitka.select_compiler(version=(3,14),msvc_available=False)
    def test_mingw_rejected_on_python314(self):
        with self.assertRaisesRegex(RuntimeError,'不使用 MinGW64'):
            build_nuitka.select_compiler('mingw64',version=(3,14),msvc_available=False)
    def test_explicit_msvc_requires_actual_install(self):
        with self.assertRaisesRegex(RuntimeError,'未找到 MSVC'):
            build_nuitka.select_compiler('msvc',version=(3,12),msvc_available=False)
    def test_packaged_resource_self_test(self):
        self.assertEqual(WLRE_Client.self_test(),0)

if __name__=='__main__':unittest.main(verbosity=2)
