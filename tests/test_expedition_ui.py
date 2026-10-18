import os
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.ui.expedition_ui import ExpeditionPanel


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'Requires a desktop')
class ExpeditionPanelTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.app = SimpleNamespace(root=self.root, live_active=True, _settings_key=None,
            snapshot={}, send=Mock(return_value=True), settings_identity=lambda: 'a'*64)
        self.catalog = {'levels': {'1': {'reduction': 0}}, 'tasks': {
            '1': {'id': 1, 'minutes': 360, 'faith_cost': 20},
            '2': {'id': 2, 'minutes': 240, 'faith_cost': 10}}}
        with patch('wlre.ui.expedition_ui.load_catalog', return_value=self.catalog):
            self.panel = ExpeditionPanel(self.root, self.app)
        self.panel.pack(fill='both', expand=True)
        self.state = {'expedition': {'ready': True, 'outpost_ready': True,
            'level': 1, 'quests': {'1': 1, '2': 2}, 'revision': 1, 'roles': {}, 'teams': {}, 'status': '待機'}}
        self.app.snapshot = self.state

    def tearDown(self):
        self.root.destroy()

    def test_threshold_controls_filter_tasks_and_enqueue_configuration(self):
        self.panel.render(self.state)
        self.assertEqual(len(self.panel.tasks.get_children()), 1)
        self.panel.hours.set('3')
        self.assertEqual(len(self.panel.tasks.get_children()), 2)
        self.panel.faith.set('85')
        self.panel.start_button.invoke()
        self.assertEqual(self.app.send.call_args.args[0], {'type': 'start_expedition',
            'settings': {'min_hours': 3.0, 'faith_min': 85, 'item_id': 0, 'quests': [], 'auto_claim': True}})
        self.app.send.return_value = False
        self.panel.start()
        self.assertIn('重新登入', self.panel.status.get())

    def test_missing_catalog_disables_start_and_displays_requirement(self):
        self.panel.catalog = {'tasks': {}, 'levels': {}}
        self.panel.render(self.state)
        self.assertTrue(self.panel.start_button.instate(['disabled']))
        self.assertIn('缺少官方', self.panel.note.get())

    def test_account_preferences_reload_without_automatic_start(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'LOCALAPPDATA': folder}):
            self.panel.hours.set('7.5')
            self.panel.faith.set('90')
            self.panel.auto_claim.set(False)
            self.panel.save()
            self.panel.hours.set('1')
            self.panel.load_settings('a'*64)
            self.assertEqual(self.panel.hours.get(), '7.5')
            self.assertEqual(self.panel.faith.get(), '90')
            self.assertFalse(self.panel.auto_claim.get())
            self.app.send.assert_not_called()
            self.panel.load_settings('b'*64)
            self.assertEqual(self.panel.faith.get(), '80')
