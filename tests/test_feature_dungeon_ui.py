"""P1b real Tk regression for the normal dungeon feature split."""
import os
import tkinter as tk
import unittest
from unittest.mock import patch

from wlre.core.state import State
from wlre.features.dungeon.panel import DungeonModePage
from wlre.features.cooperative.panel import CooperativeModePage
from wlre.ui.gui import App


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt',
                     'Requires desktop/Xvfb')
class DungeonFeatureUI(unittest.TestCase):
    def setUp(self):
        with patch.object(App, 'start_version_check'):
            self.root = tk.Tk()
            self.app = App(self.root)
            self.app.show_main()
        self.app.live_active = True
        self.root.update()
        self.page = self.app.instance_panel.main_page

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()

    def snapshot(self, *, phase='waiting', host=678, count=None):
        data = State().snapshot()
        record = next(r for r in self.page.catalog_records
                      if r['kind'] == 1 and r['min_members'] > 0)
        needed = record['min_members'] if count is None else count
        roster = [{'role_id': 678}] + [
            {'role_id': 889 + i} for i in range(max(0, needed - 1))]
        data['player']['role_id'] = 678
        data['player']['scene'] = 10000
        data['instances']['main'].update(
            room={'room_id': record['map_id'], 'host_id': host,
                  'members': len(roster)},
            members=roster, phase=phase, ready=True)
        return data

    def test_normal_page_and_start_still_require_click_confirmation(self):
        self.assertIsInstance(self.page, DungeonModePage)
        self.assertIsInstance(self.app.instance_panel.coop_page,
                              CooperativeModePage)
        state = self.snapshot()
        self.app.instance_panel.render(state, live=True)
        self.assertTrue(self.page.start_button.instate(['!disabled']))
        self.assertTrue(self.page.enter_button.instate(['disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno',
                       return_value=False):
                self.page.start_button.invoke()
                send.assert_not_called()
            with patch('wlre.ui.instance_ui.messagebox.askyesno',
                       return_value=True):
                self.page.start_button.invoke()
            send.assert_called_once_with({
                'type': 'instance_start', 'mode': 'main'})
        self.assertTrue(self.page.start_button.instate(['disabled']))

    def test_normal_entry_requires_server_started_and_live_snapshot(self):
        state = self.snapshot(phase='started')
        self.app.instance_panel.render(state, live=True)
        self.assertTrue(self.page.start_button.instate(['disabled']))
        self.assertTrue(self.page.enter_button.instate(['!disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno',
                       return_value=True):
                self.page.enter_button.invoke()
            send.assert_called_once_with({
                'type': 'instance_enter', 'mode': 'main'})
        self.assertTrue(self.page.enter_button.instate(['disabled']))
        self.app.instance_panel.render(state, live=False)
        self.assertTrue(self.page.enter_button.instate(['disabled']))

    def test_unverified_host_and_cross_mode_pending_lock_start(self):
        state = self.snapshot(host=889)
        self.app.instance_panel.render(state, live=True)
        self.assertTrue(self.page.start_button.instate(['disabled']))
        state = self.snapshot()
        state['instances']['coop']['join_pending'] = {'room_id': 91}
        self.app.instance_panel.render(state, live=True)
        self.assertTrue(self.page.start_button.instate(['disabled']))
        self.assertTrue(self.page.enter_button.instate(['disabled']))


if __name__ == '__main__':
    unittest.main()
