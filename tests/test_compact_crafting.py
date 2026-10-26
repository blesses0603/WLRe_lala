from _tk_native_pump import create_root
import sys
import os
import tkinter as tk
import unittest
from unittest.mock import Mock,patch
from wlre.ui.gui import App
from wlre.core.state import State


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt' or sys.platform == 'darwin','Requires a desktop or Xvfb')
class CompactCrafting(unittest.TestCase):
    def setUp(self):
        self.root=create_root();self.app=App(self.root);self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.app.show_main();self.app.open_feature('crafting');self.root.update()
        self.panel=self.app.crafting_panel;self.browser=self.panel.browser

    def tearDown(self):
        for job in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',job)
        self.root.destroy()

    def test_embedded_catalog_keeps_map_chat_and_twelve_icons_visible(self):
        self.assertTrue(self.browser.embedded)
        self.assertNotIsInstance(self.browser.window,tk.Toplevel)
        self.assertTrue(self.app.home_map.winfo_ismapped())
        self.assertTrue(self.app.chat_panel.winfo_ismapped())
        self.assertEqual(len(self.browser.cards),12)
        self.assertEqual(self.browser.page_size,12)
        self.assertEqual(len({card['frame'].grid_info()['column'] for card in self.browser.cards}),4)
        self.assertEqual(len({card['frame'].grid_info()['row'] for card in self.browser.cards}),3)
        for card in self.browser.cards:
            self.assertTrue(card['button'].winfo_ismapped())
            self.assertGreaterEqual(card['button'].winfo_height(),50)
            self.assertEqual(card['image'].width(),32)
        self.assertFalse(self.errors,self.errors)

    def test_twelve_item_pagination_keeps_order_and_search_resets_page(self):
        with patch('wlre.ui.crafting_browser.confirmed_unlocked',return_value=True):
            self.browser.refresh_grid(force=True)
            expected=[r['item_id'] for r in self.browser.rows]
            self.assertGreater(len(expected),12)
            self.assertEqual([card['id'] for card in self.browser.cards],expected[:12])
            self.browser.change_page(1)
            self.assertEqual([card['id'] for card in self.browser.cards if card['id'] is not None],expected[12:24])
            self.browser.search.set(str(expected[0]));self.browser.search_now()
            self.assertEqual(self.browser.page,0)
            self.assertEqual(self.browser.cards[0]['id'],expected[0])

    def test_selection_is_shared_by_detail_and_custom_plan(self):
        self.browser.change_page(1)
        previous_page=self.browser.page
        self.browser.pick_card(1)
        self.root.update()
        self.assertTrue(self.browser.detail_panel.winfo_ismapped())
        self.assertTrue(self.browser.grid.winfo_ismapped())
        self.assertEqual(self.browser.page,previous_page)
        self.assertEqual(self.panel.recipe_id,self.browser.cards[1]['id'])
        self.browser.count.set('2')
        self.root.update()
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

    def test_recipe_details_and_all_items_stay_visible_with_live_batch_quantities(self):
        self.assertFalse(hasattr(self.browser,'pages'))
        self.assertTrue(self.browser.detail_panel.winfo_ismapped())
        self.browser.count.set('1');self.browser.refresh_detail(force=True)
        table=self.browser.material_table
        original=[int(table.item(i,'values')[2]) for i in table.get_children()]
        self.assertTrue(original)
        self.browser.count.set('2');self.browser.refresh_detail(force=True);self.root.update()
        self.assertEqual([int(table.item(i,'values')[2]) for i in table.get_children()],[n*2 for n in original])
        self.assertTrue(self.browser.add_button.winfo_ismapped())
        edge=self.browser.detail_panel.winfo_rootx()
        for card in self.browser.cards:
            self.assertTrue(card['button'].winfo_ismapped())
            self.assertLessEqual(card['button'].winfo_rootx()+card['button'].winfo_width(),edge)

    def test_full_height_details_have_no_drag_divider_or_scrollbars_and_show_five_materials(self):
        from wlre.services.items.crafting import RECIPES
        detail=self.browser.detail_panel;toolbar=self.browser.toolbar
        self.assertEqual(detail.winfo_rooty(),toolbar.winfo_rooty())
        self.assertGreater(detail.winfo_height(),self.browser.grid.winfo_height())
        self.assertFalse(hasattr(self.browser,'detail_split'))
        def children(parent):
            for child in parent.winfo_children():yield child;yield from children(child)
        self.assertFalse(any(w.winfo_class() in ('TPanedwindow','TScrollbar') for w in children(detail)))
        for control in toolbar.winfo_children():
            self.assertLessEqual(control.winfo_rootx()+control.winfo_width(),detail.winfo_rootx())
        recipe=next(r for r in RECIPES.values() if len(r['materials'])==5)
        self.browser.selected=recipe['item_id'];self.browser.refresh_detail(force=True);self.root.update()
        table=self.browser.material_table
        self.assertEqual(len(table.get_children()),5)
        self.assertEqual(table.column('name','width'),76)
        self.assertFalse(table.column('name','stretch'))
        for iid in table.get_children():
            bounds=table.bbox(iid)
            self.assertTrue(bounds)
            self.assertLessEqual(bounds[1]+bounds[3],table.winfo_height())
        self.assertTrue(self.browser.add_button.winfo_ismapped())
        self.assertTrue(self.app.home_map.winfo_ismapped())
        self.assertTrue(self.app.chat_panel.winfo_ismapped())

    def test_material_icons_align_left_and_headers_cannot_be_dragged(self):
        table=self.browser.material_table;self.root.update()
        first=table.get_children()[0];bounds=table.bbox(first)
        # Treeview header height follows the platform font metrics: Linux
        # may place the first row at 28 px instead of 26 px on Windows.
        # Verify the item begins directly below its real header, not at a
        # hardcoded pixel offset that breaks with DPI and native Tk fonts.
        body_top=next((y for y in range(table.winfo_height())
                       if table.identify_region(3,y) in ('tree','cell')),None)
        self.assertIsNotNone(body_top)
        self.assertLessEqual(bounds[1],body_top+2)
        self.assertIn('image',table.identify_element(3,bounds[1]+bounds[3]//2))
        columns=('#0','name','usable','required')
        before=[table.column(c,'width') for c in columns]
        separator=next(x for x in range(1,table.winfo_width()) if table.identify_region(x,8)=='separator')
        table.event_generate('<ButtonPress-1>',x=separator,y=8)
        table.event_generate('<B1-Motion>',x=separator+30,y=8,state=256)
        table.event_generate('<ButtonRelease-1>',x=separator+30,y=8)
        self.root.update()
        self.assertEqual([table.column(c,'width') for c in columns],before)
        table.event_generate('<ButtonPress-1>',x=50,y=bounds[1]+bounds[3]//2)
        table.event_generate('<ButtonRelease-1>',x=50,y=bounds[1]+bounds[3]//2)
        self.assertEqual(table.selection(),(first,))

    def test_favorite_has_separate_click_target_and_does_not_change_recipe(self):
        import tempfile
        from pathlib import Path
        from wlre.services.items.crafting_browser_model import Favorites
        previous=self.browser.favorite_store
        with tempfile.TemporaryDirectory() as directory:
            try:
                self.browser.favorite_store=Favorites(Path(directory)/'favorites.json')
                self.browser.refresh_grid(force=True);self.root.update()
                card=self.browser.cards[0];sid=card['id'];selected=self.browser.selected
                image=card['favorite'].cget('image')
                self.assertGreaterEqual(card['favorite'].winfo_rooty(),card['button'].winfo_rooty()+card['button'].winfo_height())
                card['favorite'].invoke();self.root.update()
                self.assertIn(sid,self.browser.favorite_store.ids)
                self.assertNotEqual(card['favorite'].cget('image'),image)
                self.assertEqual(self.browser.selected,selected)
                card['favorite'].invoke();self.assertNotIn(sid,self.browser.favorite_store.ids)
            finally:self.browser.favorite_store=previous

    def test_queue_uses_server_snapshot_and_keeps_revision_in_commands(self):
        state=State().snapshot();item_id=self.panel.recipe_id
        state['crafting'].update(revision=7,queue={'1':{'index':1,'item_id':item_id,'count':2,'base_time':60,'elapsed':0}})
        self.panel.render(state);self.root.update()
        self.browser.show_queue();self.root.update()
        self.assertEqual(self.browser.queue.item('1','values')[2],'2')
        state['crafting'].update(active=1,running=True,started_at=None)
        self.panel.render(state);self.root.update();self.browser.update_queue()
        self.assertIn('製作中',self.browser.queue_activity.get())
        self.assertTrue(self.browser.queue_progress.winfo_ismapped())
        self.browser.queue.selection_set('1');self.app.send=Mock()
        self.browser.queue_command('up')
        self.app.send.assert_called_once_with({'type':'craft','action':'up','index':1,'revision':7})
        self.assertFalse(self.errors,self.errors)
