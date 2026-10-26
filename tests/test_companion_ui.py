import sys
import os
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from wlre.ui.companion_ui import CompanionPanel


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin', 'Requires a desktop')
class CompanionSelection(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.app = SimpleNamespace(live_active=True, send=Mock())
        self.panel = CompanionPanel(self.root, self.app)
        self.panel.pack(fill='both', expand=True)
        self.state = {'phase': 'world_ready', 'knowledge': {'companions_ready': True, 'active_npc_id': 101,
            'companions': {'1': {'ready': True, 'index': 1, 'npc_id': 101,
                'stats': {'name': '測試夥伴甲', 'level': 10, 'hp': 90, 'max_hp': 100}},
                '2': {'ready': True, 'index': 2, 'npc_id': 102, 'stats': {'name': '測試夥伴乙', 'sp': 0}}}}}

    def tearDown(self):
        self.root.destroy()

    def test_selection_does_not_change_server_deployment(self):
        self.panel.render(self.state)
        self.panel.companions.selection_set('2')
        self.panel.select()
        self.assertIn('測試夥伴乙', self.panel.detail.get())
        self.assertEqual(self.state['knowledge']['active_npc_id'], 101)
        self.assertEqual(self.panel.companions.set('1', 'status'), '出戰中')
        self.assertEqual(self.panel.companions.set('2', 'status'), '未出戰')
        self.assertEqual(self.panel.companions.set('1', 'hp'), '90/100')
        self.assertEqual(self.panel.companions.set('2', 'sp'), '0')
        self.assertFalse(self.panel.deploy.instate(['disabled']))
        self.panel.deploy.invoke()
        self.app.send.assert_called_once_with({'type': 'companion', 'action': 'deploy', 'index': 2, 'npc_id': 102})
        self.assertEqual(self.state['knowledge']['active_npc_id'], 101)
        self.panel.companions.selection_set('1')
        self.panel.select()
        self.assertTrue(self.panel.deploy.instate(['disabled']))
        self.panel.rest.invoke()
        self.assertEqual(self.app.send.call_args.args[0], {'type': 'companion', 'action': 'rest', 'index': 1, 'npc_id': 101})

    def test_refresh_preserves_selection_and_clears_removed_companion(self):
        self.panel.render(self.state)
        self.panel.companions.selection_set('2')
        self.state['knowledge']['active_npc_id'] = 102
        self.panel.render(self.state)
        self.assertEqual(self.panel.companions.selection(), ('2',))
        self.assertEqual(self.panel.companions.set('2', 'status'), '出戰中')
        del self.state['knowledge']['companions']['2']
        self.panel.render(self.state)
        self.assertEqual(self.panel.companions.selection(), ())
        self.assertEqual(self.panel.detail.get(), '請從清單選擇夥伴。')

    def test_empty_unsynchronized_and_offline_states(self):
        self.panel.render({})
        self.assertIn('等待', self.panel.status.get())
        self.state['knowledge']['companions'] = {}
        self.app.live_active = False
        self.panel.render(self.state)
        self.assertIn('已離線', self.panel.status.get())
        self.assertIn('0 位', self.panel.status.get())
        self.assertFalse(self.panel.companions.get_children())
