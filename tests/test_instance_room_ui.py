"""Room join/leave UI: selection, confirmation, password and cross-mode locks."""
from _tk_native_pump import create_root
import sys
import os
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from wlre.ui.gui import App
from wlre.core.state import State


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin',
                     'Requires desktop/Xvfb')
class RoomUI(unittest.TestCase):
    def setUp(self):
        self.root = create_root()
        self.app = App(self.root)
        self.app.show_main()
        self.app.live_active = True
        self.root.update()
        self.page = self.app.instance_panel.main_page

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()

    def _data(self, *, public=True):
        data = State().snapshot()
        data['instances']['main'].update(
            ready=True, list_updated_at=time.monotonic(),
            rooms=[{'room_id': 30012, 'sn': 55, 'members': 2,
                    'public': public}])
        return data

    @staticmethod
    def widgets(root):
        yield root
        for child in root.winfo_children():
            yield from RoomUI.widgets(child)

    def _dialog(self, title):
        return next(w for w in self.root.winfo_children()
                    if isinstance(w, tk.Toplevel) and w.title() == title)

    def test_join_selected_only_and_confirm_send(self):
        state = self._data()
        self.app.instance_panel.render(state, live=True)
        self.assertTrue(self.page.join_button.instate(['disabled']))
        self.page.entries.selection_set('room_0')
        self.page.on_room_selected()
        self.assertTrue(self.page.join_button.instate(['!disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=False):
                self.page.open_join_dialog()
                dialog = self._dialog('加入副本房間')
                confirm = next(w for w in self.widgets(dialog)
                               if isinstance(w, ttk.Button)
                               and w.cget('text') == '確認加入')
                confirm.invoke()
                send.assert_not_called()
                dialog.destroy()
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=True):
                self.page.open_join_dialog()
                dialog = self._dialog('加入副本房間')
                confirm = next(w for w in self.widgets(dialog)
                               if isinstance(w, ttk.Button)
                               and w.cget('text') == '確認加入')
                confirm.invoke()
                send.assert_called_once_with({
                    'type':'instance_join', 'mode':'main',
                    'room_id':30012, 'sn':55, 'password':''
                })
        self.assertTrue(self.page.join_button.instate(['disabled']))

    def test_private_room_requires_password(self):
        state = self._data(public=False)
        self.app.instance_panel.render(state, live=True)
        self.page.entries.selection_set('room_0')
        self.page.on_room_selected()
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.showwarning') as warn:
                self.page.open_join_dialog()
                dialog = self._dialog('加入副本房間')
                confirm = next(w for w in self.widgets(dialog)
                               if isinstance(w, ttk.Button)
                               and w.cget('text') == '確認加入')
                confirm.invoke()
                warn.assert_called_once()
                send.assert_not_called()
                dialog.destroy()
        state['instances']['main']['list_updated_at'] = time.monotonic() - 130
        self.app.instance_panel.render(state, live=True)
        self.assertTrue(self.page.join_button.instate(['disabled']))

    def test_leave_requires_confirmed_room_and_manual_confirmation(self):
        state = self._data()
        self.app.instance_panel.render(state, live=True)
        self.assertTrue(self.page.leave_button.instate(['disabled']))
        state['instances']['main']['room'] = {'room_id':30012, 'host_id':1111}
        state['instances']['main']['phase'] = 'waiting'
        self.app.instance_panel.render(state, live=True)
        self.assertTrue(self.page.leave_button.instate(['!disabled']))
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=False):
                self.page.leave_button.invoke()
                send.assert_not_called()
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=True):
                self.page.leave_button.invoke()
                send.assert_called_once_with({
                    'type':'instance_leave','mode':'main'})
        self.assertTrue(self.page.leave_button.instate(['disabled']))

    def test_cross_mode_pending_and_uncertainty_lock(self):
        state = self._data()
        page = self.app.instance_panel.main_page
        state['instances']['coop']['join_pending'] = {'room_id':91}
        self.app.instance_panel.render(state, live=True)
        page.entries.selection_set('room_0')
        page.on_room_selected()
        self.assertTrue(page.join_button.instate(['disabled']))
        self.assertTrue(page.create_button.instate(['disabled']))
        state['instances']['coop']['join_pending'] = None
        state['instances']['coop']['leave_uncertain'] = True
        self.app.instance_panel.render(state, live=True)
        self.assertTrue(page.join_button.instate(['disabled']))
        self.assertTrue(page.create_button.instate(['disabled']))
        self.app.instance_panel.render(State().snapshot(), live=False)
        self.assertTrue(page.join_button.instate(['disabled']))
