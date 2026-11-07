"""Offline Tk regressions: navigation is read-only; commands remain explicit."""
import os
import sys
import tkinter as tk
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

from wlre.core.state import State
from wlre.services.daily_assistant import command


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin', 'Requires Tk / Xvfb')
class DailyAssistantUITests(unittest.TestCase):
    def setUp(self):
        from wlre.ui.benefits_ui import BenefitsPanel
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.app = SimpleNamespace(live_active=True, snapshot={}, send=Mock(), open_feature=Mock())
        self.panel = BenefitsPanel(self.root, self.app)
        self.app.benefits_panel = self.panel
        self.panel.pack(fill='both', expand=True)
        self.root.geometry('760x700')
        self.state = State(phase='world_ready')
        self.state.daily_tasks.update(ready=True, groups_ready=True, catalog_ready=True, daily_value=25,
            rows=[dict(index=1, cycle=1, name='魔方', progress=1, goal=3, condition_kind=16,
                       condition_params=[3], condition='開啟魔方', execution='自動', eligible=False, received=False),
                  dict(index=2, cycle=1, name='未知任務', progress=0, goal=None,
                       condition_kind=99, condition_params=[], condition='未知', execution='手動', eligible=False, received=False)])
        self.refresh()
        self.ui = self.panel.assistant_panel
        self.panel.tabs.select(self.ui)
        self.root.update()

    def refresh(self):
        self.app.snapshot = self.state.snapshot()
        self.panel.render(self.app.snapshot)

    def test_open_select_render_and_drafts_do_not_send(self):
        self.panel.daily_panel.open_assistant()
        self.ui.tree.selection_set('1')
        self.ui.select()
        self.ui.variables['cube_enabled'].set(False)
        self.ui.variables['gold_budget'].set('123')
        self.refresh()
        self.root.update()
        self.assertFalse(self.ui.variables['cube_enabled'].get())
        self.assertEqual(self.ui.variables['gold_budget'].get(), '123')
        self.assertIn('1/3', self.ui.tree.item('1', 'values'))
        self.assertIn('需手動', self.ui.tree.item('2', 'values'))
        self.assertGreater(self.ui.tree.winfo_height(), 80)
        self.app.send.assert_not_called()

    def test_apply_is_one_atomic_command_with_independent_choices(self):
        for index, (key, var) in enumerate(self.ui.variables.items()):
            if key.endswith('_enabled'):
                var.set(index % 2 == 0)
        self.ui.variables['gold_budget'].set('0')
        self.ui.variables['star_budget'].set('15')
        self.ui.apply.invoke()
        self.app.send.assert_called_once()
        message = self.app.send.call_args.args[0]
        self.assertEqual(message['type'], 'daily_assistant')
        self.assertEqual(message['action'], 'configure')
        self.assertEqual(message['gold_budget'], 0)
        self.assertEqual(message['star_budget'], 15)
        for key, var in self.ui.variables.items():
            if key.endswith('_enabled'):
                self.assertEqual(message[key], var.get())
        before = deepcopy(self.state.star_ark)
        command(self.state, message, True)
        command(self.state, message, True)
        self.assertEqual(self.state.star_ark['reserved'], before['reserved'])
        self.assertEqual(self.state.star_ark['confirmed'], before['confirmed'])

    def test_invalid_budget_never_sends(self):
        for bad in ('-1', '1.5', '4294967296', ''):
            self.ui.variables['gold_budget'].set(bad)
            self.ui.apply.invoke()
        self.app.send.assert_not_called()
        self.assertIn('設定未送出', self.ui.status.get())

    def test_interrupted_operation_can_pause_but_not_reconfigure(self):
        self.state.star_ark.update(pending={'kind': 'dispatch'}, uncertain=True, reserved=30, confirmed=0)
        self.refresh()
        self.assertEqual(str(self.ui.apply['state']), 'disabled')
        self.assertIn('結果未確認', self.ui.status.get())
        self.assertIn('已要求額度 30', self.ui.budgets.get())
        self.ui.apply.invoke()
        self.app.send.assert_not_called()
        self.ui.pause.invoke()
        message = self.app.send.call_args.args[0]
        self.assertEqual(message, dict(type='daily_assistant', action='stop'))
        for _ in range(2):
            command(self.state, message, True)
        self.refresh()
        self.assertEqual(self.state.star_ark['pending'], {'kind': 'dispatch'})
        self.assertTrue(self.state.star_ark['uncertain'])
        self.assertEqual(self.state.star_ark['reserved'], 30)
        self.assertFalse(self.state.star_ark['enabled'])

    def test_disconnect_disables_actions_and_reconnect_syncs_settings(self):
        self.app.live_active = False
        self.refresh()
        self.ui.stop()
        self.ui.configure_assistant()
        self.app.send.assert_not_called()
        self.assertEqual(str(self.ui.pause['state']), 'disabled')
        self.app.live_active = True
        self.state.guild_actions.update(budget=100, sign_enabled=False)
        self.refresh()
        self.assertEqual(self.ui.variables['gold_budget'].get(), '100')
        self.assertFalse(self.ui.variables['guild_sign_enabled'].get())

    def test_default_window_keeps_controls_accessible_with_scroll(self):
        self.root.geometry('860x620')
        self.root.update()
        self.assertGreater(self.ui.canvas.winfo_height(), 100)
        self.assertLessEqual(self.ui.canvas.winfo_rooty() + self.ui.canvas.winfo_height(),
                             self.root.winfo_rooty() + self.root.winfo_height())
        self.assertGreaterEqual(self.ui.apply.winfo_rooty(), self.ui.canvas.winfo_rooty())
        self.assertLess(self.ui.pause.winfo_rootx() + self.ui.pause.winfo_width(),
                        self.ui.canvas.winfo_rootx() + self.ui.canvas.winfo_width())
        self.ui.canvas.yview_moveto(1)
        self.root.update()
        self.assertAlmostEqual(self.ui.canvas.yview()[1], 1.0, places=2)

    def test_new_daily_generation_discards_stale_draft(self):
        self.ui.variables['gold_budget'].set('123')
        self.state.daily_tasks['generation'] += 1
        self.refresh()
        self.assertEqual(self.ui.variables['gold_budget'].get(), str(self.state.guild_actions['budget']))
