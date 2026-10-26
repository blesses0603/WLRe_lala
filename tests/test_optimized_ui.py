import os,queue,tempfile,tkinter as tk,unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from wlre.ui.gui import App
from wlre.core.state import State


class BackgroundUpdates(unittest.TestCase):
    def test_background_coalesces_and_foreground_flushes_latest(self):
        events=queue.Queue();events.put(('state',{'value':1}));events.put(('state',{'value':2}))
        app=SimpleNamespace(events=events,diagnostics=Mock(),render=Mock(),root=Mock(),poll=Mock(),
            background_window=Mock(return_value=True),_pending_display=None,_last_display=10,
            _background_logs=deque(),chat_panel=SimpleNamespace(display_dirty=False),live_active=False)
        with patch('wlre.ui.gui.time.perf_counter',return_value=0),patch('wlre.ui.gui.time.monotonic',return_value=10.1):App.poll(app)
        app.render.assert_not_called()
        self.assertEqual(app._pending_display,{'value':2})
        app.background_window.return_value=False
        with patch('wlre.ui.gui.time.perf_counter',return_value=0),patch('wlre.ui.gui.time.monotonic',return_value=10.2):App.poll(app)
        app.render.assert_called_once_with({'value':2})
        self.assertIsNone(app._pending_display)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop or Xvfb')
class OptimizedWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # GUI layout tests must not start real release/version HTTP workers.
        # Those workers can trigger cyclic GC of a retired Tcl interpreter
        # from a non-UI thread while later test cases create new Tk roots.
        with patch.object(App, 'start_version_check'):
            cls.root=tk.Tk()
            cls.app=App(cls.root)
            cls.app.show_main()
            cls.root.update()

    @classmethod
    def tearDownClass(cls):
        import gc
        root,app=cls.root,cls.app
        for job in root.tk.call('after','info'):
            root.tk.call('after','cancel',job)
        try:
            app.close()
        finally:
            # A class fixture otherwise retains all Tk Variables and images
            # for the rest of unittest discovery, past root.destroy().
            cls.app=None
            cls.root=None
            del app,root
            gc.collect()

    def test_account_switch_restores_settings_without_starting_ai(self):
        from wlre.storage import account_settings as store
        original=store.settings_file
        previous=self.app.ai_settings;previous_key=self.app._settings_key
        with tempfile.TemporaryDirectory() as directory,patch.object(store,'settings_file',side_effect=lambda key,base=None:original(key,directory)):
            try:
                self.app.host.set('fixture');self.app.port.set('123');self.app.account.set('account-a')
                self.app.activate_account_settings('fixture',123,'account-a')
                self.app.ai_settings['field_heal']=True;self.app.persist_ai_settings(self.app.ai_settings)
                self.app.account.set('account-b');self.app.activate_account_settings('fixture',123,'account-b')
                self.assertFalse(self.app.ai_settings['field_heal'])
                self.app.account.set('account-a');self.app.activate_account_settings('fixture',123,'account-a')
                self.assertTrue(self.app.ai_settings['field_heal'])
                self.assertFalse(self.app.snapshot.get('auto_battle',{}).get('enabled',False))
            finally:self.app.ai_settings=previous;self.app._settings_key=previous_key

    def test_editor_rejects_apply_after_account_switch(self):
        from wlre.storage import account_settings as store
        from wlre.ui.auto_battle_ui import SettingsEditor
        original=store.settings_file
        with tempfile.TemporaryDirectory() as directory,patch.object(store,'settings_file',side_effect=lambda key,base=None:original(key,directory)):
            self.app.account.set('account-a');self.app.activate_account_settings('fixture',123,'account-a')
            editor=SettingsEditor(self.app)
            try:
                self.app.account.set('account-b');self.app.activate_account_settings('fixture',123,'account-b')
                with patch('wlre.ui.auto_battle_ui.messagebox.showerror') as error:editor.apply()
                self.assertIn('帳號已變更',error.call_args.args[1])
                self.assertFalse(list(Path(directory).rglob('*.json')))
            finally:editor.window.destroy()

    def test_hidden_panel_defers_render_until_selected(self):
        self.app.left_tabs.select(self.app.overview_panel.master);self.root.update()
        state=State().snapshot()
        with patch.object(self.app.alchemy_panel,'render') as renderer:
            self.app.render(state);renderer.assert_not_called()
            self.app.open_feature('alchemy');self.root.update()
            renderer.assert_called()
        self.app.left_tabs.select(self.app.overview_panel.master);self.root.update()

    def test_background_logs_and_chat_are_bounded_and_restored(self):
        self.app.entered_world=True
        before=self.app.chat_panel.view.get('1.0','end')
        with patch.object(self.app,'background_window',return_value=True):
            for i in range(600):self.app.write(f'fixture-log-{i}')
            self.app.chat_panel.handle_event({'type':'chat_message','channel':'世界','role_id':99,'text':'fixture-message'},State().snapshot())
            self.assertEqual(len(self.app._background_logs),500)
            self.assertTrue(self.app.chat_panel.display_dirty)
            self.assertEqual(before,self.app.chat_panel.view.get('1.0','end'))
        with patch.object(self.app,'background_window',return_value=False):self.app.poll()
        self.assertFalse(self.app.chat_panel.display_dirty)
        self.assertIn('fixture-message',self.app.chat_panel.view.get('1.0','end'))
        self.assertIn('fixture-log-599',self.app.log.get('1.0','end'))
        self.assertFalse(self.app._background_logs)

    def test_account_activation_does_not_publish_key_if_expedition_load_fails(self):
        previous_key=self.app._settings_key;previous_settings=self.app.ai_settings
        with patch('wlre.ui.account_controller.account_settings.load',return_value=dict(previous_settings)),patch.object(self.app.expedition_panel,'load_settings',side_effect=OSError('settings unavailable')):
            with self.assertRaises(OSError):self.app.activate_account_settings('fixture',123,'another-account')
        self.assertEqual(self.app._settings_key,previous_key)
        self.assertIs(self.app.ai_settings,previous_settings)
