"""Official read-only/conditional recipes remain browseable in crafting UI."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from wlre.ui.crafting.catalog_grid import render_catalog_grid
from wlre.services.items.crafting_browser_model import availability


class Var:
    def __init__(self,value=''):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


def recipe(item,**fields):
    return {'item_id':item,'tool_id':39001,'output':1,'materials':[{'item_id':8,'count':2}],
            'seconds':10,'design_id':0,'time_id':0,'limit_kind':0,'open_used':0,
            **fields}


class CatalogVisibilityTests(unittest.TestCase):
    def page(self):
        return SimpleNamespace(search=Var(),favorite_store=SimpleNamespace(ids=[]),
            filter_key='all',only_tools=Var(False),state={},page=0,page_size=12,
            page_label=Var(),selected=None,grid_key=None,detail_key=None,
            cards=[{'frame':Mock(),'button':Mock(),'favorite':Mock(),'status':Mock(),'id':None}
                   for _ in range(12)],icons=Mock(),embedded=True,
            favorite_images={False:'off',True:'on'},refresh_detail=Mock())

    def render(self,page,recipes,**kwargs):
        deps={'confirmed_unlocked':lambda row:False,'room_known':lambda state:False,
              'tool_status':lambda state,item:'待同步','item_name':lambda item:'物品'+str(item),
              'availability':availability}
        deps.update(kwargs)
        return render_catalog_grid(page,recipes=recipes,**deps)

    def test_readonly_and_conditional_recipes_are_visible_even_if_none_are_confirmed_unlocked(self):
        page=self.page()
        rows={'7':recipe(7,read_only=True),'9':recipe(9,design_id=1),
              '10':recipe(10,open_used=1),'11':recipe(11,time_id=1)}
        self.render(page,rows)
        self.assertEqual({row['item_id'] for row in page.rows},{7,9,10,11})
        self.assertEqual({card['id'] for card in page.cards if card['id'] is not None},{7,9,10,11})
        self.assertIn('配方 4 項',page.page_label.get())
        self.assertNotIn('已解鎖',page.page_label.get())
        self.assertEqual(page.cards[0]['status'].configure.call_args.kwargs['text'],'參考配方')

    def test_readonly_status_does_not_falsely_claim_craftable(self):
        status,reason=availability({},recipe(7,read_only=True))
        self.assertEqual(status,'參考配方')
        self.assertIn('查看材料',reason)
        self.assertNotEqual(status,'可製作')

    def test_equipment_filter_requires_explicit_selection_and_explains_empty_result(self):
        page=self.page()
        rows={'7':recipe(7,read_only=True)}
        self.render(page,rows,room_known=lambda state:True,tool_status=lambda state,item:'未擺放')
        self.assertEqual(len(page.rows),1)
        page.only_tools.set(True)
        self.render(page,rows,room_known=lambda state:True,tool_status=lambda state,item:'未擺放')
        self.assertEqual(page.rows,[])
        self.assertIn('取消設備篩選',page.empty_catalog_message)

    def test_unsynced_house_never_hides_the_catalog(self):
        page=self.page()
        page.only_tools.set(True)
        self.render(page,{'7':recipe(7,read_only=True)})
        self.assertEqual(len(page.rows),1)

    def test_search_and_favorite_filter_include_readonly_recipes(self):
        page=self.page()
        rows={'7':recipe(7,read_only=True),'9':recipe(9,read_only=True)}
        page.search.set('物品7')
        self.render(page,rows)
        self.assertEqual([r['item_id'] for r in page.rows],[7])
        page.search.set('')
        page.filter_key='favorites'
        page.favorite_store.ids=[9]
        self.render(page,rows)
        self.assertEqual([r['item_id'] for r in page.rows],[9])

    def test_empty_result_reason_updates_when_only_filter_changes(self):
        page=self.page()
        rows={'7':recipe(7,read_only=True)}
        page.search.set('不存在')
        self.render(page,rows)
        self.assertIn('搜尋',page.empty_catalog_message)
        page.search.set('')
        page.filter_key='favorites'
        page.refresh_detail.reset_mock()
        self.render(page,rows)
        self.assertIn('收藏',page.empty_catalog_message)
        page.refresh_detail.assert_called_once_with()

    def test_missing_source_is_not_mislabeled_as_zero_unlocked(self):
        page=self.page()
        self.render(page,{})
        self.assertIn('尚未載入',page.empty_catalog_message)
        self.assertNotIn('已解鎖',page.page_label.get())


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop or Xvfb')
class CraftingVisibilityWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from tkinter import ttk
        from wlre.ui.crafting_browser import CraftingBrowser
        from wlre.services.items.crafting import RECIPES
        self.root=tk.Tk()
        self.root.geometry('1120x700')
        self.addCleanup(self.root.destroy)
        self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.panel=ttk.Frame(self.root)
        self.panel.pack(fill='both',expand=True)
        self.panel.state={}
        self.panel.app=SimpleNamespace(root=self.root,live_active=False,send=Mock())
        self.panel.open_plan=Mock()
        self.panel.add=Mock()
        self.panel.command=Mock()
        rows={'7':recipe(7,read_only=True),'9':recipe(9,read_only=True,tool_id=39002)}
        self.patches=[
            patch.dict(RECIPES,rows,clear=True),
            patch('wlre.ui.crafting_browser.ItemIcons',return_value=SimpleNamespace(get=lambda *args:'',close=Mock())),
            patch('wlre.ui.crafting_browser.Favorites',return_value=SimpleNamespace(ids=[],load_error=None)),
            patch('wlre.ui.crafting_browser.item_name',side_effect=lambda item:'物品'+str(item)),
            patch('wlre.ui.crafting_browser.feature_note',return_value='目前官方 Runtime 資料已驗證'),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.browser=CraftingBrowser(self.panel,embedded=True)
        self.addCleanup(self.browser.close)
        self.root.update_idletasks()

    def test_window_shows_cards_workbenches_and_materials_before_house_sync(self):
        self.assertFalse(self.browser.only_tools.get())
        self.assertEqual(len(self.browser.rows),2)
        self.assertTrue(self.browser.cards[0]['frame'].winfo_ismapped())
        self.assertTrue(self.browser.tool_tree.exists('39001'))
        self.assertTrue(self.browser.tool_tree.exists('39002'))
        self.assertIn('全部配方',self.browser.tool_tree.item('all','text'))
        self.assertEqual(self.browser.name.get(),'物品7')
        self.assertTrue(self.browser.material_table.get_children())
        self.assertFalse(self.errors,self.errors)
