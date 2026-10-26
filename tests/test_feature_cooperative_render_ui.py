"""Third batch Tk regression: cooperative room list and reward widgets."""
import sys
import os
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from wlre.core.state import State
from wlre.ui.gui import App
from wlre.features.cooperative.panel import CooperativeModePage


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin',
                     'Requires desktop/Xvfb')
class CooperativeRenderUI(unittest.TestCase):
    def setUp(self):
        with patch.object(App, 'start_version_check'):
            self.root = tk.Tk()
            self.app = App(self.root)
            self.app.show_main()
        self.app.live_active = True
        self.root.update()
        self.page = self.app.instance_panel.coop_page

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()

    def data(self, open_reward=2):
        state = State().snapshot()
        state['instances']['coop'].update(
            ready=True, list_updated_at=time.monotonic(),
            rooms=[{'room_id': 91, 'sn': 9, 'members': 1,
                    'capacity': 2, 'public': True}],
            reward={'open_reward': open_reward, 'reward_mark': 0,
                    'win_stage': 1, 'reward_count': 2, 'npc_id': 20})
        return state

    def test_room_selection_persists_through_server_refresh(self):
        self.assertIsInstance(self.page, CooperativeModePage)
        state = self.data()
        self.app.instance_panel.render(state, live=True)
        self.assertEqual(len(self.page.entries.get_children()), 1)
        self.page.entries.selection_set('room_0')
        self.page.on_room_selected()
        self.app.instance_panel.render(state, live=True)
        self.assertEqual(self.page.entries.selection(), ('room_0',))
        self.assertEqual(self.page.selected_room()['room_id'], 91)
        self.assertFalse(self.app.instance_panel.main_page.cooperative)

    def test_paid_reward_never_enables_free_claim(self):
        state = self.data()
        self.app.instance_panel.render(state, live=True)
        self.assertIn('付費寶箱待處理', self.page.reward_note.get())
        self.assertTrue(self.page.claim_button.instate(['disabled']))
        state['instances']['coop']['reward_uncertain'] = True
        self.app.instance_panel.render(state, live=True)
        self.assertIn('結果不明', self.page.reward_note.get())
        self.assertTrue(self.page.claim_button.instate(['disabled']))
        self.assertTrue(self.page.cancel_reward_button.instate(['disabled']))


if __name__ == '__main__':
    unittest.main()
