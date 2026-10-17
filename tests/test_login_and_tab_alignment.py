import os,tkinter as tk,unittest
from unittest.mock import patch
from wlre.ui.gui import App


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop')
class LoginAndTabAlignment(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.app=App(self.root);self.app.show_main();self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',job)
        self.root.destroy()

    def test_efficiency_is_right_aligned_and_survives_badge_rebuild(self):
        tabs=self.app.left_tabs;page=str(self.app.efficiency_panel)
        for rebuild in (False,True):
            if rebuild:tabs.tab(self.app.party_panel,text='組隊（1）');self.root.update()
            button=tabs.buttons[page]
            self.assertEqual(button.pack_info()['side'],'right')
            self.assertEqual(button.winfo_x()+button.winfo_width(),tabs.bar.winfo_width())
            self.assertGreater(button.winfo_x(),tabs.buttons[str(self.app.crafting_panel)].winfo_x())
            button.invoke();self.root.update();self.assertEqual(tabs.select(),page)
        tabs._step(page,-1);self.assertEqual(tabs.select(),str(self.app.crafting_panel))

    def test_login_has_no_verification_toggle_and_always_verifies_before_login(self):
        self.app.show_login();self.root.update()
        def children(widget):
            for child in widget.winfo_children():yield child;yield from children(child)
        captions=[str(w.cget('text')) for w in children(self.app.login_window) if 'text' in w.keys()]
        self.assertNotIn('先驗證帳號，再登入',captions)
        self.assertNotIn('驗證並登入',captions)
        self.assertEqual(self.app.connect_button.cget('text'),'登入')
        self.app.profile={'fixture':True};self.app.worker=None
        self.app.account.set('fixture-account');self.app.password.set('fixture-password')
        with patch.object(self.app,'activate_account_settings'),patch.object(self.app,'save_saved_login',return_value=True),patch.object(self.app,'background',side_effect=lambda task:task()),patch('wlre.ui.gui.run_client') as run:
            self.app.connect_button.invoke()
            run.assert_called_once()
            self.assertIs(run.call_args.kwargs['verify_first'],True)
            self.assertEqual(run.call_args.kwargs['account'],'fixture-account')
