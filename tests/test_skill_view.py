"""Skill entry owns no inventory UI; live updates and cast guards stay intact."""
import os
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from wlre.ui.skill_view import SkillView
from wlre.ui.feature_navigation import FeatureWindowController
from test_skill_browser import ACTORS, ROWS, CATALOG


class NavigationTests(unittest.TestCase):
    def test_skill_entry_is_single_instance_and_refreshes_on_reopen(self):
        app=FeatureWindowController()
        app.assert_ui_thread=Mock();app.skill_window=None;app.snapshot={}
        view=Mock();view.window.winfo_exists.return_value=True
        with patch('wlre.ui.feature_navigation.SkillView',return_value=view) as create:
            app.open_skills();app.open_skills()
            create.assert_called_once_with(app)
            view.set_state.assert_called_once_with(app.snapshot)
            view.window.lift.assert_called_once()
            view.window.winfo_exists.return_value=False
            app.open_skills()
            self.assertEqual(create.call_count,2)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop')
class SkillWindowTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.geometry('1000x700')
        self.errors=[];self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.app=SimpleNamespace(root=self.root,snapshot={'player':{'role_id':1},'battle':{'active':False},'knowledge':{}},
                                 live_active=True,send=Mock(),priority_target=None)
        self.rows=patch('wlre.ui.skill_browser.skill_rows',return_value=ROWS)
        self.cat=patch('wlre.ui.skill_browser.CAT',CATALOG)
        self.rows.start();self.cat.start()
        with patch('wlre.ui.resource_view.BagGrid',side_effect=AssertionError('inventory constructed')), \
             patch('wlre.ui.resource_view.ItemIcons',side_effect=AssertionError('item icons loaded')):
            self.view=SkillView(self.app)
        self.root.update()

    def tearDown(self):
        self.root.destroy();self.rows.stop();self.cat.stop()
        self.assertFalse(self.errors)

    def test_independent_window_has_no_bag_storage_or_commands_on_open(self):
        self.assertFalse(hasattr(self.view,'bag'))
        self.assertFalse(hasattr(self.view,'remote_garage'))
        self.app.send.assert_not_called()
        self.assertEqual(len(self.view.skill_browser.rows),2)

    def test_disconnect_and_account_removal_clear_cast_state(self):
        self.app.live_active=False
        self.view.set_state(self.app.snapshot)
        self.assertEqual(str(self.view.skill_browser.cast['state']),'disabled')
        self.app.snapshot={}
        self.view.set_state({})
        self.assertFalse(self.view.skill_browser.skill_map)
        self.app.send.assert_not_called()

    def test_inventory_only_updates_recompute_cost_item_reasons(self):
        with patch.object(self.view.skill_browser,'render',wraps=self.view.skill_browser.render) as render:
            self.app.snapshot=dict(self.app.snapshot,inventory={'revision':2,'items':{'1':{'count':1}}})
            self.view.set_state(self.app.snapshot)
            render.assert_called_once()

    def test_search_refresh_and_close_do_not_send(self):
        self.view.query.set('no-match');self.root.update()
        self.assertFalse(self.view.skill_browser.rows)
        self.view.query.set('');self.root.update()
        self.assertEqual(len(self.view.skill_browser.rows),2)
        self.view.window.destroy();self.root.update()
        self.app.send.assert_not_called()

    def test_click_uses_latest_live_state_guard(self):
        self.app.live_active=False
        with patch('wlre.ui.skill_view.messagebox.showinfo') as message:
            self.view.use_skill()
            message.assert_called_once()
        self.app.send.assert_not_called()

    def test_bag_window_no_longer_creates_skill_browser(self):
        from wlre.ui.resource_view import ResourceView
        with patch('wlre.ui.skill_view.SkillBrowser',side_effect=AssertionError('skill UI constructed')):
            bag=ResourceView(self.app)
        self.assertFalse(hasattr(bag,'skill_browser'))
        self.assertEqual(len(bag.tabs.tabs()),2)
        bag.window.destroy()
