import os
import tkinter as tk
import unittest
from unittest.mock import Mock,patch
from wlre.ui.gui import App
from wlre.core.state import State


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop or Xvfb')
class CompactCrafting(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.app=App(self.root);self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.app.show_main();self.app.left_tabs.select(self.app.crafting_panel);self.root.update()
        self.panel=self.app.crafting_panel;self.browser=self.panel.browser

    def tearDown(self):
        for job in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',job)
        self.root.destroy()

    def test_embedded_catalog_keeps_map_chat_and_six_icons_visible(self):
        self.assertTrue(self.browser.embedded)
        self.assertNotIsInstance(self.browser.window,tk.Toplevel)
        self.assertTrue(self.app.home_map.winfo_ismapped())
        self.assertTrue(self.app.chat_panel.winfo_ismapped())
        self.assertEqual(len(self.browser.cards),6)
        ids=[card['id'] for card in self.browser.cards]
        self.browser.change_page(1);self.root.update()
        self.assertNotEqual(ids,[card['id'] for card in self.browser.cards])
        for card in self.browser.cards:
            self.assertTrue(card['button'].winfo_ismapped())
            self.assertGreaterEqual(card['button'].winfo_height(),56)
            self.assertEqual(card['image'].width(),32)
        self.assertFalse(self.errors,self.errors)

    def test_selection_is_shared_by_detail_and_custom_plan(self):
        self.browser.pick_card(1)
        self.assertEqual(self.panel.recipe_id,self.browser.cards[1]['id'])
        self.browser.count.set('2')
        self.browser.pages.select(self.browser.detail_page);self.root.update()
        self.assertTrue(self.browser.add_button.winfo_ismapped())
        self.assertEqual(self.panel.count.get(),'2')
        plan=self.panel.open_plan();plan.add_current()
        self.assertEqual(plan.rows,[{'item_id':self.panel.recipe_id,'count':2}])
        with patch('wlre.ui.crafting_browser.availability',return_value=('可製作','')),patch('wlre.ui.crafting_browser.recipe_plan'):
            self.app.live_active=False;self.browser.refresh_detail(force=True)
            self.assertTrue(self.browser.add_button.instate(['disabled']))
            self.app.live_active=True;self.browser.refresh_detail()
            self.assertFalse(self.browser.add_button.instate(['disabled']))
        self.assertFalse(self.errors,self.errors)

    def test_queue_uses_server_snapshot_and_keeps_revision_in_commands(self):
        state=State().snapshot();item_id=self.panel.recipe_id
        state['crafting'].update(revision=7,queue={'1':{'index':1,'item_id':item_id,'count':2,'base_time':60,'elapsed':0}})
        self.panel.render(state);self.root.update()
        self.browser.show_queue();self.root.update()
        self.assertEqual(self.browser.queue.item('1','values')[2],'2')
        self.browser.queue.selection_set('1');self.app.send=Mock()
        self.browser.queue_command('up')
        self.app.send.assert_called_once_with({'type':'craft','action':'up','index':1,'revision':7})
        self.assertFalse(self.errors,self.errors)
