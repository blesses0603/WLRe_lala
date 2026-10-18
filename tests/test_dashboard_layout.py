"""Run with a display (or xvfb-run) to catch clipped dashboard content."""
import os
import tkinter as tk
import unittest
from unittest.mock import patch
from tkinter import font as tkfont, ttk
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

    def setUp(self):
        # Layout assertions describe the foreground UI. Windows CI may not
        # grant focus; background buffering has its own dedicated tests.
        foreground = patch.object(self.app, 'background_window', return_value=False)
        foreground.start()
        self.addCleanup(foreground.stop)
        # Every test starts on the expected pages, even if a prior assertion
        # failed before its final tab-restoration statements.
        self.app.left_tabs.select(self.app.overview_panel.master)
        self.app.activity_tabs.select(self.app.logs_frame)
        self.root.update()

    def test_party_tables_have_no_visible_scrollbars(self):
        self.app.left_tabs.select(self.app.party_panel)
        self.root.update()
        for tree in (self.app.party_panel.members, self.app.party_panel.requests):
            with self.subTest(table=str(tree)):
                self.assertEqual(tree.winfo_class(), 'Treeview')
                self.assertFalse(
                    any(isinstance(child, ttk.Scrollbar)
                        for child in tree.master.winfo_children())
                )

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

    def test_all_main_pages_have_a_visible_shared_outer_border(self):
        theme=self.app.theme
        for page in (self.app.overview_panel.master,self.app.party_panel,
                     self.app.alchemy_panel,self.app.crafting_panel,self.app.efficiency_panel):
            with self.subTest(page=str(page)):
                self.app.left_tabs.select(page);self.root.update()
                data=theme.windows[str(self.root)];data['signature']=None;theme.paint(self.root)
                image=data['widgets'][str(page)]['images'][0]
                x=page.winfo_rootx()-self.root.winfo_rootx()
                y=page.winfo_rooty()-self.root.winfo_rooty()
                background=data['surface'].convert('RGB')
                middle=image.height()//2
                self.assertNotEqual(tuple(self.root.tk.call(str(image),'get',1,middle)),background.getpixel((x+1,y+middle)))
                self.assertEqual(tuple(self.root.tk.call(str(image),'get',4,middle)),background.getpixel((x+4,y+middle)))
        self.app.left_tabs.select(self.app.overview_panel.master);self.root.update()

    def test_right_tabs_map_size_and_party_settings(self):
        self.assertEqual([self.app.left_tabs.tab(t,'text') for t in self.app.left_tabs.tabs()],
                         ['主頁','組隊','夥伴出戰','遠征','煉金','製作','經驗效率'])
        self.assertEqual([self.app.activity_tabs.tab(t,'text') for t in self.app.activity_tabs.tabs()],['事件紀錄','戰場陣形'])
        self.assertEqual((self.app.home_map.winfo_width(),self.app.home_map.winfo_height()),(380,320))
        self.assertTrue(self.app.home_map.portal_list.winfo_ismapped())
        self.app.write('fixture-before-switch')
        self.app.activity_tabs.select(self.app.formation);self.root.update()
        self.app.write('fixture-while-battle-visible')
        self.assertTrue(self.app.formation.winfo_ismapped());self.assertTrue(self.app.chat_panel.winfo_ismapped())
        self.assertTrue(self.app.home_map.winfo_ismapped())
        self.app.left_tabs.select(self.app.party_panel);self.root.update()
        self.assertTrue(self.app.party_guard_panel.winfo_ismapped())
        self.assertLessEqual(self.app.party_guard_panel.winfo_rooty()+self.app.party_guard_panel.winfo_height(),self.app.party_panel.winfo_rooty()+self.app.party_panel.winfo_height())
        self.assertEqual(tkfont.nametofont('TkDefaultFont',root=self.root).cget('size'),-14)
        self.app.activity_tabs.select(self.app.logs_frame)
        self.assertIn('fixture-before-switch',self.app.log.get('1.0','end'))
        self.assertIn('fixture-while-battle-visible',self.app.log.get('1.0','end'))

    def test_hidden_expedition_checks_online_tasks_without_opening_tab(self):
        panel = self.app.expedition_panel
        quest = next(q for q in panel.catalog['tasks'].values() if q['difficulty'] == 1 and q['minutes'] > 300)
        state = State().snapshot()
        state['player'] = {'role_id': 1, 'name': '測試角色', 'scene': 60000}
        state['expedition'].update(ready=True, outpost_ready=True, level=1, quests={'1': quest['id']})
        with patch.object(self.app, 'live_active', True), patch.object(self.app, 'send') as send:
            self.app.render(state)
            self.root.update()
            self.assertFalse(panel.winfo_ismapped())
            self.assertEqual(len(panel.tasks.get_children()), 1)
            self.assertIn('已自動檢查', panel.status.get())
            send.assert_not_called()
        self.app.left_tabs.select(self.app.overview_panel.master);self.root.update()

    def test_all_navigation_actions_still_work(self):
        panel=self.app.overview_panel
        for key,destination,title in (('party','party_panel','隊伍檢查'),
                                      ('alchemy','alchemy_panel','煉金'),
                                      ('crafting','crafting_panel','製作'),
                                      ('efficiency','efficiency_panel','經驗效率')):
            button=panel.actions[key]
            with self.subTest(key=key):
                self.assertEqual(button.cget('text'),title)
                self.assertTrue(button.cget('image'))
                self.assertEqual(button.cget('compound'),'none')
                self.assertIsNotNone(button._action_icon)
                button.invoke();self.root.update()
                expected=getattr(self.app,destination)
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
