"""A server name cannot redirect remembered credentials to a new endpoint."""
from copy import deepcopy
from types import SimpleNamespace
import os
import unittest
from unittest.mock import Mock, patch
from wlre.storage import server_lines
from wlre.ui.login_controller import LoginController


class Value:
    def __init__(self, value=''): self.value=value
    def get(self): return self.value
    def set(self, value): self.value=value


OLD = {'id':101, 'name':'地球一線', 'host':'old.example', 'port':16988}
NEW = dict(OLD, host='new.example', port=17000)


class Form(LoginController):
    def __init__(self):
        for key,value in dict(host=OLD['host'],port=str(OLD['port']),account='fixture-account',
                password='fixture-password',server_line=OLD['name'],server_group='地球',
                line_display='1線',remember_account=True,remember_password=True,status='').items():
            setattr(self,key,Value(value))
        self._selected_line_id=101;self._line_endpoint=(OLD['host'],str(OLD['port']))
        self.line_catalog=[dict(OLD)];self.line_choices={server_lines.CUSTOM:None,OLD['name']:dict(OLD)}
        self._memory_restoring=False;self._password_autofilled=True
        self._login_memory_key='old-key';self._loaded_identity=(OLD['host'],str(OLD['port']),'fixture-account',101)
        self.server_choice=Mock();self.line_choice=Mock();self.saved_account_choice=Mock()
        self.server_list_status_label=Mock();self.live_active=False
        self.activate_account_settings=Mock()


class EndpointBindingTests(unittest.TestCase):
    def setUp(self): self.form=Form()

    def refresh(self, rows):
        with patch('wlre.ui.login_controller.server_lines.load',return_value=deepcopy(rows)), \
             patch('wlre.ui.login_controller.server_lines.status_label',return_value='fixture'), \
             patch('wlre.ui.login_controller.login_memory.list_entries',return_value=[]), \
             patch('wlre.ui.login_controller.login_memory.save') as save, \
             patch('wlre.ui.login_controller.login_memory.delete') as delete:
            self.form.refresh_server_lines()
        save.assert_not_called();delete.assert_not_called()

    def test_identity_change_after_widget_destruction_still_clears_secret(self):
        self.form.saved_account_choice.winfo_exists.return_value=False
        self.form.account.set('different-account')
        self.form.login_identity_changed()
        self.assertEqual(self.form.password.get(),'')
        self.assertIsNone(self.form._login_memory_key)
        self.assertFalse(self.form._password_autofilled)
        self.form.saved_account_choice.set.assert_not_called()

    def test_destination_change_after_widget_destruction_still_clears_secret(self):
        self.form.saved_account_choice.winfo_exists.return_value=False
        self.form._clear_endpoint_credentials('changed')
        self.assertEqual(self.form.password.get(),'')
        self.assertEqual(self.form.account.get(),'')
        self.assertIsNone(self.form._loaded_identity)
        self.assertEqual(self.form.status.get(),'changed')
        self.form.saved_account_choice.set.assert_not_called()

    def test_tcl_teardown_during_label_update_does_not_interrupt_invalidation(self):
        import tkinter as tk
        for operation in ('winfo_exists','set'):
            with self.subTest(operation=operation):
                form=Form()
                getattr(form.saved_account_choice,operation).side_effect=tk.TclError('destroyed fixture')
                form.account.set('different-account')
                form.login_identity_changed()
                self.assertEqual(form.password.get(),'')
                self.assertIsNone(form._login_memory_key)

    def test_live_widget_still_receives_identity_change_label(self):
        self.form.account.set('different-account')
        self.form.login_identity_changed()
        self.form.saved_account_choice.set.assert_called_once()

    def test_same_id_and_name_new_endpoint_updates_target_and_drops_form_credentials(self):
        self.refresh([NEW])
        self.assertEqual((self.form.host.get(),self.form.port.get()),('new.example','17000'))
        self.assertEqual(self.form._line_endpoint,('new.example','17000'))
        self.assertEqual(self.form.display_lines[self.form.line_display.get()],NEW)
        self.assertEqual((self.form.account.get(),self.form.password.get()),('',''))
        self.assertFalse(self.form.remember_password.get())
        self.assertIsNone(self.form._login_memory_key);self.assertIsNone(self.form._loaded_identity)
        with patch('wlre.ui.login_controller.login_memory.load') as load:
            self.form.restore_remembered_password()
        load.assert_not_called()

    def test_new_port_alone_is_new_destination_even_for_typed_password(self):
        self.form._password_autofilled=False
        self.refresh([dict(OLD,port=17001)])
        self.assertEqual(self.form.port.get(),'17001')
        self.assertEqual(self.form.password.get(),'')

    def test_same_name_new_id_is_not_same_server(self):
        self.refresh([dict(NEW,id=102)])
        self.assertEqual(self.form.server_line.get(),server_lines.CUSTOM)
        self.assertEqual(self.form.host.get(),OLD['host'])
        self.assertEqual(self.form._selected_line_id,0)
        self.assertEqual(self.form.account.get(),'');self.assertEqual(self.form.password.get(),'')

    def test_removed_official_line_becomes_explicit_custom_without_saved_secrets(self):
        self.refresh([])
        self.assertEqual(self.form.server_line.get(),server_lines.CUSTOM)
        self.assertEqual(self.form.password.get(),'')
        self.assertIsNone(self.form._login_memory_key)

    def test_rename_with_same_full_endpoint_keeps_credentials_bound(self):
        self.refresh([dict(OLD,name='地球一線新名稱')])
        self.assertEqual(self.form.server_line.get(),'地球一線新名稱')
        self.assertEqual(self.form.password.get(),'fixture-password')
        self.assertEqual(self.form._login_memory_key,'old-key')

    def test_stale_name_cannot_relabel_custom_address_as_new_official_target(self):
        self.form._selected_line_id=0;self.form._line_endpoint=None
        self.form.host.set('manual.example');self.form.port.set('')
        self.refresh([NEW])
        self.assertEqual((self.form.host.get(),self.form.port.get()),('manual.example',''))
        self.assertEqual(self.form.server_line.get(),server_lines.CUSTOM)
        self.assertEqual(self.form.password.get(),'fixture-password')

    def test_explicit_destination_change_clears_typed_and_remembered_credentials(self):
        self.form.line_choices[NEW['name']]=NEW
        self.form.line_catalog=[NEW]
        self.form._password_autofilled=False
        self.form.select_server_line()
        self.assertEqual(self.form.host.get(),NEW['host'])
        self.assertEqual(self.form.password.get(),'')
        self.assertEqual(self.form.account.get(),'')

    def test_loading_old_saved_endpoint_does_not_rebind_its_password_to_updated_server(self):
        record=dict(OLD,host=OLD['host'],port=OLD['port'],line_id=101,line_name=OLD['name'],
                    key='old-key',account='fixture-account',password='fixture-password',
                    remember_password=True,password_error=False)
        self.form.line_catalog=[NEW]
        with patch('wlre.ui.login_controller.login_memory.load',return_value=record), \
             patch('wlre.ui.login_controller.login_memory.list_entries',return_value=[]), \
             patch('wlre.ui.login_controller.server_lines.load',return_value=[NEW]), \
             patch('wlre.ui.login_controller.server_lines.status_label',return_value='fixture'):
            self.form.load_saved_login('old-key')
        self.assertEqual(self.form.host.get(),NEW['host'])
        self.assertEqual(self.form.password.get(),'')
        self.assertIsNone(self.form._login_memory_key)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires Tk display')
