"""Run with a display (or xvfb-run) to catch clipped dashboard content."""
import os
import tkinter as tk
import unittest
from tkinter import font as tkfont
from wlre.core.state import State
from wlre.ui.gui import App


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop or Xvfb')
class DashboardLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tk.Tk();cls.app=App(cls.root);cls.errors=[]
        cls.root.report_callback_exception=lambda *args:cls.errors.append(args)
        cls.app.show_main();cls.root.update()

    @classmethod
    def tearDownClass(cls):
        for job in cls.root.tk.call('after','info'):cls.root.tk.call('after','cancel',job)
        cls.root.destroy()

    def test_summary_rows_have_room_for_real_text(self):
        state=State().snapshot()
        state['player']={'role_id':1,'name':'測試角色','scene':60000}
        state['knowledge']['player']['stats']={'level':14,'hp':168,'max_hp':215,'sp':108,'max_sp':108}
        state['inventory']['field_supply']={'pending':True,'reason':'等待補給確認'}
        self.app.status.set('事件尚未完成，等待伺服器回覆。'*50)
        self.app.live_active=True
        self.app.render(state);self.root.update()
        panel=self.app.overview_panel
        self.assertEqual((self.root.winfo_width(),self.root.winfo_height()),(1280,800))
        self.assertIn('HP 168/215',panel.values['role'].get())
        self.assertIn('等待補給確認',panel.values['activity'].get())
        font=tkfont.nametofont('TkDefaultFont',root=self.root)
        for key,(label,limit) in panel.labels.items():
            with self.subTest(key=key):
                self.assertTrue(label.winfo_ismapped())
                self.assertGreaterEqual(label.winfo_height(),font.metrics('linespace'))
                self.assertLessEqual(panel.cards[key].winfo_y()+panel.cards[key].winfo_height(),panel.winfo_height())
                for line in panel.values[key].get().splitlines():
                    self.assertLessEqual(font.measure(line),label.winfo_width())
        self.assertFalse(self.errors,self.errors)

    def test_work_surfaces_keep_artwork_and_map_is_secondary(self):
        self.root.update()
        layout=self.app.layout
        self.assertIn(layout.body,list(self.app.theme.descendants(self.root)))
        self.assertGreater(layout.left.winfo_width(),layout.right.winfo_width())
        for widget in (layout.left,layout.right,self.app.home_map,self.app.logs_frame,self.app.chat_panel):
            self.assertGreater(widget.winfo_height(),100)
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.root.winfo_rootx()+1280)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),self.root.winfo_rooty()+800)

    def test_all_navigation_actions_still_work(self):
        panel=self.app.overview_panel
        for key,destination in (('ai','ai_page'),('roaming','roam_page'),('party','party_panel'),('alchemy','alchemy_panel'),('crafting','crafting_panel'),('efficiency','efficiency_panel')):
            panel.actions[key].invoke();self.root.update()
            expected=self.app.battle_page if destination in ('ai_page','roam_page') else getattr(self.app,destination)
            self.assertEqual(self.app.left_tabs.select(),str(expected))
        self.app.left_tabs.select(panel.master);self.root.update()
        self.assertFalse(self.errors,self.errors)

    def test_utility_windows_fit_supported_desktop(self):
        from wlre.ui.auto_battle_ui import SettingsEditor, ActionEditor
        from wlre.ui.resource_view import ResourceView
        from wlre.ui.recovery_ui import SupplyPicker
        def check(window):
            self.root.update()
            self.assertGreaterEqual(window.winfo_x(),0)
            self.assertGreaterEqual(window.winfo_y(),0)
            self.assertLessEqual(window.winfo_x()+window.winfo_width(),self.root.winfo_screenwidth())
            self.assertLessEqual(window.winfo_y()+window.winfo_height(),self.root.winfo_screenheight())
            self.assertLessEqual(window.winfo_width(),1240)
            self.assertLessEqual(window.winfo_height(),760)
            def inspect(parent):
                for child in parent.winfo_children():
                    if isinstance(child,tk.Toplevel) or not child.winfo_ismapped():continue
                    if child.winfo_class() in ('TButton','TEntry','TCombobox','TSpinbox'):
                        self.assertLessEqual(child.winfo_rootx()+child.winfo_width(),window.winfo_rootx()+window.winfo_width()+2)
                        self.assertLessEqual(child.winfo_rooty()+child.winfo_height(),window.winfo_rooty()+window.winfo_height()+2)
                    inspect(child)
            inspect(window)
        resources=ResourceView(self.app)
        try:check(resources.window)
        finally:resources.window.destroy()
        settings=SettingsEditor(self.app)
        try:
            for page in settings.tabs.tabs():
                with self.subTest(page=settings.tabs.tab(page,'text')):
                    settings.tabs.select(page);check(settings.window)
            picker=SupplyPicker(settings.recovery_pages['hp'],0)
            try:check(picker.window)
            finally:picker.window.destroy()
        finally:settings.window.destroy()
        browser=self.app.crafting_panel.open_browser()
        try:
            check(browser.window);browser.show_queue();check(browser.queue_window)
        finally:browser.close()
        plan=self.app.crafting_panel.open_plan()
        try:check(plan.window)
        finally:plan.window.destroy()
        self.app.open_navigation();navigation=self.app.navigation_windows[-1]
        try:check(navigation.window)
        finally:navigation.window.destroy()
        self.app.home_map.show_audit()
        try:check(self.app.home_map.audit_window)
        finally:self.app.home_map.audit_window.destroy()
        self.app.chat_panel.show_emoji_picker()
        try:check(self.app.chat_panel.emoji_picker)
        finally:self.app.chat_panel.emoji_picker.destroy()
        action=ActionEditor(self.root,{'kind':1,'id':0,'target':1},self.app.snapshot,'player',lambda row:None)
        try:check(action.window)
        finally:action.window.destroy()
        self.assertFalse(self.errors,self.errors)
