import tkinter as tk
import unittest
from unittest.mock import patch
from gui_support import isolate_gui_background_checks


class SeedlessDesktopTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError as error:self.skipTest(str(error))
        def close():
            for job in self.root.tk.call('after','info'):
                self.root.tk.call('after','cancel',job)
            self.root.destroy()
        isolate_gui_background_checks(self)
        self.addCleanup(close)
        self.enterContext(patch('wlre.storage.bundled_database.load_bundled_bytes',side_effect=FileNotFoundError('isolated legacy data')))
        from wlre.ui.gui import App
        self.app=App(self.root)

    def test_dashboard_does_not_require_legacy_navigation(self):
        self.app.show_main();self.root.update_idletasks()
        self.assertTrue(self.app.overview_panel.winfo_ismapped())
        self.assertIsNone(self.app.home_map.repository)

    def test_missing_legacy_opens_independent_official_preview(self):
        from wlre.ui.official_navigation_preview import OfficialNavigationPreview
        before=len([w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)])
        with patch('wlre.ui.official_navigation_preview.OfficialNavigationPreview',wraps=OfficialNavigationPreview) as preview:
            self.app.open_navigation();self.assertEqual(preview.call_count,1)
        after=len([w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)])
        self.assertEqual(after,before+1)

    def test_corrupt_legacy_is_reported_not_hidden(self):
        with (patch('wlre.ui.navigation_gui.Repository',side_effect=ValueError('corrupt')),
              patch('wlre.ui.gui.messagebox.showerror') as error):
            self.app.open_navigation()
        error.assert_called_once()
