import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from tools.build import build_nuitka
from wlre import launcher


class DependencyCache(unittest.TestCase):
    def test_repeat_build_validates_without_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            environment=Path(directory)
            with patch.object(build_nuitka,'run_logged') as run:
                build_nuitka.prepare_dependencies('python',environment,environment/'build.log')
                self.assertTrue((environment/'dependencies.sha256').exists())
                run.reset_mock()
                build_nuitka.prepare_dependencies('python',environment,environment/'build.log')
                commands=[call.args[0] for call in run.call_args_list]
                self.assertEqual(len(commands),2)
                self.assertFalse(any('install' in command for command in commands))

    def test_failed_cached_probe_repairs_and_failed_install_leaves_no_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            environment=Path(directory);log=environment/'build.log'
            with patch.object(build_nuitka,'run_logged'):
                build_nuitka.prepare_dependencies('python',environment,log)
            with patch.object(build_nuitka,'run_logged',side_effect=RuntimeError('broken')):
                with self.assertRaises(RuntimeError):build_nuitka.prepare_dependencies('python',environment,log)
            self.assertFalse((environment/'dependencies.sha256').exists())

    def test_ui_requirement_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);environment=root/'env';environment.mkdir()
            (root/'requirements-build.txt').write_text('-r requirements-ui.txt\n-r requirements-extractor.txt')
            (root/'requirements-ui.txt').write_text('Pillow>=10')
            (root/'requirements-extractor.txt').write_text('UnityPy==1.25.4')
            with patch.object(build_nuitka,'ROOT',root),patch.object(build_nuitka,'run_logged') as run:
                build_nuitka.prepare_dependencies('python',environment,root/'build.log')
                (root/'requirements-ui.txt').write_text('Pillow>=11')
                run.reset_mock()
                build_nuitka.prepare_dependencies('python',environment,root/'build.log')
                self.assertTrue(any('install' in call.args[0] for call in run.call_args_list))

    def test_extractor_requirement_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);environment=root/'env';environment.mkdir()
            (root/'requirements-build.txt').write_text('-r requirements-ui.txt\n-r requirements-extractor.txt')
            (root/'requirements-ui.txt').write_text('Pillow>=10')
            (root/'requirements-extractor.txt').write_text('UnityPy==1.25.4')
            with patch.object(build_nuitka,'ROOT',root),patch.object(build_nuitka,'run_logged') as run:
                build_nuitka.prepare_dependencies('python',environment,root/'build.log')
                run.reset_mock()
                (root/'requirements-extractor.txt').write_text('UnityPy==1.25.3')
                build_nuitka.prepare_dependencies('python',environment,root/'build.log')
                self.assertTrue(any('install' in call.args[0] for call in run.call_args_list))

    def test_force_upgrade_installs_even_with_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            environment=Path(directory);log=environment/'build.log'
            with patch.object(build_nuitka,'run_logged') as run:
                build_nuitka.prepare_dependencies('python',environment,log)
                run.reset_mock();build_nuitka.prepare_dependencies('python',environment,log,upgrade=True)
                self.assertTrue(any('install' in call.args[0] and 'pip'==call.args[0][-1] for call in run.call_args_list))


class StartupSerialization(unittest.TestCase):
    def test_missing_images_uses_shared_lock_and_rechecks_after_install(self):
        import builtins
        original=builtins.__import__
        def importing(name,*args,**kwargs):
            if name=='PIL':raise ImportError('fixture')
            return original(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=importing),patch.object(launcher,'file_lock',return_value=nullcontext()) as lock,patch.object(launcher.subprocess,'run',side_effect=[Mock(returncode=1),Mock(returncode=0),Mock(returncode=0),Mock(returncode=0)]) as run,patch.object(launcher.venv,'EnvBuilder'):
            self.assertEqual(launcher.main(),0)
            lock.assert_called_once()
            self.assertEqual(lock.call_args.kwargs['timeout'],300)
            self.assertIn('install',run.call_args_list[1].args[0])
            self.assertTrue(run.call_args_list[2].kwargs['check'])
