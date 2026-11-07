"""The navigation shortcut uses official preparation, never legacy seed UI."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from wlre import launcher


class NavigationLauncherTests(unittest.TestCase):
    def test_navigation_shortcut_uses_shared_app_and_extractor(self):
        private=Path('/private-tested-python')
        with (patch.object(launcher.sys,'argv',['launcher','--navigation']),
              patch.object(launcher,'ensure_extractor_environment',return_value=private) as extractor,
              patch.object(launcher.subprocess,'run',return_value=SimpleNamespace(returncode=7)) as run,
              patch('builtins.print') as output):
            self.assertEqual(launcher.main(),7)
        extractor.assert_called_once()
        self.assertEqual(run.call_args.args[0],[str(private),'-m','wlre.ui.gui'])
        self.assertIn('主頁開啟導航預覽',output.call_args.args[0])

    def test_navigation_requires_pinned_extractor_probe(self):
        python=Path('/test-python');root=Path(__file__).resolve().parents[1]
        with (patch.object(launcher.sys,'argv',['launcher','--navigation']),
              patch.object(launcher.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run):
            self.assertEqual(launcher.ensure_extractor_environment(python,root),python)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][:2],[str(python),'-c'])
        self.assertIn('import UnityPy',run.call_args.args[0][2])

    def test_self_test_still_skips_dependency_setup(self):
        python=Path('/test-python')
        with (patch.object(launcher.sys,'argv',['launcher','--self-test']),
              patch.object(launcher.subprocess,'run') as run):
            self.assertEqual(launcher.ensure_extractor_environment(python,Path('/absent')),python)
        run.assert_not_called()


if __name__=='__main__':unittest.main()
