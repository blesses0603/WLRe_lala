"""Guard feature ownership, retained shared infrastructure and migration scope."""
import ast
import importlib
from pathlib import Path
import unittest

from tools.architecture.inventory import ROOT, config, owner
from tools.architecture.test_features import selected_tests


class FeatureArchitecture(unittest.TestCase):
    def test_feature_ownership_is_unambiguous_and_version_is_unchanged(self):
        spec = config()
        moves = [old for value in spec['features'].values() for old in value['moves']]
        self.assertEqual(len(moves), len(set(moves)))
        from wlre import __version__
        self.assertEqual(__version__, '0.6.1')
        for name, feature in spec['features'].items():
            for old, target in feature['moves'].items():
                self.assertEqual(owner(old, spec), name)
                self.assertTrue(target.startswith('wlre.features.' + name + '.'))

    def test_migrated_public_modules_keep_identity_and_patch_points(self):
        spec = config()
        for name, feature in spec['features'].items():
            if feature.get('status') != 'implemented': continue
            for old, target in feature['moves'].items():
                with self.subTest(feature=name, old=old):
                    self.assertIs(importlib.import_module(old), importlib.import_module(target))

    def test_feature_domains_do_not_import_tk_or_socket(self):
        root = ROOT / 'wlre/features'
        if not root.exists(): return
        for path in root.glob('*/domain/**/*.py'):
            tree = ast.parse(path.read_text(encoding='utf8'))
            for node in ast.walk(tree):
                modules = [item.name for item in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ''] if isinstance(node, ast.ImportFrom) else []
                self.assertFalse(any(module.split('.')[0] in ('tkinter', 'socket') for module in modules), str(path))

    def test_modular_selection_keeps_shared_instance_regressions(self):
        document = {'python_files': [
            {'path': 'tests/test_instance.py', 'imports': ['wlre.services.instance_room_flow']},
            {'path': 'tests/test_other.py', 'imports': ['wlre.services.social.guild']},
        ]}
        names = selected_tests(['cooperative'], document)
        self.assertIn('test_instance', names)
        self.assertNotIn('test_other', names)
        with self.assertRaises(ValueError): selected_tests(['unknown'], document)