class EndpointConnectTests(unittest.TestCase):
    def test_identity_callback_with_real_destroyed_combobox(self):
        import tkinter as tk
        from tkinter import ttk
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        form=Form();form.saved_account_choice=ttk.Combobox(root)
        form.saved_account_choice.destroy()
        form.account.set('different-account')
        form.login_identity_changed()
        self.assertEqual(form.password.get(),'')
        self.assertIsNone(form._login_memory_key)
        form._clear_endpoint_credentials('destination changed')
        self.assertEqual(form.account.get(),'')

    def test_connect_uses_refreshed_destination_only_after_credentials_are_reentered(self):
        import tkinter as tk
        from gui_support import isolate_gui_background_checks
        from wlre.ui.gui import App
        isolate_gui_background_checks(self)
        root=tk.Tk()
        def cleanup():
            for job in root.tk.call('after','info'): root.tk.call('after','cancel',job)
            root.destroy()
        self.addCleanup(cleanup)
        with patch('wlre.ui.version_gate_controller.VersionGateController.start_version_check'):
            app=App(root)
        app._memory_restoring=True
        app.host.set(OLD['host']);app.port.set(str(OLD['port']))
        app.account.set('old-account');app.password.set('old-secret')
        app._memory_restoring=False
        app._selected_line_id=101;app._line_endpoint=(OLD['host'],str(OLD['port']))
        app.server_line.set(OLD['name']);app.line_catalog=[OLD]
        with patch('wlre.ui.login_controller.server_lines.load',return_value=[NEW]), \
             patch('wlre.ui.login_controller.login_memory.list_entries',return_value=[]):
            app.refresh_server_lines()
        app.profile={'fixture':True}
        with patch.object(app,'can_login_after_version_check',return_value=True), \
             patch.object(app,'activate_account_settings'), \
             patch.object(app,'save_saved_login',return_value=True), \
             patch('wlre.ui.gui.messagebox.showinfo'), \
             patch('wlre.ui.gui.run_client') as client, \
             patch.object(app,'background',side_effect=lambda work:work() or True):
            app.connect();client.assert_not_called()
            app.account.set('new-account');app.password.set('new-secret')
            app.connect()
        self.assertEqual(client.call_args.args[:2],('new.example',17000))
        self.assertEqual(client.call_args.kwargs['account'],'new-account')
        self.assertEqual(client.call_args.kwargs['password'],'new-secret')
