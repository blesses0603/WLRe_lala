import copy
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
from wlre.services.items import maintenance
from wlre.services.battle.auto_battle import defaults, validate
from wlre.network.wire import ProtocolError


class MaintenanceTests(unittest.TestCase):
    def test_old_preferences_migrate_and_round_trip(self):
        old=defaults();old.pop('maintenance')
        value=validate(old)
        self.assertEqual(value['maintenance'],maintenance.defaults())
        value['maintenance'].update(repair_enabled=True,cleanup_enabled=True,repair_below=42,repair_items=[34104,0],cleanup_items=[34014]+[0]*14)
        self.assertEqual(validate(value),value)

    def test_invalid_preferences_are_rejected(self):
        for change in ({'repair_enabled':1},{'cleanup_enabled':'yes'},{'repair_below':250},
                       {'repair_below':True},{'repair_items':[31070,0]},{'cleanup_items':[1]},
                       {'cleanup_items':[True]+[0]*14}):
            with self.subTest(change=change),self.assertRaises(ProtocolError):maintenance.validate(change)

    def test_backpack_only_excludes_protected_stock(self):
        inv={'ready':True,'reliable':True,'reserved':{'3':1},'alchemy_slots':['4'],'expedition_slots':['5'],
             'items':{str(i):{'item_id':34104,'count':3} for i in range(1,9)}}
        inv['items']['2']['locked']=True
        inv['items']['6']['available_time']=1
        inv['items']['7']['limited_time']=1
        inv['items']['8']['item_id']=34014
        self.assertEqual(maintenance.backpack_stock(inv,True),{34104:3})
        self.assertEqual(maintenance.backpack_stock(inv),{34104:3,34014:3})
        inv['reliable']=False
        self.assertEqual(maintenance.backpack_stock(inv),{})
        inv['ready']=False;inv['reliable']=True
        self.assertEqual(maintenance.backpack_stock(inv),{})


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop')
class MaintenanceUiTests(unittest.TestCase):
    def setUp(self):
        from wlre.ui.gui import App
        from wlre.ui.auto_battle_ui import SettingsEditor
        self.folder=tempfile.TemporaryDirectory()
        self.environment=patch.dict(os.environ,{'LOCALAPPDATA':self.folder.name});self.environment.start()
        self.root=tk.Tk();self.app=App(self.root);self.editor=SettingsEditor(self.app)
        self.page=self.editor.maintenance_page
        self.editor.tabs.select(self.page);self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',job)
        self.root.destroy();self.environment.stop();self.folder.cleanup()

    def test_new_tab_saves_draft_and_preserves_missing_items(self):
        self.assertEqual(len(self.page.buttons),17)
        self.page.items['repair'][0]=34104;self.page.items['cleanup'][0]=34014
        self.page.repair_enabled.set(True);self.page.cleanup_enabled.set(True)
        self.page.threshold.set(35);self.page.refresh_slots(force=True)
        self.assertIn('缺貨',self.page.buttons['repair',0].cget('text'))
        self.assertEqual(self.editor.collect()['maintenance']['repair_below'],35)
        value=copy.deepcopy(self.editor.collect());self.editor.draft.value=value;self.editor.render()
        self.assertEqual(self.editor.collect(),value)
        for button in self.page.buttons.values():
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),self.page.winfo_rootx()+self.page.winfo_width())

    def test_all_filled_slots_and_runtime_status_fit_in_window(self):
        self.page.items={'repair':[34104,34104],'cleanup':[32001]*15}
        self.page.refresh_slots(force=True);self.root.update()
        bottom=self.page.winfo_rooty()+self.page.winfo_height()
        for widget in (*self.page.buttons.values(),*self.page.winfo_children()):
            with self.subTest(widget=str(widget),height=self.page.winfo_height()):
                self.assertTrue(widget.winfo_ismapped())
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),bottom)

    def test_picker_refreshes_backpack_and_rechecks_before_commit(self):
        from wlre.ui.maintenance_ui import BackpackPicker
        self.app.snapshot['inventory']={'ready':True,'reliable':True,'items':{'1':{'item_id':34104,'count':2}}}
        picker=BackpackPicker(self.page,'repair',0)
        self.root.update();self.assertEqual(picker.table.get_children(),('34104',))
        self.app.snapshot['inventory']['items'].clear()
        with patch('wlre.ui.maintenance_ui.messagebox.showinfo') as info:
            picker.commit(34104);info.assert_called_once()
        self.assertEqual(self.page.items['repair'][0],0)
        self.assertEqual(picker.table.get_children(),())
        picker.window.destroy()
