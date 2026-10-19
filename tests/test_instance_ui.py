"""Regression tests for the instance and co-op navigation skeleton."""
import os
import tkinter as tk
import unittest
from unittest.mock import patch

from wlre.ui.gui import App


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'Requires a desktop or Xvfb')
class InstanceNavigation(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.app = App(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.app.show_main()
        self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()

    def test_main_entry_and_two_subtabs_are_navigable(self):
        panel = self.app.instance_panel
        self.assertTrue(panel._section_outline)
        self.assertEqual(self.app.left_tabs.tab(panel, 'text'), '副本')
        self.app.left_tabs.buttons[str(panel)].invoke()
        self.root.update()
        self.assertEqual(self.app.left_tabs.select(), str(panel))
        self.assertEqual(
            [panel.tabs.tab(page, 'text') for page in panel.tabs.tabs()],
            ['主要', '協力'],
        )
        for page, title in ((panel.main_page, '主要'), (panel.coop_page, '協力')):
            with self.subTest(mode=title):
                panel.tabs.buttons[str(page)].invoke()
                self.root.update()
                self.assertEqual(panel.tabs.select(), str(page))
                self.assertTrue(page.winfo_ismapped())
                self.assertEqual(page.entries.get_children(), ())
                self.assertEqual(
                    [page.entries.heading(column, 'text') for column in page.columns],
                    ['副本名稱', '進入條件', '狀態'],
                )
                self.assertTrue(page.enter_button.instate(['disabled']))
        self.assertFalse(self.errors, self.errors)

    def test_unverified_entry_never_sends_game_commands(self):
        panel = self.app.instance_panel
        self.app.left_tabs.select(panel)
        with patch.object(self.app, 'send') as send:
            for page in (panel.main_page, panel.coop_page):
                panel.tabs.select(page)
                self.root.update()
                page.enter_button.invoke()
            send.assert_not_called()
        self.assertFalse(self.errors, self.errors)
