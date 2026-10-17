import os
import tkinter as tk
import unittest
from unittest.mock import patch
from wlre.core.state import State
from wlre.ui.gui import App
from wlre.ui.auto_battle_ui import SettingsEditor


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop')
class OverviewControls(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.app=App(self.root);self.app.show_main();self.root.update()
        self.panel=self.app.overview_panel;self.app.live_active=True
        self.state=State().snapshot();self.state['player']={'role_id':1,'name':'測試角色','scene':12000}
        self.app.render(self.state);self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',job)
        self.root.destroy()

    def test_both_actions_start_stop_and_follow_confirmed_state(self):
        for key,section,start,stop in (('ai','auto_battle','start_auto_battle','stop_auto_battle'),('roaming','roaming','start_roaming','stop_roaming')):
            button=self.panel.actions[key]
            with patch.object(self.app,'send') as send:
                button.invoke();self.assertEqual(send.call_args.args[0]['type'],start)
                self.assertFalse(button.active)
                self.state[section]['enabled']=True
                self.app.render(self.state);self.root.update()
                self.assertEqual(button.button.cget('text'),'關閉')
                self.assertTrue(button.find_withtag('halo'));self.assertIsNotNone(button.job)
                button.invoke();self.assertEqual(send.call_args.args[0]['type'],stop)
                self.state[section]['enabled']=False
                self.app.render(self.state);self.root.update()
                self.assertEqual(button.button.cget('text'),'啟動')
                self.assertFalse(button.find_withtag('halo'));self.assertIsNone(button.job)

    def test_hidden_animation_pauses_and_disconnect_clears_halo(self):
        self.state['auto_battle']['enabled']=True;self.app.render(self.state);self.root.update()
        button=self.panel.actions['ai']
        self.app.left_tabs.select(self.app.crafting_panel);self.root.update()
        self.assertIsNone(button.job)
        self.app.left_tabs.select(self.panel.master);self.root.update()
        self.assertIsNotNone(button.job)
        self.app.live_active=False;self.panel.refresh()
        self.assertFalse(button.active);self.assertIsNone(button.job)

    def test_settings_entry_title_map_header_and_button_bounds(self):
        with patch('wlre.ui.auto_battle_ui.open_settings') as settings:
            self.panel.ai_settings_button.invoke();settings.assert_called_once_with(self.app)
        editor=SettingsEditor(self.app)
        try:self.assertEqual(editor.window.title(),'自動戰鬥設定')
        finally:editor.window.destroy()
        descendants=list(self.app.theme.descendants(self.root))
        captions=[str(w.cget('text')) for w in descendants if 'text' in w.keys()]
        self.assertNotIn('進階導航',captions)
        self.assertNotIn('Lua 規則自動戰鬥',captions)
        self.assertIn('自動戰鬥',captions)
        for key in ('ai','roaming'):
            button=self.panel.actions[key];frame=self.panel.cards[key]
            self.assertLessEqual(button.winfo_x()+button.winfo_width(),frame.winfo_width())
            self.assertLessEqual(button.winfo_y()+button.winfo_height(),frame.winfo_height())
