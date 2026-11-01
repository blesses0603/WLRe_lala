from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from wlre.paths import RESOURCE_ROOT
from wlre.storage.full_resource_seed import build_seed, SEED_NAME
from wlre.resource_manifest import validate_resources, data_files


class SeedOnlyRuntimeTests(unittest.TestCase):
    def test_configuration_selftest_and_package_inventory_without_originals(self):
        from wlre.storage import defaults, server_lines
        from wlre.services import resource_compatibility
        with tempfile.TemporaryDirectory() as folder:
            package=Path(folder)/'wlre';root=package/'resources';root.mkdir(parents=True)
            shutil.copytree(RESOURCE_ROOT/'assets',root/'assets')
            build_seed(RESOURCE_ROOT,root/SEED_NAME)
            with patch.object(defaults,'RESOURCE_ROOT',root),patch.object(server_lines,'RESOURCE_ROOT',root),patch.object(resource_compatibility,'RESOURCE_ROOT',root):
                self.assertTrue(defaults.load_default_profile()['game_endpoint'])
                self.assertTrue(server_lines.load())
                self.assertEqual(resource_compatibility.load_supported_resources()['schema_version'],1)
            validate_resources(root)
            files=data_files(package,compact=True)
            self.assertIn(root/SEED_NAME,files)
            self.assertFalse(any(p.suffix in ('.json','.zip','.gz') for p in files))

    def test_fresh_process_import_and_selftest_with_only_database_and_images(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            for source in RESOURCE_ROOT.parent.rglob('*.py'):
                target=base/'wlre'/source.relative_to(RESOURCE_ROOT.parent)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
            root=base/'wlre'/'resources';root.mkdir()
            shutil.copytree(RESOURCE_ROOT/'assets',root/'assets')
            build_seed(RESOURCE_ROOT,root/SEED_NAME)
            shutil.copy2(RESOURCE_ROOT.parent.parent/'WLRE_Client.py',base/'WLRE_Client.py')
            env=dict(os.environ,LOCALAPPDATA=str(base/'new_user'),WLRE_DISABLE_AUTO_CATALOG='1')
            for args in (['WLRE_Client.py','--self-test'],['-c','from wlre.ui.gui import App;from wlre.storage.defaults import load_default_profile;from wlre.storage.server_lines import load;assert load();assert load_default_profile()']):
                result=subprocess.run([sys.executable,*args],cwd=base,env=env,capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
