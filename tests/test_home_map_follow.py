import os
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from wlre.ui.home_map import HomeMap


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop')
class AutomaticMap(unittest.TestCase):
    def setUp(self):
        # GUI lifecycle test: supply independently verified 1275 scene rows.
        # Real runtime must not silently use 1262 stage_coordinates when the
        # official 1275 source has not yet been installed.
        stage = lambda model, width: {
            'model_id': model, 'map_width': width, 'map_height': width,
            'small_offset_x': 12, 'small_offset_y': 12}
        runtime = SimpleNamespace(
            revision=1275,
            stages={12903: stage(12903, 9360),
                    12904: stage(12904, 10080)},
            scene_names={12903: '水之迴廊', 12904: '海底宮殿通道'},
            doors={}, portal_destinations={}, portal_positions={})
        self.runtime_patch = patch('wlre.services.world.runtime_1275.active_runtime',
                                   return_value=runtime)
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)
        self.root=tk.Tk();self.root.geometry('600x500')
        self.pick=Mock();self.move=Mock();self.portal=Mock()
        self.map=HomeMap(self.root,self.pick,Mock(),on_move=self.move,on_portal=self.portal,compact=True)
        self.map.pack(fill='both',expand=True);self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',job)
        self.root.destroy()

    def test_waits_for_current_scene_then_follows_changes_without_reloading_same_map(self):
        self.assertIsNone(self.map.selected_id)
        self.assertIn('等待',self.map.note.get())
        with patch.object(self.map,'show_map',wraps=self.map.show_map) as load:
            self.map.set_state({'player':{'scene':12903}})
            self.assertEqual(self.map.selected_id,12903);self.assertIsNotNone(self.map.image)
            self.map.set_state({'player':{'scene':12903}})
            self.assertEqual(load.call_count,1)
            self.map.set_state({'player':{'scene':12904}})
            self.assertEqual(self.map.selected_id,12904);self.assertIn('12904',self.map.map_title.get())
            self.assertEqual(load.call_count,2)
        self.pick.assert_not_called();self.move.assert_not_called();self.portal.assert_not_called()

    def test_map_controls_removed_and_audit_cannot_change_current_map(self):
        def children(widget):
            for child in widget.winfo_children():yield child;yield from children(child)
        self.map.set_state({'player':{'scene':12903}})
        self.map.show_audit();self.root.update()
        widgets=list(children(self.map))
        self.assertFalse(any(w.winfo_class() in ('TCombobox','TCheckbutton') for w in widgets))
        captions=[str(w.cget('text')) for w in widgets if 'text' in w.keys()]
        for text in ('載入','跟隨目前地圖','導航邊界','預覽選取地圖'):
            self.assertNotIn(text,captions)
        self.assertEqual(self.map.selected_id,12903)

    def test_missing_map_does_not_keep_previous_image(self):
        self.map.set_state({'player':{'scene':12903}})
        self.map.set_state({'player':{'scene':99999999}})
        self.assertEqual(self.map.selected_id,99999999)
        self.assertIsNone(self.map.image);self.assertIsNone(self.map.projection)
