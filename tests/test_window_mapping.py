"""Native mapping must settle without running the scheduled startup worker."""
import _tkinter
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.ui.window_layout import wait_for_widget_mapping


class WindowMappingTests(unittest.TestCase):
    def test_idle_geometry_is_not_mistaken_for_native_mapping(self):
        events = []
        widget = SimpleNamespace(update_idletasks=Mock(), mapped=False)

        def dooneevent(flags):
            events.append(flags)
            # Model native Map/Configure delivery after several WM events.
            widget.mapped = len(events) == 3
            return 1

        widget.tk = SimpleNamespace(dooneevent=dooneevent)
        widget.winfo_ismapped = lambda: widget.mapped
        wait_for_widget_mapping(widget)
        self.assertTrue(widget.mapped)
        self.assertEqual(len(events), 3)
        for flags in events:
            self.assertTrue(flags & _tkinter.DONT_WAIT)
            self.assertTrue(flags & _tkinter.WINDOW_EVENTS)
            self.assertTrue(flags & _tkinter.IDLE_EVENTS)
            self.assertFalse(flags & _tkinter.TIMER_EVENTS)
            self.assertFalse(flags & _tkinter.FILE_EVENTS)

    def test_unmapped_widget_fails_after_deadline_not_false_success(self):
        widget = SimpleNamespace(update_idletasks=Mock(),
                                 winfo_ismapped=lambda: False,
                                 tk=SimpleNamespace(dooneevent=Mock(return_value=0)))
        with (patch('time.monotonic', side_effect=[10, 10, 10.5, 11]),
              patch('time.sleep') as sleep):
            with self.assertRaisesRegex(RuntimeError, 'was not mapped within 1 seconds'):
                wait_for_widget_mapping(widget, timeout=1)
        self.assertEqual(widget.tk.dooneevent.call_count, 2)
        self.assertEqual(sleep.call_count, 2)

    def test_already_mapped_widget_does_not_pump_native_events(self):
        widget = SimpleNamespace(update_idletasks=Mock(),
                                 winfo_ismapped=lambda: True,
                                 tk=SimpleNamespace(dooneevent=Mock()))
        wait_for_widget_mapping(widget)
        widget.tk.dooneevent.assert_not_called()


class NativeWindowMappingTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        def close():
            for job in self.root.tk.call('after', 'info'):
                self.root.tk.call('after', 'cancel', job)
            self.root.destroy()
        self.addCleanup(close)

    def test_withdrawn_dashboard_and_login_map_without_startup_timers(self):
        self.root.withdraw()
        panel = tk.Frame(self.root)
        panel.pack()
        login = tk.Toplevel(self.root)
        label = tk.Label(login, text='Offline login policy')
        label.pack()
        login.withdraw()
        fired = []
        self.root.after(0, lambda: fired.append('startup'))

        self.root.deiconify()
        wait_for_widget_mapping(panel)
        self.assertTrue(panel.winfo_ismapped())
        self.assertEqual(login.state(), 'withdrawn')
        self.assertEqual(fired, [])

        self.root.withdraw()
        login.deiconify()
        wait_for_widget_mapping(label)
        self.assertTrue(label.winfo_ismapped())
        self.assertEqual(self.root.state(), 'withdrawn')
        self.assertEqual(fired, [])

    def test_real_hidden_widget_times_out_without_showing_it(self):
        self.root.withdraw()
        panel = tk.Frame(self.root)
        panel.pack()
        with self.assertRaisesRegex(RuntimeError, 'was not mapped'):
            wait_for_widget_mapping(panel, timeout=0.02)
        self.assertEqual(self.root.state(), 'withdrawn')

    def test_entry_smoke_keeps_real_startup_and_network_callbacks_unrun(self):
        import WLRE_Client
        # smoke_test_gui owns its own Tcl interpreter.
        self.doCleanups()
        with (patch('wlre.ui.version_gate_controller.prepare_on_launch') as prepare,
              patch('wlre.ui.version_gate_controller.run_prelogin_check') as official,
              patch('wlre.ui.version_gate_controller.check_lala_release') as release):
            self.assertEqual(WLRE_Client.smoke_test_gui(), 0)
        prepare.assert_not_called()
        official.assert_not_called()
        release.assert_not_called()
