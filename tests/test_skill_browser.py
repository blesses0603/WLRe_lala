"""Skill display stays bound to confirmed actors and never sends on selection."""
import os
import tkinter as tk
import unittest
from unittest.mock import patch, Mock
from wlre.ui.skill_browser_model import actor_key, skill_key, matches, detail_text, level_text

ACTORS = [dict(pid=1,name='角色',level=20),dict(pid=2,npc_index=1,name='夥伴',level=12)]
ROWS = [dict(id=101,name='物理技能',level=1,category='物理',sp=6,source='S5-3',reasons=[]),
        dict(id=102,name='輔助技能',level=5,category='輔助',sp=10,source='S5-3',reasons=['SP不足'])]
CATALOG = {'skills':{'101':dict(LvLimit=1,description='官方說明',WeaponKind1=1,WeaponKind2=0,WeaponKind3=0,WeaponKind4=0,WeaponKind5=0),
                      '102':dict(LvLimit=10,description='第二項說明')}}


class ModelTests(unittest.TestCase):
    def test_actor_slots_are_distinct(self):
        self.assertNotEqual(actor_key(dict(pid=2,npc_index=1)),actor_key(dict(pid=2,npc_index=2)))
        self.assertNotEqual(skill_key(ACTORS[0],101),skill_key(ACTORS[1],101))
    def test_filter_requires_both_category_and_query(self):
        self.assertTrue(matches(ROWS[0],ACTORS[0],'101','物理'))
        self.assertFalse(matches(ROWS[0],ACTORS[0],'101','魔法'))
        self.assertFalse(matches(ROWS[0],ACTORS[0],'missing','全部'))
    def test_max_level_not_assumed(self):
        self.assertIn('MAX',level_text(ROWS[0],CATALOG['skills']['101']))
        self.assertNotIn('MAX',level_text(ROWS[0],{}))
    def test_unknown_description_and_weapon_explicit(self):
        text=detail_text(ROWS[0],{},False,False)
        self.assertIn('尚未同步技能說明',text);self.assertIn('未連線',text)
        self.assertIn('待同步',text)
    def test_conditions_are_not_replaced_by_pretty_ui(self):
        self.assertIn('SP不足',detail_text(ROWS[1],{},True,True))
        self.assertIn('目前不在戰鬥',detail_text(ROWS[0],{},True,False))


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop')
class BrowserTests(unittest.TestCase):
    def setUp(self):
        from wlre.ui.skill_browser import SkillBrowser
        self.root=tk.Tk();self.root.geometry('1024x560');self.errors=[];self.sent=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.rows=patch('wlre.ui.skill_browser.skill_rows',side_effect=lambda state,actor:ROWS if actor['pid']==1 else [])
        self.cat=patch('wlre.ui.skill_browser.CAT',CATALOG)
        self.rows.start();self.cat.start()
        self.browser=SkillBrowser(self.root,lambda:self.sent.append(True));self.browser.pack(fill='both',expand=True)
        self.state={'player':{'role_id':1},'battle':{'active':True},'knowledge':{}}
        self.browser.render(self.state,ACTORS,'',True);self.root.update()
    def tearDown(self):
        self.root.destroy();self.rows.stop();self.cat.stop()
    def test_initial_details_and_no_automatic_cast(self):
        self.assertIn('官方說明',self.browser.details.get('1.0','end'))
        self.assertEqual(self.sent,[]);self.assertFalse(self.errors)
    def test_filter_updates_selection_and_stale_cast_is_disabled(self):
        self.browser.category.set('魔法');self.browser.render_skills();self.root.update()
        self.assertFalse(self.browser.list.selection());self.assertFalse(self.browser.skill_map)
        self.assertEqual(str(self.browser.cast['state']),'disabled')
        self.assertEqual(self.sent,[])
    def test_actor_switch_clears_other_actors_skills(self):
        self.browser.actor_list.selection_set(actor_key(ACTORS[1]));self.browser.pick_actor();self.root.update()
        self.assertFalse(self.browser.skill_map);self.assertEqual(self.sent,[])
    def test_selection_survives_refresh_but_not_actor_removal(self):
        key=skill_key(ACTORS[0],102)
        self.browser.list.selection_set(key);self.browser.pick_skill()
        self.browser.render(self.state,ACTORS,'',True);self.root.update()
        self.assertEqual(self.browser.selected_skill,key)
        self.browser.render(self.state,ACTORS[1:],'',True);self.root.update()
        self.assertIsNone(self.browser.selected_skill)
    def test_unavailable_and_disconnected_skill_cannot_cast(self):
        self.browser.list.selection_set(skill_key(ACTORS[0],102));self.browser.pick_skill()
        self.assertEqual(str(self.browser.cast['state']),'disabled')
        self.browser.render(self.state,ACTORS,'101',False);self.root.update()
        self.assertEqual(str(self.browser.cast['state']),'disabled')
    def test_duplicate_npc_portraits_use_exact_slot_and_distinct_labels(self):
        self.browser.provider.close()
        provider=Mock();provider.request.return_value={}
        self.browser.provider=provider
        actors=[dict(pid=2,npc_index=1,name='同名夥伴',level=5),dict(pid=2,npc_index=2,name='同名夥伴',level=5)]
        state=dict(self.state,knowledge={'companions':{'1':{'npc_id':2,'index':1},'2':{'npc_id':2,'index':2}}})
        self.browser.render(state,actors,'',True)
        calls=provider.request.call_args_list
        self.assertEqual(list(calls[0].args[0]['knowledge']['companions']),['1'])
        self.assertEqual(list(calls[1].args[0]['knowledge']['companions']),['2'])
        self.assertIn('#1',self.browser.actor_list.item(actor_key(actors[0]),'text'))
        self.assertIn('#2',self.browser.actor_list.item(actor_key(actors[1]),'text'))
    def test_repeated_filter_destroy_has_no_callback(self):
        for category in ('輔助','全部','物理'):
            self.browser.category.set(category);self.browser.render_skills();self.root.update()
        self.browser.destroy();self.root.update()
        self.assertFalse(self.errors)
    def test_720p_layout_keeps_buttons_inside(self):
        self.root.geometry('1000x530');self.root.update()
        for widget in (self.browser.cast,self.browser.list,self.browser.actor_list):
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width()+2)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height()+2)
