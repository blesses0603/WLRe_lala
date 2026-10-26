"""Tk regression for 1275 doors on the minimap; no real game commands."""
from _tk_native_pump import create_root
import sys
import os
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.ui.home_map import HomeMap
from wlre.services.world.portals import Portals


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin',
                     'Requires a desktop or Linux virtual display')
class Portal1275UI(unittest.TestCase):
    def setUp(self):
        self.root = create_root()
        self.root.geometry('640x500')
        self.picked = Mock()
        self.sent = Mock()
        runtime = SimpleNamespace(doors={12170: [
            {'index': 2, 'x': 5701, 'y': 3230, 'event_ids': [2]}]})
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1275'), patch(
                'wlre.services.world.runtime_1275.active_runtime',
                return_value=runtime):
            catalog = Portals()
        with patch('wlre.ui.home_map.Portals', return_value=catalog):
            self.map = HomeMap(
                self.root, self.picked, Mock(), on_portal=self.sent,
                compact=True)
        self.map.pack(fill='both', expand=True)
        self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()

    def test_unmarked_door_is_hidden_from_list_and_cannot_send(self):
        self.map.set_state({'player': {'scene': 12170}})
        self.assertEqual(len(self.map.portal_rows), 0)
        self.assertIn('StageMapData 傳點名稱表', self.map.portal_info.get())
        self.assertNotIn('傳點 #2', self.map.portal_list.get(0))
        self.assertEqual(len(self.map.portals.for_scene(12170)), 1)
        self.assertEqual(str(self.map.portal_go.cget('state')), 'disabled')
        self.map.portal_list.selection_set(0)
        self.map.choose_portal()
        self.picked.assert_not_called()
        self.assertFalse(self.map.go_portal())
        self.sent.assert_not_called()

    def test_audit_shows_1275_not_historical_1262(self):
        self.map.set_state({'player': {'scene': 12170}})
        self.map.show_audit()
        self.assertEqual(self.map.audit_window.title(),
                         '1275 官方門事件（位置預覽）')
        from tkinter import ttk
        def trees(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Treeview): yield child
                yield from trees(child)
        table = next(trees(self.map.audit_window))
        self.assertEqual(len(table.get_children()), 1)

    def test_list_hides_unmarked_door_while_audit_keeps_both(self):
        runtime = SimpleNamespace(
            doors={12170: [{'index': 1, 'x': 42, 'y': 64},
                           {'index': 2, 'x': 43, 'y': 65}]},
            portal_names={(12170, 1): '前往北島-北'},
            portal_positions={(12170, 1): {
                'scene': 12170, 'index': 1, 'x': 200, 'y': 300,
                'position_verified': True, 'source_kind': '1275_eve_door_links_grid_scaled'}},
            portal_metadata_status='destination_links_loaded')
        with patch('wlre.services.world.runtime_1275.baseline_revision', return_value='1275'), \
             patch('wlre.services.world.runtime_1275.active_runtime', return_value=runtime):
            self.map.portals = Portals()
        self.map.selected_id = 12170
        self.map.image = object()
        self.map.projection = SimpleNamespace(packet_to_pixel=lambda x, y: (x, y))
        with patch.object(self.map, 'draw'):
            self.map.refresh_portals()
        self.assertEqual(len(self.map.portal_rows), 1)
        self.assertIn('前往北島-北', self.map.portal_list.get(0))
        self.map.show_audit()
        from tkinter import ttk
        def trees(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Treeview): yield child
                yield from trees(child)
        table = next(trees(self.map.audit_window))
        self.assertEqual(len(table.get_children()), 2)

    def test_global_review_includes_scenes_without_any_doors(self):
        from wlre.services.world.portal_coverage import audit_portal_coverage
        self.map.portals.data['portal_coverage'] = audit_portal_coverage(
            {12170: [{'index': 2}]}, {12170, 12171, 12172})
        window = self.map.show_all_portal_coverage()
        self.root.update_idletasks()
        from tkinter import ttk
        def trees(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Treeview): yield child
                yield from trees(child)
        table = next(trees(window))
        self.assertEqual(set(table.get_children()), {'12170', '12171', '12172'})
        self.assertEqual(table.item('12171', 'values')[2], '0')
        self.sent.assert_not_called()
        window.destroy()


if __name__ == '__main__':
    unittest.main()
