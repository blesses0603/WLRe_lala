from _tk_native_pump import create_root
import sys
import os, time, tkinter as tk, unittest
from unittest.mock import patch
from wlre.services.official_version import BASELINE
from wlre.ui.gui import App


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt' or sys.platform == 'darwin','Requires a desktop')
class LoginAndTabAlignment(unittest.TestCase):
    def setUp(self):
        self.root=create_root();self.app=App(self.root);self.app.show_main();self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',job)
        self.root.destroy()

    def test_efficiency_is_right_aligned_and_survives_badge_rebuild(self):
        tabs=self.app.left_tabs;page=str(self.app.efficiency_launcher)
        for rebuild in (False,True):
            if rebuild:tabs.tab(self.app.party_launcher,text='組隊（1）');self.root.update()
            button=tabs.buttons[page]
            self.assertEqual(button.pack_info()['side'],'right')
            self.assertEqual(button.winfo_x()+button.winfo_width(),tabs.bar.winfo_width())
            self.assertGreater(button.winfo_x(),tabs.buttons[str(self.app.crafting_launcher)].winfo_x())
            button.invoke();self.root.update()
            self.assertEqual(self.app.feature_windows['efficiency'].state(),'normal')
            self.assertEqual(tabs.select(),str(self.app.overview_panel.master))
        tabs._step(page,-1);self.assertEqual(tabs.select(),str(self.app.crafting_launcher))

    def test_login_has_no_verification_toggle_and_always_verifies_before_login(self):
        self.app.show_login();self.root.update()
        def children(widget):
            for child in widget.winfo_children():yield child;yield from children(child)
        captions=[str(w.cget('text')) for w in children(self.app.login_window) if 'text' in w.keys()]
        self.assertNotIn('先驗證帳號，再登入',captions)
        self.assertNotIn('驗證並登入',captions)
        self.assertEqual(self.app.connect_button.cget('text'),'登入')
        # This is only a synthetic approved result: it must satisfy the
        # complete per-package gate contract, including a fresh check time.
        # Incomplete fixtures used to trigger a modal warning and hang CI.
        self.app._version_gate_result={
            'status':'version_identifiers_match','blocked':False,
            'remote':{
                'status':'same_resources',
                'packages':{
                    package:{'comparison':'same'} for package in BASELINE
                },
            },
        }
        self.app.version_gate_state='ready'
        self.app._version_gate_checked=time.monotonic()
        with patch('wlre.ui.version_gate_controller.messagebox.showwarning',
                   side_effect=AssertionError('unexpected version warning')):
            self.app.continue_to_login()
        self.assertTrue(self.app._version_gate_entry_approved)
        self.app.profile={'fixture':True};self.app.worker=None
        self.app.account.set('fixture-account');self.app.password.set('fixture-password')
        with (patch.object(self.app,'activate_account_settings'),
              patch.object(self.app,'save_saved_login',return_value=True),
              patch.object(self.app,'background',side_effect=lambda task:task()),
              patch('wlre.ui.gui.run_client') as run,
              patch('wlre.ui.version_gate_controller.messagebox.showinfo',
                    side_effect=AssertionError('unexpected version info dialog')),
              patch('wlre.ui.version_gate_controller.messagebox.showwarning',
                    side_effect=AssertionError('unexpected version warning'))):
            self.app.connect_button.invoke()
            run.assert_called_once()
            self.assertIs(run.call_args.kwargs['verify_first'],True)
            self.assertEqual(run.call_args.kwargs['account'],'fixture-account')

    def test_missing_package_comparison_still_blocks_login(self):
        # setUp enters the main dashboard and destroys its login window.
        # Re-create the hidden login screen to assert that denial never reveals it.
        self.app.show_login()
        self.app.login_window.withdraw()
        self.app._version_gate_result={
            'status':'version_identifiers_match','blocked':False,
            'remote':{'status':'same_resources','packages':{}},
        }
        self.app.version_gate_state='ready'
        with patch('wlre.ui.version_gate_controller.messagebox.showwarning') as warning:
            self.app.continue_to_login()
        warning.assert_called_once()
        self.assertFalse(self.app._version_gate_entry_approved)
        self.assertEqual(self.app.login_window.state(),'withdrawn')
        self.assertEqual(str(self.app.connect_button.cget('state')),'disabled')
