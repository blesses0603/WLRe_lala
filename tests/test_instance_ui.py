"""Regression tests for the instance and co-op navigation skeleton."""
from _tk_native_pump import assert_normal_display, create_root
import sys
import os
import tkinter as tk
import unittest
from unittest.mock import patch
from tkinter import ttk

from wlre.ui.gui import App


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin', 'Requires a desktop or Xvfb')
class InstanceNavigation(unittest.TestCase):
    def setUp(self):
        self.root = create_root()
        self.app = App(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.app.show_main()
        self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()

    def test_main_entry_and_two_subtabs_are_navigable(self):
        panel = self.app.instance_panel
        launcher=self.app.instance_launcher
        self.assertTrue(launcher._section_outline)
        self.assertEqual(self.app.left_tabs.tab(launcher,'text'),'副本')
        self.assertEqual(self.app.instance_window.state(),'withdrawn')
        self.app.left_tabs.buttons[str(launcher)].invoke()
        self.root.update()
        self.assertEqual(self.app.left_tabs.select(),
                         str(self.app.overview_panel.master))
        assert_normal_display(self, self.app.instance_window)
        self.assertEqual(str(panel.winfo_toplevel()),str(self.app.instance_window))
        self.assertEqual(
            [panel.tabs.tab(page, 'text') for page in panel.tabs.tabs()],
            ['主要', '協力'],
        )
        for page, title in ((panel.main_page, '主要'), (panel.coop_page, '協力')):
            with self.subTest(mode=title):
                panel.tabs.buttons[str(page)].invoke()
                self.root.update()
                self.assertEqual(panel.tabs.select(), str(page))
                self.assertTrue(page.winfo_ismapped())
                self.assertEqual(page.entries.get_children(), ())
                self.assertEqual(
                    [page.entries.heading(column, 'text') for column in page.columns],
                    ['房間／副本', '人數／條件', '公開狀態'],
                )
                self.assertEqual(len(page.catalog_table.get_children()),
                                 3 if page.cooperative else 27)
                self.assertTrue(page.enter_button.instate(['disabled']))
        self.assertFalse(self.errors, self.errors)

    def test_new_icons_use_same_size_as_other_dashboard_tabs(self):
        launcher = self.app.instance_launcher
        controls = (
            self.app.left_tabs.buttons[str(launcher)],
            self.app.instance_panel.tabs.buttons[str(self.app.instance_panel.main_page)],
            self.app.instance_panel.tabs.buttons[str(self.app.instance_panel.coop_page)],
        )
        for button in controls:
            image = button.cget('image')
            self.assertTrue(image)
            self.assertEqual(int(self.root.tk.call('image', 'width', image)), 34)
            self.assertEqual(int(self.root.tk.call('image', 'height', image)), 34)
            # GlassTheme.skin() wraps the original ttk style at runtime as
            # Glass<serial>.Icon.Tab.TButton. Preserve that existing effect
            # instead of assuming the unskinned style name on every OS.
            style = button.cget('style')
            self.assertTrue(
                style == 'Icon.Tab.TButton'
                or (style.startswith('Glass')
                    and style.endswith('.Icon.Tab.TButton')),
                style)
        # Selecting co-op still uses the original Notebook navigation.
        self.app.instance_panel.tabs.select(self.app.instance_panel.coop_page)
        self.assertEqual(
            self.app.instance_panel.tabs.select(),
            str(self.app.instance_panel.coop_page))

    def test_compact_window_keeps_room_actions_above_the_lists(self):
        # A fixed-size popout must show both official and live room tables.
        panel = self.app.instance_panel
        self.app.open_instances()
        self.root.update()
        for page in (panel.main_page, panel.coop_page):
            with self.subTest(mode=page.mode):
                panel.tabs.select(page)
                self.root.update()
                for button in (page.create_button, page.refresh_button,
                               page.join_button, page.leave_button):
                    self.assertTrue(button.winfo_ismapped())
                    self.assertLess(
                        button.winfo_rooty() + button.winfo_height(),
                        page.catalog_table.winfo_rooty())
                self.assertLess(
                    page.create_button.winfo_rooty() + page.create_button.winfo_height(),
                    page.winfo_rooty() + page.winfo_height())
                self.assertTrue(page.entries.winfo_ismapped())
                self.assertTrue(page.room_list_note.get())
                self.assertGreater(page.entries.winfo_height(),1)
                if page.cooperative:
                    self.assertTrue(page.claim_button.winfo_ismapped())
                    self.assertLess(
                        page.claim_button.winfo_rooty() + page.claim_button.winfo_height(),
                        page.catalog_table.winfo_rooty())
        self.assertFalse(self.errors, self.errors)

    def test_creation_disabled_reason_for_selected_coop_dungeon(self):
        from wlre.core.state import State
        self.app.live_active = True
        panel = self.app.instance_panel
        state = State(phase='world_ready', initial_data_complete=True).snapshot()
        state['player']['role_id'] = 678
        state['expedition']['enabled'] = True
        self.app.open_instances()
        panel.render(state, live=True)
        panel.tabs.select(panel.coop_page)
        page = panel.coop_page
        page.catalog_table.selection_set('catalog_2')  # 1262 coop ID 28
        page.on_catalog_selected()
        self.root.update()
        self.assertTrue(page.create_button.instate(['!disabled']))
        self.assertNotIn('自動遠征仍開啟', page.creation_hint.get())
        self.assertTrue(page.creation_hint_label.winfo_ismapped())
        self.assertLess(page.creation_hint_label.winfo_rooty(),
                        page.catalog_table.winfo_rooty())
        state['expedition']['pending'] = {'started': 1}
        panel.render(state, live=True)
        self.assertTrue(page.create_button.instate(['disabled']))
        self.assertIn('遠征等待回覆', page.creation_hint.get())
        state['expedition']['pending'] = None
        panel.render(state, live=True)
        self.assertTrue(page.create_button.instate(['!disabled']))
        self.assertIn('可以建立公開／私人房間', page.creation_hint.get())

    def test_fixed_window_and_non_draggable_columns(self):
        self.app.open_instances()
        self.root.update()
        window=self.app.instance_window
        self.assertEqual(tuple(int(x) for x in window.resizable()),(0,0))
        self.assertEqual(window.minsize(),window.maxsize())
        self.assertLessEqual(window.winfo_width(),1040)
        self.assertLessEqual(window.winfo_height(),600)
        for page in (self.app.instance_panel.main_page,
                     self.app.instance_panel.coop_page):
            self.app.instance_panel.tabs.select(page)
            self.root.update()
            self.assertIsInstance(page.body,ttk.Frame)
            self.assertNotIsInstance(page.body,ttk.Panedwindow)
            self.assertEqual(page.catalog_column.winfo_manager(),'grid')
            self.assertEqual(page.room_column.winfo_manager(),'grid')
            self.assertEqual(page.catalog_column.grid_info()['column'],0)
            self.assertEqual(page.room_column.grid_info()['column'],1)
            self.assertTrue(page.entries.winfo_ismapped())
            self.assertTrue(page.catalog_table.winfo_ismapped())
        self.assertFalse(self.errors,self.errors)

    def test_window_close_and_reopen_preserves_selection(self):
        panel=self.app.instance_panel
        self.app.open_instances()
        panel.tabs.select(panel.coop_page)
        page=panel.coop_page
        page.catalog_table.selection_set('catalog_2')
        page.on_catalog_selected()
        self.root.update()
        with patch.object(self.app,'send') as send:
            self.app.instance_window.event_generate('<Escape>')  # harmless
            self.app.hide_instances()
            self.assertEqual(self.app.instance_window.state(),'withdrawn')
            self.assertFalse(page.winfo_ismapped())
            self.app.open_instance_button.invoke()
            self.root.update()
            assert_normal_display(self, self.app.instance_window)
            self.assertEqual(panel.tabs.select(),str(page))
            self.assertEqual(page.catalog_table.selection(),('catalog_2',))
            send.assert_not_called()
        self.assertFalse(self.errors,self.errors)

    def test_unverified_entry_never_sends_game_commands(self):
        panel = self.app.instance_panel
        self.app.open_instances()
        with patch.object(self.app, 'send') as send:
            for page in (panel.main_page, panel.coop_page):
                panel.tabs.select(page)
                self.root.update()
                page.enter_button.invoke()
            send.assert_not_called()
        self.assertFalse(self.errors, self.errors)

    def test_creation_enabled_only_when_ready_and_catalog_selected(self):
        from wlre.core.state import State
        panel = self.app.instance_panel
        self.app.live_active = True
        state = State().snapshot()
        panel.render(state, live=True)
        self.assertTrue(panel.main_page.create_button.instate(['disabled']))
        panel.main_page.catalog_table.selection_set('catalog_0')
        panel.main_page.on_catalog_selected()
        self.assertTrue(panel.main_page.create_button.instate(['!disabled']))
        panel.coop_page.catalog_table.selection_set('catalog_1')
        panel.coop_page.on_catalog_selected()
        self.assertTrue(panel.coop_page.create_button.instate(['!disabled']))
        state['instances']['main']['create_pending'] = {'map_id': 30012}
        panel.render(state, live=True)
        self.assertTrue(panel.main_page.create_button.instate(['disabled']))
        self.assertTrue(panel.coop_page.create_button.instate(['disabled']))
        state['instances']['main']['create_pending'] = None
        state['instances']['coop']['create_uncertain'] = True
        panel.render(state, live=True)
        self.assertTrue(panel.main_page.create_button.instate(['disabled']))
        panel.render(State().snapshot(), live=False)
        self.assertTrue(panel.coop_page.create_button.instate(['disabled']))

    def test_create_dialog_requires_confirm_before_send(self):
        from wlre.core.state import State
        panel = self.app.instance_panel
        self.app.live_active = True
        panel.render(State().snapshot(), live=True)
        page = panel.main_page
        page.catalog_table.selection_set('catalog_0')
        page.on_catalog_selected()
        def visit(widget):
            yield widget
            for child in widget.winfo_children():
                yield from visit(child)
        with patch.object(self.app, 'send') as send:
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=False):
                page.open_create_dialog()
                dialog = next(w for w in self.root.winfo_children()
                              if isinstance(w, tk.Toplevel) and w.title() == '建立副本房間')
                confirm = next(w for w in visit(dialog)
                               if isinstance(w, ttk.Button)
                               and w.cget('text') == '確認建立')
                confirm.invoke()
                send.assert_not_called()
                dialog.destroy()
            with patch('wlre.ui.instance_ui.messagebox.askyesno', return_value=True):
                page.open_create_dialog()
                dialog = next(w for w in self.root.winfo_children()
                              if isinstance(w, tk.Toplevel) and w.title() == '建立副本房間')
                confirm = next(w for w in visit(dialog)
                               if isinstance(w, __import__('tkinter.ttk').ttk.Button)
                               and w.cget('text') == '確認建立')
                confirm.invoke()
                send.assert_called_once_with({
                    'type': 'instance_create', 'mode': 'main', 'public': True,
                    'password': '', 'map_id': 30012
                })
        self.assertTrue(page.create_button.instate(['disabled']))

    def test_room_snapshots_and_safe_manual_refresh(self):
        from wlre.core.state import State
        panel = self.app.instance_panel
        self.app.live_active = True
        state = State().snapshot()
        state['instances']['main'].update(
            ready=True, status='房間清單同步完成',
            rooms=[{'room_id': 101, 'members': 2, 'public': True}])
        state['instances']['coop'].update(
            ready=True, rooms=[{'room_id': 202, 'members': 1,
                                'capacity': 4, 'public': False}])
        panel.render(state, live=True)
        self.assertEqual(len(panel.main_page.entries.get_children()), 1)
        self.assertEqual(len(panel.coop_page.entries.get_children()), 1)
        self.assertEqual(
            panel.main_page.entries.item(panel.main_page.entries.get_children()[0], 'values')[0],
            '房間 #101',
        )
        with patch.object(self.app, 'send') as send:
            panel.main_page.refresh_button.invoke()
            panel.coop_page.refresh_button.invoke()
            self.assertEqual(send.call_count, 2)
            self.assertEqual(send.call_args_list[0].args[0],
                             {'type': 'instance_refresh', 'mode': 'main'})
            self.assertEqual(send.call_args_list[1].args[0],
                             {'type': 'instance_refresh', 'mode': 'coop'})
            panel.main_page.enter_button.invoke()
            panel.coop_page.enter_button.invoke()
            self.assertEqual(send.call_count, 2)
        panel.render(State().snapshot(), live=False)
        self.assertTrue(panel.main_page.refresh_button.instate(['disabled']))
        self.assertTrue(panel.coop_page.enter_button.instate(['disabled']))
        self.assertEqual(panel.coop_page.entries.get_children(), ())
