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
        card=self.app.overview_panel.cards['ai'];label=self.app.overview_panel.labels['ai'][0]
        x=label.winfo_rootx()-self.root.winfo_rootx();y=label.winfo_rooty()-self.root.winfo_rooty()
        image=data['widgets'][str(label)]['images'][0]
        actual=tuple(self.root.tk.call(str(image),'get',2,2))
        self.assertEqual(actual,data['surface'].convert('RGB').getpixel((x+2,y+2)))
        self.assertNotEqual(actual,data['background'].convert('RGB').getpixel((x+2,y+2)))

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
