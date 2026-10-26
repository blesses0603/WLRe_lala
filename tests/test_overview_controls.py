import os
import tkinter as tk
import unittest
from unittest.mock import patch
from wlre.core.state import State
from wlre.ui.gui import App
from wlre.ui.auto_battle_ui import SettingsEditor
from wlre.ui.halo_button import edge_points,edge_overlay


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop')
class OverviewControls(unittest.TestCase):
    def setUp(self):
        # These tests verify local Tk controls, not remote update/version checks.
        # Keep all Tk lifecycle work on the test/UI thread with no HTTP workers.
        with patch.object(App, 'start_version_check'):
            self.root=tk.Tk();self.app=App(self.root);self.app.show_main();self.root.update()
        self.panel=self.app.overview_panel;self.app.live_active=True
        self.state=State().snapshot();self.state['player']={'role_id':1,'name':'測試角色','scene':12000}
        self.app.render(self.state);self.root.update()

    def tearDown(self):
        # Explicitly close and release all Tk widgets on the test main thread.
        # Deferred GC by a networking/animation worker otherwise can invoke
        # tkinter.Variable.__del__ from the wrong thread after Tk has ended.
        import gc
        for job in self.root.tk.call('after','info'):
            self.root.tk.call('after','cancel',job)
        self.app.close()
        self.panel = None
        self.app = None
        self.root = None
        gc.collect()

    def test_both_actions_start_stop_and_follow_confirmed_state(self):
        for key,section,start,stop in (('ai','auto_battle','start_auto_battle','stop_auto_battle'),('roaming','roaming','start_roaming','stop_roaming')):
            button=self.panel.actions[key]
            with patch.object(self.app,'send') as send:
                button.invoke();self.assertEqual(send.call_args.args[0]['type'],start)
                self.assertFalse(button.active)
                self.state[section]['enabled']=True
                self.app.render(self.state);self.root.update()
                self.assertEqual(button.cget('text'),'關閉')
                self.assertTrue(button.halo_visible);self.assertIsNotNone(button.job)
                button.invoke();self.assertEqual(send.call_args.args[0]['type'],stop)
                self.state[section]['enabled']=False
                self.app.render(self.state);self.root.update()
                self.assertEqual(button.cget('text'),'啟動')
                self.assertFalse(button.halo_visible);self.assertIsNone(button.job)

    def test_all_three_automation_buttons_switch_images_only_after_state_update(self):
        for key, section in (
            ('ai', 'auto_battle'),
            ('roaming', 'roaming'),
            ('expedition', 'expedition'),
        ):
            with self.subTest(feature=key):
                button = self.panel.actions[key]
                idle_photo = str(button.cget('image'))
                self.assertTrue(idle_photo)
                self.assertEqual(self.root.tk.call('image', 'width', idle_photo), 28)
                self.assertEqual(button.cget('text'), '啟動')
                self.state[section]['enabled'] = True
                self.app.render(self.state)
                self.root.update()
                self.assertNotEqual(str(button.cget('image')), idle_photo)
                self.assertEqual(button.cget('text'), '關閉')
                self.assertTrue(button.active)
                self.state[section]['enabled'] = False
                self.app.render(self.state)
                self.root.update()
                self.assertEqual(str(button.cget('image')), idle_photo)
                self.assertFalse(button.active)

    def test_expedition_home_toggle_commands_unchanged_with_images(self):
        button = self.panel.actions['expedition']
        with patch.object(self.app.expedition_panel, 'start') as start, (
                patch.object(self.app, 'send') as send):
            button.invoke()
            start.assert_called_once_with()
            self.assertFalse(button.active)
            self.assertEqual(button.cget('text'), '啟動')
            self.state['expedition']['enabled'] = True
            self.app.render(self.state)
            self.root.update()
            button.invoke()
            send.assert_called_once_with({'type': 'stop_expedition'})
            self.assertEqual(button.cget('text'), '關閉')

    def test_hidden_animation_pauses_and_disconnect_clears_halo(self):
        self.state['auto_battle']['enabled']=True;self.app.render(self.state);self.root.update()
        button=self.panel.actions['ai']
        self.app.left_tabs.select(self.app.crafting_launcher);self.root.update()
        self.assertIsNone(button.job)
        self.app.left_tabs.select(self.panel.master);self.root.update()
        self.assertIsNotNone(button.job)
        self.app.live_active=False;self.panel.refresh()
        self.assertFalse(button.active);self.assertIsNone(button.job)

    def test_overview_uses_shared_border_and_actions_use_standard_button_geometry(self):
        self.assertTrue(self.panel.master._section_outline)
        reference=self.panel.actions['roaming']
        for key in ('ai','roaming'):
            button=self.panel.actions[key]
            self.assertEqual(button.winfo_class(),'TButton')
            self.assertEqual(button.cget('padding'),reference.cget('padding'))
            self.assertEqual(button.cget('width'),reference.cget('width'))
            self.assertEqual(button.winfo_width(),reference.winfo_width())
            self.assertEqual(button.winfo_height(),reference.winfo_height())
            self.assertFalse(button.winfo_children())

    def test_rainbow_follows_button_edge_without_rectangular_canvas_frame(self):
        button=self.panel.actions['ai'];theme=self.app.theme
        theme.windows[str(self.root)]['signature']=None;theme.paint(self.root)
        button.set_active(True)
        def pixel(x,y):return tuple(self.root.tk.call(str(button.photos[0]),'get',x,y))
        base=button.surfaces[0].convert('RGB');width,height=base.size
        self.assertEqual(pixel(1,1),base.getpixel((1,1)))
        self.assertNotEqual(pixel(width//2,1),base.getpixel((width//2,1)))
        first=pixel(width//2,1)
        button.phase+=.3;button.paint_edge()
        self.assertNotEqual(pixel(width//2,1),first)
        button.set_active(False)
        self.assertEqual(pixel(width//2,1),base.getpixel((width//2,1)))
        self.assertFalse(button.halo_visible)

    def test_animation_uses_elapsed_time_and_does_not_restart_on_state_refresh(self):
        button=self.panel.actions['ai']
        with patch('wlre.ui.halo_button.time.monotonic',return_value=100):button.set_active(True)
        origin=button.started
        with patch('wlre.ui.halo_button.time.monotonic',return_value=101):button.set_active(True)
        self.assertEqual(button.started,origin)
        button.pause()
        with patch('wlre.ui.halo_button.time.monotonic',return_value=101.5),patch.object(button,'after',return_value='fixture') as after:
            button.animate()
            self.assertAlmostEqual(button.phase,.5)
            self.assertLessEqual(after.call_args.args[0],16)
        button.job=None

    def test_supply_settings_still_open_after_removing_battle_tab(self):
        from unittest.mock import Mock
        editor=Mock();editor.recovery_tab='fixture-recovery-page'
        with patch('wlre.ui.auto_battle_ui.open_settings',return_value=editor) as settings:
            self.panel.actions['supply'].invoke()
            settings.assert_called_once_with(self.app)
            editor.tabs.select.assert_called_once_with('fixture-recovery-page')

    def test_settings_entry_title_map_header_and_button_bounds(self):
        with patch('wlre.ui.auto_battle_ui.open_settings') as settings:
            self.panel.ai_settings_button.invoke();settings.assert_called_once_with(self.app)
        editor=SettingsEditor(self.app)
        try:self.assertEqual(editor.window.title(),'自動戰鬥設定')
        finally:editor.window.destroy()
        descendants=list(self.app.theme.descendants(self.root))
        captions=[str(w.cget('text')) for w in descendants if 'text' in w.keys()]
        self.assertNotIn('進階導航',captions)
        self.assertNotIn('Lua 規則自動戰鬥',captions)
        self.assertIn('自動戰鬥',captions)
        for key in ('ai','roaming'):
            button=self.panel.actions[key];frame=self.panel.cards[key]
            self.assertLessEqual(button.winfo_x()+button.winfo_width(),frame.winfo_width())
            self.assertLessEqual(button.winfo_y()+button.winfo_height(),frame.winfo_height())


class EdgeSampling(unittest.TestCase):
    def test_straights_and_corners_have_even_color_spacing(self):
        import math
        points=edge_points(52,20)
        lengths=[math.dist(point,points[(i+1)%len(points)][0]) for i,(point,_) in enumerate(points)]
        self.assertLessEqual(max(lengths),.76)
        self.assertGreater(min(lengths),.5)
        self.assertIs(points,edge_points(52,20))


class StableHaloMask(unittest.TestCase):
    def test_alpha_is_identical_through_full_color_cycle_and_has_no_square_corners(self):
        first=edge_overlay(52,20,0)
        alpha=first.getchannel('A')
        for phase in (.01,.25,.5,.75,.99):
            frame=edge_overlay(52,20,phase)
            self.assertEqual(frame.getchannel('A').tobytes(),alpha.tobytes())
            self.assertNotEqual(frame.tobytes(),first.tobytes())
        for x,y in ((0,0),(1,1),(50,1),(1,18),(50,18),(26,10)):
            self.assertEqual(alpha.getpixel((x,y)),0)
        self.assertGreater(alpha.getpixel((26,1)),0)
