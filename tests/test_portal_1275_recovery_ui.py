"""Tk regression for 1275 doors on the minimap; no real game commands."""
import os
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.ui.home_map import HomeMap
from wlre.services.world.portals import Portals


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt',
                     'Requires a desktop or Linux virtual display')
class Portal1275UI(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
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

    def test_1275_verified_door_is_selectable_not_directly_sendable(self):
        self.map.set_state({'player': {'scene': 12170}})
        self.assertEqual(len(self.map.portal_rows), 1)
        self.assertIn('傳點 #2（官方名稱未取得）', self.map.portal_list.get(0))
        self.assertEqual(str(self.map.portal_go.cget('state')), 'disabled')
        self.map.portal_list.selection_set(0)
        self.map.choose_portal()
        self.picked.assert_called_once_with(12170, 5701, 3230)
        self.assertIn('目的地待核對', str(self.map.portal_go.cget('text')))
        self.assertFalse(self.map.go_portal())
        self.sent.assert_not_called()

    def test_audit_shows_1275_not_historical_1262(self):
        self.map.set_state({'player': {'scene': 12170}})
        self.map.show_audit()
        self.assertEqual(self.map.audit_window.title(),
                         '1275 官方門事件（位置預覽）')


if __name__ == '__main__':
    unittest.main()
