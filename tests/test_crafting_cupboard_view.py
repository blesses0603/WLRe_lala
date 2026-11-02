"""Crafting consumes S62 cupboard snapshots for display, without inventing sends."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.wire import Packet, Writer, ProtocolError
from wlre.services.items.crafting import RECIPES, recipe_plan
from wlre.services.items.crafting_browser_model import material_rows, availability
from wlre.services.items.room_storage import confirmed_material_count
from wlre.ui.crafting_browser import CraftingBrowser


def recipe():
    return {'item_id':7,'tool_id':39001,'output':1,'materials':[{'item_id':8,'count':4}],
            'seconds':10,'design_id':0,'time_id':0,'limit_kind':0,'open_used':0}


class CupboardCraftingViewTests(unittest.TestCase):
    def setUp(self):
        self.state=State(phase='world_ready')
        self.state.player={'role_id':1}
        self.state.inventory.update(ready=True,reliable=True,
            items={'10':{'index':10,'item_id':8,'count':2}})
        self.state.furniture.update(ready=True,owner=1,
            items={'1':{'index':1,'item_id':39001,'status':0}})
        self.state.crafting['ready']=True
        self.enterContext(patch.dict(RECIPES,{'7':recipe()},clear=True))

    def snapshot(self):
        body=Writer().u8(1).u8(1).u16(2).u16(10).u16(8).u16(500).u16(11).u16(8).u16(7).build()
        self.state.apply(decode(Packet(62,57,body)))

    def row(self):
        return material_rows(self.state.snapshot(),recipe(),1)[0]

    def test_current_s62_snapshot_is_read_and_distinct_from_bag_slot_ten(self):
        self.snapshot()
        row=self.row()
        self.assertEqual(row['cupboard'],507)
        self.assertEqual(row['usable'],2)
        self.assertEqual(row['required'],4)
        self.assertEqual(self.state.inventory['items']['10']['count'],2)

    def test_deltas_before_initial_do_not_look_like_complete_inventory(self):
        self.state.apply(decode(Packet(62,57,Writer().u8(1).u8(2).u16(10).u16(8).u16(5).build())))
        self.assertIsNone(self.row()['cupboard'])

    def test_delete_and_add_update_displayed_cupboard_quantity(self):
        self.snapshot()
        self.state.apply(decode(Packet(62,57,Writer().u8(2).u16(10).u16(17).build())))
        self.assertEqual(self.row()['cupboard'],490)
        self.state.apply(decode(Packet(62,57,Writer().u8(1).u8(2).u16(11).u16(8).u16(3).build())))
        self.assertEqual(self.row()['cupboard'],493)

    def test_unreliable_counts_are_unknown_instead_of_usable(self):
        self.snapshot()
        self.state.room_storage['materials']['reliable']=False
        self.assertIsNone(self.row()['cupboard'])

    def test_empty_complete_and_unsynced_cupboard_are_different(self):
        self.assertIsNone(self.row()['cupboard'])
        self.state.apply(decode(Packet(62,57,Writer().u8(1).u8(1).u16(0).build())))
        self.assertEqual(self.row()['cupboard'],0)

    def test_materials_in_cupboard_do_not_claim_unimplemented_consumption(self):
        self.snapshot()
        status,reason=availability(self.state.snapshot(),recipe(),1)
        self.assertEqual(status,'待取料')
        self.assertIn('雜物櫃',reason)
        with self.assertRaises(ProtocolError):recipe_plan(self.state,7,1)
        self.assertIsNone(self.state.crafting['pending'])

    def test_matching_storage_revision_refreshes_existing_browser(self):
        window=SimpleNamespace(winfo_ismapped=lambda:True,after_idle=Mock(return_value='refresh'),after_cancel=Mock())
        page=SimpleNamespace(refresh_runtime_catalog=Mock(return_value=False),state_key=None,
            app=SimpleNamespace(live_active=True),embedded=True,window=window,
            refresh_job=None,refresh=Mock())
        CraftingBrowser.update_state(page,self.state.snapshot())
        window.after_idle.reset_mock()
        self.snapshot()
        CraftingBrowser.update_state(page,self.state.snapshot())
        window.after_idle.assert_called_once_with(page.refresh)

    def test_invalid_quantity_is_not_advertised_as_available(self):
        storage={'materials':{'ready':True,'reliable':True,'items':{'10':{'item_id':8,'count':-1}}}}
        self.assertIsNone(confirmed_material_count(storage,8))


import os


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop or Xvfb')
class StorageGridWindowTests(unittest.TestCase):
    def test_nested_storage_keeps_twenty_four_cells_visible_through_resize(self):
        import tkinter as tk
        from wlre.ui.bag_grid import BagGrid
        root=tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('1040x450')
        icons=SimpleNamespace(get=lambda item,size:tk.PhotoImage(master=root,width=size,height=size))
        grid=BagGrid(root,icons,lambda action:None,read_only=True,compact=True)
        grid.pack(fill='both',expand=True)
        grid.render({'ready':True,'reliable':True,'capacity':200,
                     'items':{str(i):{'index':i,'item_id':3874,'count':i} for i in range(1,148)}})
        root.update()
        for geometry in ('1040x450','440x450'):
            root.geometry(geometry);root.update()
            self.assertEqual((grid.columns,grid.row_count,grid.page_size),(6,4,24))
            self.assertEqual(grid.page_label.get(),'1 / 7')
            self.assertEqual(sum(cell['frame'].winfo_ismapped() for cell in grid.cells),24)
            self.assertEqual({int(cell['frame'].grid_info()['row']) for cell in grid.cells},{0,1,2,3})
            for cell in grid.cells:
                frame=cell['frame']
                self.assertLessEqual(frame.winfo_x()+frame.winfo_width(),grid.board.winfo_width())
                self.assertLessEqual(frame.winfo_y()+frame.winfo_height(),grid.board.winfo_height())
        grid.change_page(1);root.update()
        self.assertEqual(grid.cells[0]['index'],'25')
        self.assertEqual(grid.cells[23]['index'],'48')


if __name__=='__main__':unittest.main()
