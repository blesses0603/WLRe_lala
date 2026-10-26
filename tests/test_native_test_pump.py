"""原生測試迴圈實際執行 callback、銷毀與清理，沒有模擬 Tk。"""
import os
import sys
import tkinter as tk
import unittest

from _tk_native_pump import assert_normal_display, create_root, pump_native_events


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin',
                     'Requires native Tk or Xvfb')
class NativeTestPumpTests(unittest.TestCase):
    def test_real_callbacks_execute_and_private_quit_timer_is_released(self):
        root = create_root()
        self.addCleanup(root.destroy)
        root.withdraw()
        fired = []
        root.after(1, lambda: fired.append(True))
        pump_native_events(root)
        self.assertEqual(fired, [True])
        self.assertFalse(root.tk.call('after', 'info'))
        self.assertIsInstance(root, tk.Tk)

    def test_callback_can_destroy_root_without_leaving_native_loop_running(self):
        root = create_root()
        root.withdraw()
        root.after(1, root.destroy)
        pump_native_events(root)
        self.assertFalse(root._test_event_pumping)

    def test_regular_update_keeps_actual_callback_semantics(self):
        root = create_root()
        self.addCleanup(root.destroy)
        root.withdraw()
        fired = []
        root.after(0, lambda: fired.append(True))
        root.update()
        self.assertEqual(fired, [True])

    def test_display_assertion_rejects_hidden_window_and_accepts_real_fixed_window(self):
        root = create_root()
        self.addCleanup(root.destroy)
        root.withdraw()
        with self.assertRaises(AssertionError):
            assert_normal_display(self, root)
        root.minsize(160, 120)
        root.maxsize(160, 120)
        root.resizable(False, False)
        root.deiconify()
        root.update()
        assert_normal_display(self, root)
