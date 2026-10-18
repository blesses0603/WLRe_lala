"""Regression coverage for resource contracts and compatible preference migration."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from wlre.paths import RESOURCE_ROOT
from wlre.resource_manifest import REQUIRED_RESOURCES,require_resources,validate_resources
from wlre.storage import expedition_settings
from wlre.services.items.crafting_browser_model import Favorites,RECIPES


class ArchitectureRegressionTests(unittest.TestCase):
    def test_missing_expedition_or_button_rejected(self):
        for missing in ('expedition_catalog.json','assets/buttons/Btn_Bag.png'):
            with self.subTest(missing=missing),tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                for name in REQUIRED_RESOURCES:
                    if name==missing:continue
                    target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.touch()
                with self.assertRaisesRegex(RuntimeError,missing):require_resources(root)

    def test_corrupt_extra_image_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in REQUIRED_RESOURCES:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.symlink_to(RESOURCE_ROOT/name)
            (root/'broken.png').write_bytes(b'not an image')
            with self.assertRaises(OSError):validate_resources(root)

    def test_expedition_account_isolation_and_validation(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'LOCALAPPDATA':temp}):
            first='a'*64;second='b'*64
            value=expedition_settings.load(first);value['min_hours']=6
            expedition_settings.save(first,value)
            self.assertEqual(expedition_settings.load(first)['min_hours'],6)
            self.assertEqual(expedition_settings.load(second)['min_hours'],0)
            with self.assertRaises(ValueError):expedition_settings.settings_file('../bad')

    def test_favorites_migrate_once_preserving_original(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'LOCALAPPDATA':temp}):
            legacy=Path(temp)/'old.json';item=int(next(iter(RECIPES)))
            original=json.dumps({'version':1,'items':[item]});legacy.write_text(original)
            with patch('wlre.services.items.crafting_browser_model.legacy_favorites_file',return_value=legacy):
                migrated=Favorites();self.assertEqual(migrated.ids,[item])
                self.assertEqual(legacy.read_text(),original)
                migrated.path.write_text('{"version":1,"items":[]}')
                self.assertEqual(Favorites().ids,[])

    def test_portal_policy_has_no_ui_dependency(self):
        source=Path('wlre/services/world/portal_policy.py').read_text()
        self.assertNotIn('wlre.ui',source)
