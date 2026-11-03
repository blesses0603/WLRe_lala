"""v0.5.2: all secondary functions are fixed windows centered on main."""

from gui_support import isolate_gui_background_checks
import os
import tkinter as tk
import unittest
from unittest.mock import Mock

from wlre.ui.feature_windows import WINDOWS
from wlre.ui.window_layout import center_on_main


class DailyDestinationRouting(unittest.TestCase):
    def test_ark_and_guild_open_other_window_and_select_their_page_without_sending(self):
        from types import SimpleNamespace
        from wlre.ui.daily_tasks_ui import DailyTaskPanel
        for kind,target in ((9,'ark_panel'),(10,'guild_panel')):
            with self.subTest(kind=kind):
                other=SimpleNamespace(tabs=Mock(),ark_panel=object(),guild_panel=object())
                app=SimpleNamespace(other_features_panel=other,open_feature=Mock(),send=Mock())
                tree=Mock();tree.selection.return_value=('1',)
                panel=SimpleNamespace(app=app,tree=tree,rows={'1':dict(condition_kind=kind)})
                DailyTaskPanel.open_destination(panel)
                app.open_feature.assert_called_once_with('other')
                other.tabs.select.assert_called_once_with(getattr(other,target))
                app.send.assert_not_called()


class CenterGeometry(unittest.TestCase):
    def test_main_center_when_display_has_space(self):
        main=Mock()
        main.winfo_x.return_value=180
        main.winfo_y.return_value=120
        main.winfo_width.return_value=1280
        main.winfo_height.return_value=800
        window=Mock()
        window.winfo_screenwidth.return_value=2048
        window.winfo_screenheight.return_value=1200
        size=center_on_main(window,main,880,600)
        self.assertEqual(size,(880,600,380,220))
        window.resizable.assert_called_once_with(False,False)
        window.minsize.assert_called_once_with(880,600)
        window.maxsize.assert_called_once_with(880,600)

    def test_720p_clamp_stays_visible(self):
        main=Mock()
        main.winfo_x.return_value=0
        main.winfo_y.return_value=0
        main.winfo_width.return_value=1280
        main.winfo_height.return_value=800
        window=Mock()
        window.winfo_screenwidth.return_value=1280
        window.winfo_screenheight.return_value=720
        w,h,x,y=center_on_main(window,main,1080,650)
        self.assertLessEqual(x+w,1280)
        self.assertLessEqual(y+h,720)
        self.assertGreaterEqual(x,0)
        self.assertGreaterEqual(y,0)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt',
                     'Requires Tk / Xvfb')
class SecondaryFeatures(unittest.TestCase):
    def setUp(self):
        isolate_gui_background_checks(self)
        from wlre.ui.gui import App
        self.root=tk.Tk()
        self.app=App(self.root)
        self.errors=[]
        self.root.report_callback_exception=lambda *e:self.errors.append(e)
        self.app.show_main()
        self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after','info'):
            self.root.tk.call('after','cancel',job)
        self.root.destroy()

    def test_every_non_home_tab_is_a_launcher(self):
        self.assertEqual(tuple(self.app.feature_windows),tuple(WINDOWS))
        self.assertEqual(len(self.app.feature_launchers),9)
        self.assertEqual(
            [self.app.left_tabs.tab(t,'text') for t in self.app.left_tabs.tabs()],
            ['主頁','組隊','夥伴出戰','遠征','副本','福利','其他功能','煉金','製作','經驗效率'])
        for key in WINDOWS:
            panel=getattr(self.app, {
                'party':'party_panel','companion':'companion_panel',
                'expedition':'expedition_panel','instance':'instance_panel',
                'alchemy':'alchemy_panel','crafting':'crafting_panel',
                'benefits':'benefits_panel','other':'other_features_panel','efficiency':'efficiency_panel'}[key])
            self.assertEqual(panel.winfo_toplevel(),
                             self.app.feature_windows[key])
            self.assertEqual(self.app.feature_windows[key].state(),'withdrawn')

    def test_open_always_centers_on_main_and_reuses_window(self):
        home=self.app.left_tabs.select()
        for key in WINDOWS:
            with self.subTest(key=key):
                window=self.app.feature_windows[key]
                self.app.left_tabs.buttons[str(self.app.feature_launchers[key])].invoke()
                self.root.update()
                self.assertEqual(window.state(),'normal')
                self.assertEqual(self.app.left_tabs.select(),home)
                self.assertEqual(tuple(int(x) for x in window.resizable()),(0,0))
                self.assertEqual(window.minsize(),window.maxsize())
                # No network command may be sent merely by opening or hiding.
                identity=str(window)
                self.app.hide_feature(key)
                self.assertEqual(window.state(),'withdrawn')
                self.app.open_feature(key)
                self.root.update()
                self.assertEqual(str(window),identity)
                self.app.hide_feature(key)
        self.assertFalse(self.errors,self.errors)

    def test_all_windows_hidden_when_relogging(self):
        self.app.open_feature('party')
        self.app.open_feature('instance')
        self.app.hide_all_features()
        self.assertTrue(all(window.state()=='withdrawn'
                            for window in self.app.feature_windows.values()))

    def test_other_window_owns_ark_and_guild_pages_and_benefits_keeps_only_rewards(self):
        benefits=self.app.benefits_panel;other=self.app.other_features_panel
        self.assertEqual([benefits.tabs.tab(p,'text') for p in benefits.tabs.tabs()],
                         ['魔方','每日任務','每週任務'])
        self.assertEqual([other.tabs.tab(p,'text') for p in other.tabs.tabs()],['方舟','組織'])
        for panel in (other.ark_panel,other.guild_panel):
            self.assertEqual(panel.winfo_toplevel(),self.app.feature_windows['other'])
        self.assertFalse(hasattr(benefits,'ark_panel'))
        self.assertFalse(hasattr(benefits,'guild_panel'))

    def test_missing_game_sidebar_sprites_fall_back_to_text(self):
        from wlre.ui.instance_menu_icons import MENU_ASSETS, menu_icon_photo
        self.assertIn('主要',MENU_ASSETS)
        self.assertIn('協力',MENU_ASSETS)
        # The unit test does not assume the original game SpriteAtlas was
        # supplied; text must remain usable when an image is missing.
        page=self.app.instance_panel
        self.app.open_instances()
        self.root.update()
        self.assertTrue(page.tabs.buttons[str(page.main_page)].winfo_ismapped())
        self.assertTrue(page.tabs.buttons[str(page.coop_page)].winfo_ismapped())


if __name__=='__main__':
    unittest.main()
