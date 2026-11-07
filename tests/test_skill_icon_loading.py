"""Slow disk/image decoding must not block Tk or outlive the window."""
import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from unittest.mock import Mock, patch
from PIL import Image
from wlre.ui.skill_icons import SkillIcons


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.master = Mock()
        self.master.after.return_value = 'timer'
        self.ready = Mock()
        self.executor = Mock()
        self.future = Future()
        self.executor.submit.return_value = self.future
        self.icons = SkillIcons(self.master, self.ready, self.executor)

    def tearDown(self):
        self.icons.close()

    def test_get_only_queues_work_and_deduplicates(self):
        with patch('wlre.ui.skill_icons.skill_icon_image') as decode:
            self.assertIsNone(self.icons.get({'GId':10001}))
            self.assertIsNone(self.icons.get({'GId':10001}))
            decode.assert_not_called()
        self.executor.submit.assert_called_once()
        self.ready.assert_not_called()

    def test_photo_creation_happens_only_during_tk_poll(self):
        self.icons.get({'GId':10001},40)
        pixels = Image.new('RGBA',(40,40))
        self.future.set_result(pixels)
        self.ready.assert_not_called()
        with patch('wlre.ui.skill_icons.ImageTk.PhotoImage',return_value='photo') as photo:
            self.icons._poll()
            photo.assert_called_once()
        self.assertEqual(self.icons.get({'GId':10001},40),'photo')
        self.ready.assert_called_once_with(('icon_sk10001s',40),'photo')

    def test_failure_is_cached_without_retry_storm(self):
        self.icons.get({'GId':65535})
        self.future.set_result(None)
        self.icons._poll()
        for _ in range(10):self.assertIsNone(self.icons.get({'GId':65535}))
        self.executor.submit.assert_called_once()

    def test_close_cancels_pending_and_never_calls_tk_for_late_result(self):
        self.future.set_running_or_notify_cancel()
        self.icons.get({'GId':10001})
        self.icons.close()
        pixels=Image.new('RGBA',(40,40))
        with patch('wlre.ui.skill_icons.ImageTk.PhotoImage') as photo:
            self.future.set_result(pixels)
            self.icons._poll()
            photo.assert_not_called()
        self.ready.assert_not_called()
        self.master.after_cancel.assert_called_once()

    def test_tk_work_is_bounded_per_tick(self):
        futures=[]
        for _ in range(9):
            future=Future();future.set_result(None);futures.append(future)
        self.executor.submit.side_effect=futures
        for gid in range(1,10):self.icons.get({'GId':gid})
        self.icons._poll()
        self.assertEqual(self.ready.call_count,4)
        self.assertEqual(len(self.icons.pending),5)

    def test_actual_decoder_runs_off_calling_thread(self):
        ui_thread=threading.get_ident();called=[];gate=threading.Event()
        def decode(*args):
            called.append(threading.get_ident());gate.wait(2);return None
        with ThreadPoolExecutor(max_workers=1) as executor:
            loader=SkillIcons(self.master,executor=executor)
            try:
                with patch('wlre.ui.skill_icons.skill_icon_image',side_effect=decode):
                    loader.get({'GId':10001})
                    self.assertEqual(len(loader.pending),1)
                    gate.set()
                    next(iter(loader.pending.values())).result(timeout=2)
                self.assertNotEqual(called,[ui_thread])
            finally:
                gate.set();loader.close()
