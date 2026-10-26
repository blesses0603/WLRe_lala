"""P1a second batch: cooperative creation, joining, and leaving in Tk."""
from _tk_native_pump import create_root
import sys
import os
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from wlre.core.state import State
from wlre.ui.gui import App
from wlre.features.cooperative.panel import CooperativeModePage


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin',
                     'Requires a desktop/Xvfb')
class CooperativeRoomDialogsUI(unittest.TestCase):
    def setUp(self):
        with patch.object(App, 'start_version_check'):
            self.root = create_root()
            self.app = App(self.root)
            self.app.show_main()
        self.app.live_active = True
        self.root.update()
        self.page = self.app.instance_panel.coop_page

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()

    @staticmethod
    def widgets(root):
        yield root
        for child in root.winfo_children():
            yield from CooperativeRoomDialogsUI.widgets(child)

    def dialog_button(self, title, button_text):
        dialog = next(w for w in self.root.winfo_children()
                      if isinstance(w, tk.Toplevel) and w.title() == title)
        button = next(w for w in self.widgets(dialog)
                      if isinstance(w, ttk.Button)
                      and w.cget('text') == button_text)
        return dialog, button

    def test_coop_screen_and_create_payload(self):
        self.assertIsInstance(self.page, CooperativeModePage)
        self.assertTrue(self.page.cooperative)
        self.assertFalse(self.app.instance_panel.main_page.cooperative)
        self.app.instance_panel.render(State().snapshot(), live=True)
        self.page.catalog_table.selection_set('catalog_0')
        self.page.on_catalog_selected()
        record = self.page.catalog_records[0]
        self.assertTrue(self.page.create_button.instate(['!disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno',
                       return_value=True):
                self.page.open_create_dialog()
                dialog, confirm = self.dialog_button(
                    '建立副本房間', '確認建立')
                self.assertTrue(any(
                    isinstance(w, ttk.Spinbox)
                    for w in self.widgets(dialog)))
                confirm.invoke()
            send.assert_called_once_with({
                'type': 'instance_create', 'mode': 'coop',
                'public': True, 'password': '',
                'dungeon_id': record['id'],
                'player_count': record['min_members'],
                'confirm_cost': True,
            })
        self.assertTrue(self.page.create_button.instate(['disabled']))

    def test_coop_join_requires_confirmation_and_cost_flag(self):
        data = State().snapshot()
        data['instances']['coop'].update(
            ready=True, list_updated_at=time.monotonic(),
            rooms=[{'room_id': 91, 'members': 1,
                    'capacity': 2, 'public': True}])
        self.app.instance_panel.render(data, live=True)
        self.page.entries.selection_set('room_0')
        self.page.on_room_selected()
        self.assertTrue(self.page.join_button.instate(['!disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno',
                       return_value=False):
                self.page.open_join_dialog()
                dialog, confirm = self.dialog_button(
                    '加入副本房間', '確認加入')
                confirm.invoke()
                send.assert_not_called()
                dialog.destroy()
            with patch('wlre.ui.instance_ui.messagebox.askyesno',
                       return_value=True):
                self.page.open_join_dialog()
                _, confirm = self.dialog_button('加入副本房間', '確認加入')
                confirm.invoke()
            send.assert_called_once_with({
                'type': 'instance_join', 'mode': 'coop',
                'room_id': 91, 'password': '', 'confirm_cost': True,
            })
        self.assertTrue(self.page.join_button.instate(['disabled']))

    def test_coop_leave_waits_for_manual_confirmation(self):
        data = State().snapshot()
        data['instances']['coop'].update(
            room={'room_id': 91, 'host_id': 678, 'standby': False},
            phase='waiting')
        self.app.instance_panel.render(data, live=True)
        self.assertTrue(self.page.leave_button.instate(['!disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno',
                       return_value=False):
                self.page.leave_button.invoke()
                send.assert_not_called()
            with patch('wlre.ui.instance_ui.messagebox.askyesno',
                       return_value=True):
                self.page.leave_button.invoke()
            send.assert_called_once_with({
                'type': 'instance_leave', 'mode': 'coop',
            })
        self.assertTrue(self.page.leave_button.instate(['disabled']))


if __name__ == '__main__':
    unittest.main()
