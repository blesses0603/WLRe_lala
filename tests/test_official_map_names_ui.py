"""Navigation labels refresh without selecting a different numeric map/model."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires Tk display')
class OfficialMapNamesUITests(unittest.TestCase):
    def test_open_window_updates_names_and_clears_failed_choices(self):
        import tkinter as tk
        from wlre.ui.navigation_gui import NavigationWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        first=SimpleNamespace(revision=1296,stages={10000:{'name_id':1,'model_id':10000}},texts={1:'first'})
        second=SimpleNamespace(revision=1296,stages=first.stages,texts={1:'renamed'})
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=first),patch('wlre.services.world.dynamic_bundle_runtime.current_catalog_token',return_value=('first',)):
            page=NavigationWindow(root);root.update()
            self.assertEqual(tuple(page.logical_map_choices['values']),('first(10000)',))
            page.scene.set('first(10000)')
            page.logical_map.set('first(10000)')
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=second),patch('wlre.services.world.dynamic_bundle_runtime.current_catalog_token',return_value=('second',)):
            page.refresh_names()
            self.assertEqual(page.scene.get(),'renamed(10000)')
            self.assertEqual(page.logical_map.get(),'renamed(10000)')
        with patch('wlre.services.world.runtime_1275.active_runtime',side_effect=ValueError('failed')),patch('wlre.services.world.dynamic_bundle_runtime.current_catalog_token',return_value=('failed',)):
            page.refresh_names()
            self.assertFalse(page.logical_map_choices['values'])
            self.assertEqual(page.logical_map.get(),'未知地圖(10000)')
            self.assertEqual(page.scene.get(),'未命名場景(10000)')
        self.assertFalse(errors,errors)
