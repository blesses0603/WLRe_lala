import os
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from wlre.core.state import State
from wlre.ui.gui import App


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop')
class RedesignedLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tk.Tk();cls.app=App(cls.root);cls.errors=[]
        cls.root.report_callback_exception=lambda *args:cls.errors.append(args)
        cls.app.show_main();cls.root.update()

    @classmethod
    def tearDownClass(cls):
        for job in cls.root.tk.call('after','info'):cls.root.tk.call('after','cancel',job)
        cls.root.destroy()

    def descendants(self,parent):
        for child in parent.winfo_children():
            if isinstance(child,tk.Toplevel) or not child.winfo_ismapped():continue
            yield child;yield from self.descendants(child)

    def test_all_main_controls_fit_visible_content(self):
        for page in self.app.left_tabs.tabs():
            self.app.left_tabs.select(page);self.root.update()
            widget=self.root.nametowidget(page)
            for child in self.descendants(widget):
                if child.winfo_class() not in ('TButton','TEntry','TCombobox','TSpinbox'):continue
                with self.subTest(page=self.app.left_tabs.tab(page,'text'),control=str(child)):
                    self.assertGreaterEqual(child.winfo_rootx(),widget.winfo_rootx())
                    self.assertLessEqual(child.winfo_rootx()+child.winfo_width(),widget.winfo_rootx()+widget.winfo_width()+1)
                    self.assertLessEqual(child.winfo_rooty()+child.winfo_height(),widget.winfo_rooty()+widget.winfo_height()+1)
        self.assertFalse(self.errors,self.errors)
        self.app.left_tabs.select(self.app.overview_panel.master);self.root.update()

    def test_card_labels_inherit_same_readable_surface(self):
        self.app.left_tabs.select(self.app.overview_panel.master);self.root.update()
        theme=self.app.theme;data=theme.windows[str(self.root)];data['signature']=None;theme.paint(self.root)
        self.assertIn('ai', self.app.overview_panel.cards)
        label=self.app.overview_panel.labels['ai'][0]
        x=label.winfo_rootx()-self.root.winfo_rootx();y=label.winfo_rooty()-self.root.winfo_rooty()
        image=data['widgets'][str(label)]['images'][0]
        actual=tuple(self.root.tk.call(str(image),'get',2,2))
        self.assertEqual(actual,data['surface'].convert('RGB').getpixel((x+2,y+2)))
        self.assertNotEqual(actual,data['background'].convert('RGB').getpixel((x+2,y+2)))

    def test_combined_recovery_shows_both_columns_and_preserves_independent_settings(self):
        from wlre.ui.auto_battle_ui import SettingsEditor
        editor=SettingsEditor(self.app)
        try:
            editor.tabs.select(editor.recovery_tab);self.root.update()
            names=[editor.tabs.tab(t,'text') for t in editor.tabs.tabs()]
            self.assertIn('補給設定',names);self.assertNotIn('HP補給',names);self.assertNotIn('SP補給',names)
            hp=editor.recovery_pages['hp'];sp=editor.recovery_pages['sp']
            self.assertLessEqual(hp.winfo_rootx()+hp.winfo_width(),sp.winfo_rootx())
            self.assertTrue(hp.winfo_ismapped());self.assertTrue(sp.winfo_ismapped())
            from wlre.services.items.combat_resources import CAT,heal_effects
            for page in (hp,sp):
                sid=next(int(sid) for sid in CAT['items'] if heal_effects(int(sid)).get(page.resource))
                page.items=[sid]*10;page.render_slots()
            self.root.update()
            for page in (hp,sp):
                self.assertEqual(len(page.buttons),10)
                for control in [*page.buttons,*page.scales.values()]:self.assertTrue(control.winfo_ismapped())
                for widget in self.descendants(page):
                    if widget.winfo_class() not in ('TButton','TCombobox','TScale'):continue
                    self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),page.winfo_rootx()+page.winfo_width()+1)
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),page.winfo_rooty()+page.winfo_height()+1)
            editor.rootvars['field_heal'].set(True)
            hp.percents['player'].set(33);sp.percents['player'].set(66)
            value=editor.collect()
            self.assertTrue(value['field_heal'])
            self.assertEqual(value['recovery']['hp']['player_percent'],33)
            self.assertEqual(value['recovery']['sp']['player_percent'],66)
            editor.draft.value=value;editor.render()
            self.assertEqual(editor.collect()['recovery'],value['recovery'])
        finally:editor.window.destroy()

    def test_compact_battle_truncates_long_name_but_inspection_keeps_full_data(self):
        self.app.activity_tabs.select(self.app.formation);self.root.update()
        battle=self.app.formation;name='非常長的測試敵方角色名稱不應蓋到鄰格'
        state=State().snapshot();state['player']={'role_id':1}
        state['battle_units']={'3:1':{'col':3,'row':1,'pid':2,'master_id':0,'name':name,'hp':123456,'max_hp':987654}}
        battle.set_state(state);self.root.update()
        x1,y1,x2,y2,_,_=next(rect for rect in battle.rects if rect[4:]==(3,1))
        self.assertLessEqual(battle.bold_font.measure(battle.fit_text(name,x2-x1-30,bold=True)),x2-x1-30)
        event=SimpleNamespace(x=(x1+x2)/2,y=(y1+y2)/2)
        battle.inspect_unit(event)
        self.assertIn(name,battle.note.get());self.assertIn('123456/987654',battle.note.get())
        original=battle.on_select;battle.on_select=Mock()
        try:
            battle.pick(event);battle.on_select.assert_called_once_with('3:1',False)
        finally:battle.on_select=original
        self.app.activity_tabs.select(self.app.logs_frame);self.root.update()
