"""Compatibility entry follows official scene mapping without legacy readers."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires Tk display')
class OfficialMapNamesUITests(unittest.TestCase):
    def test_open_window_updates_official_mapping_and_clears_failed_source(self):
        import tkinter as tk
        from wlre.ui.navigation_gui import NavigationWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        first=SimpleNamespace(stages={10011:{'model_id':10001}},catalog_identity=SimpleNamespace(key='first'),
                              smallmaps=SimpleNamespace(catalog_key='first',models={10001}))
        second=SimpleNamespace(stages={10011:{'model_id':12050}},catalog_identity=SimpleNamespace(key='second'),
                               smallmaps=SimpleNamespace(catalog_key='second',models={12050}))
        callback=Mock()
        with patch('wlre.storage.bundled_database.load_bundled_bytes',side_effect=AssertionError('legacy read')) as legacy:
            with patch('wlre.ui.official_navigation_preview.current_runtime',return_value=first):
                page=NavigationWindow(root,10011,on_route=callback);root.update();page.window.after_cancel(page.timer);page.poll()
                self.assertIn('模型 M10001',page.mapping.get())
                self.assertEqual(page.fields[0].get(),'10011')
            with patch('wlre.ui.official_navigation_preview.current_runtime',return_value=second):
                page.window.after_cancel(page.timer);page.poll();self.assertIn('模型 M12050',page.mapping.get())
                self.assertEqual(page.fields[0].get(),'10011')
            with patch('wlre.ui.official_navigation_preview.current_runtime',return_value=None):
                page.window.after_cancel(page.timer);page.poll();self.assertIn('請先完成官方資料同步',page.mapping.get())
            legacy.assert_not_called();callback.assert_not_called()
            page.close()
        self.assertFalse(errors,errors)
