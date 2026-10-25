"""Guard feature ownership, retained shared infrastructure and migration scope."""
import ast
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

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

    def test_expanded_package_aliases_share_modules_and_patch_points(self):
        path = ROOT / 'architecture/compatibility.json'
        if not path.exists():
            self.skipTest('No feature modules have been migrated yet')
        registry = json.loads(path.read_text(encoding='utf8'))
        self.assertEqual(registry['schema_version'], 1)
        self.assertTrue(registry['modules'])
        for old, target in registry['modules'].items():
            with self.subTest(old=old, target=target):
                legacy = importlib.import_module(old)
                canonical = importlib.import_module(target)
                self.assertIs(legacy, canonical)
                marker = object()
                with patch.object(legacy, '_compatibility_identity_probe', marker, create=True):
                    self.assertIs(canonical._compatibility_identity_probe, marker)

    def test_room_actions_belong_to_features_and_remain_on_legacy_page(self):
        from wlre.features.cooperative.ui.actions import CooperativeActions
        from wlre.features.cooperative.ui.panel import CooperativePage
        from wlre.features.dungeon.ui.actions import DungeonActions
        from wlre.features.dungeon.ui.panel import DungeonPage
        from wlre.ui.instance_ui import InstanceModePage
        for actions, page, methods in (
            (CooperativeActions, CooperativePage,
             ('request_standby', 'request_reward_claim', 'request_reward_cancel', 'request_auto_reward')),
            (DungeonActions, DungeonPage, ('request_start', 'request_enter')),
        ):
            self.assertTrue(issubclass(page, InstanceModePage))
            for method in methods:
                with self.subTest(page=page.__name__, method=method):
                    implementation = actions.__dict__[method]
                    self.assertIs(getattr(InstanceModePage, method), implementation)
                    self.assertIs(getattr(page, method), implementation)
                    self.assertEqual(implementation.__module__, actions.__module__)

    def test_feature_room_actions_reject_disconnected_state_without_dialog_or_send(self):
        from wlre.features.cooperative.ui.actions import CooperativeActions
        from wlre.features.dungeon.ui.actions import DungeonActions
        for actions, cooperative, ready, method in (
            (CooperativeActions, True, '_standby_ready', 'request_standby'),
            (CooperativeActions, True, '_claim_ready', 'request_reward_claim'),
            (CooperativeActions, True, '_cancel_ready', 'request_reward_cancel'),
            (CooperativeActions, True, '_auto_toggle_ready', 'request_auto_reward'),
            (DungeonActions, False, '_start_ready', 'request_start'),
            (DungeonActions, False, '_enter_ready', 'request_enter'),
        ):
            with self.subTest(method=method):
                app = SimpleNamespace(live_active=False, send=Mock())
                page = SimpleNamespace(cooperative=cooperative, app=app, **{ready: True})
                with patch('tkinter.messagebox.askyesno') as confirmation:
                    getattr(actions, method)(page)
                confirmation.assert_not_called()
                app.send.assert_not_called()

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
