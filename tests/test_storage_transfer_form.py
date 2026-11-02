"""Actual storage typing/clicks must not be replaced by mocked modal results."""
from copy import deepcopy
import os
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_room_storage_transfer import ready
from wlre.ui.resource_view import ResourceView
from wlre.ui.storage_transfer_form import transfer_command
from wlre.ui.theme import install


class StorageInputValidationTests(unittest.TestCase):
    def test_quantities_fail_before_any_packet_is_sent(self):
        snap=ready().snapshot();item=snap['room_storage']['materials']['items']['300']
        for value in ('','abc','0','-1','1.5','1001','65536','９','1'*1000):
            with self.subTest(value=value[:10]),self.assertRaises(ValueError):
                transfer_command(snap,'materials','withdraw',300,item,value)

    def test_current_revisions_are_used_but_replaced_identity_is_rejected(self):
        snap=ready().snapshot();item=deepcopy(snap['inventory']['items']['3'])
        snap['inventory']['revision']=100;snap['room_storage']['revision']=200
        command=transfer_command(snap,'materials','deposit',3,item,' 4 ')
        self.assertEqual((command['bag_revision'],command['storage_revision']),(100,200))
        snap['inventory']['items']['3']['serial']+=1
        with self.assertRaisesRegex(ValueError,'物品已變更'):
            transfer_command(snap,'materials','deposit',3,item,'4')


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop or Xvfb')
class StorageInputWindowTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.geometry('1280x800');install(self.root)
        self.app=SimpleNamespace(root=self.root,snapshot=ready().snapshot(),live_active=True,send=Mock(return_value=True))
        self.view=ResourceView(self.app);self.root.update();self.view.window.focus_force()
        self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)

    def tearDown(self):
        errors=self.errors[:]
        for job in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',job)
        self.root.destroy()
        self.assertFalse(errors,errors)

    def open_form(self):
        self.view.remote_materials.selection_set('bag300')
        self.view.storage_buttons[-1][0].invoke();self.root.update()
        return self.view.storage_form

    def test_real_entry_and_confirm_remain_operable_without_modal_window_or_grab(self):
        windows=[w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)]
        form=self.open_form()
        self.assertTrue(form.winfo_ismapped())
        self.assertEqual(windows,[w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)])
        self.assertIsNone(self.root.grab_current())
        self.assertIs(self.root.focus_get(),form.entry)
        form.entry.delete(0,'end')
        form.entry.event_generate('<KeyPress>',keysym='4');self.root.update()
        self.assertEqual(form.entry.get(),'4')
        form.confirm.event_generate('<ButtonPress-1>',x=8,y=8)
        form.confirm.event_generate('<ButtonRelease-1>',x=8,y=8);self.root.update()
        sent=self.app.send.call_args.args[0]
        self.assertEqual((sent['action'],sent['index'],sent['count']),('withdraw',300,4))
        form.submit();form.confirm.invoke()
        self.app.send.assert_called_once()
        self.assertTrue(all(str(b.cget('state'))=='disabled' for b,_ in self.view.storage_buttons))

    def test_enter_submits_and_escape_cancels_without_sending(self):
        form=self.open_form()
        form.entry.event_generate('<Escape>');self.root.update()
        self.assertFalse(form.winfo_ismapped());self.app.send.assert_not_called()
        form=self.open_form();form.count.set('8')
        form.entry.event_generate('<Return>');self.root.update()
        self.assertEqual(self.app.send.call_args.args[0]['count'],8)

    def test_inline_form_keeps_all_twenty_four_storage_cells_visible(self):
        self.view.tabs.select(1)
        form=self.open_form();grid=self.view.remote_garage
        self.assertEqual((grid.columns,grid.row_count,grid.page_size),(6,4,24))
        for cell in grid.cells:
            frame=cell['frame']
            self.assertTrue(frame.winfo_ismapped())
            self.assertGreaterEqual(frame.winfo_height(),24)
            self.assertLessEqual(frame.winfo_y()+frame.winfo_height(),grid.board.winfo_height())
            self.assertLessEqual(frame.winfo_x()+frame.winfo_width(),grid.board.winfo_width())
        self.assertLessEqual(grid.winfo_rooty()+grid.winfo_height(),form.winfo_rooty())
        self.view.cancel_storage();self.root.update()
        self.assertTrue(grid.card.winfo_ismapped())

    def test_invalid_input_shows_inline_error_and_can_be_corrected(self):
        form=self.open_form();form.count.set('abc');form.confirm.invoke();self.root.update()
        self.assertIn('整數',form.message.get());self.app.send.assert_not_called()
        self.assertTrue(form.winfo_ismapped());self.assertIsNone(self.root.grab_current())
        form.count.set('4');form.confirm.invoke();self.app.send.assert_called_once()

    def test_latest_snapshot_is_checked_after_user_enters_quantity(self):
        form=self.open_form();form.count.set('4')
        snap=deepcopy(self.app.snapshot);snap['inventory']['revision']=10;snap['room_storage']['revision']=20
        self.app.snapshot=snap;self.view.set_state(snap);form.confirm.invoke()
        sent=self.app.send.call_args.args[0]
        self.assertEqual((sent['bag_revision'],sent['storage_revision']),(10,20))

    def test_changed_stock_or_disconnection_keeps_form_and_does_not_send(self):
        form=self.open_form();form.count.set('4')
        self.app.snapshot['room_storage']['materials']['items']['300']['count']=2
        form.confirm.invoke();self.app.send.assert_not_called()
        self.assertIn('不足',form.message.get())
        self.app.live_active=False;form.confirm.invoke()
        self.assertIn('連線已結束',form.message.get());self.app.send.assert_not_called()

    def test_maximum_and_send_failure_or_rejection_allow_explicit_correction(self):
        form=self.open_form();form.maximum.invoke()
        self.assertEqual(form.count.get(),'1000')
        self.app.send.return_value=False;form.count.set('4');form.confirm.invoke()
        self.assertFalse(form.submitted);self.assertIn('尚未送出',form.message.get())
        self.app.send.return_value=True;form.confirm.invoke()
        self.assertTrue(form.submitted)
        self.view.storage_rejected('伺服器事件尚未結束')
        self.assertFalse(form.submitted);self.assertIsNone(self.view.storage_queued_revision)
        self.assertIn('事件尚未結束',form.message.get())


if __name__=='__main__':unittest.main()
