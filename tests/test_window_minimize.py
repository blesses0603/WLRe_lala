"""Window lifecycle contracts, including queued Map events during iconify."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

from wlre.ui.theme import GlassTheme


class WindowMinimizeTests(unittest.TestCase):
    def setUp(self):
        self.theme = GlassTheme.__new__(GlassTheme)
        self.theme.windows_chrome = Mock()
        self.window = Mock()
        self.window.winfo_exists.return_value = True
        self.window.state.return_value = 'normal'
        self.window._glass_restore = False
        # A native handle must not select the old synchronous ctypes path.
        self.window._glass_hwnd = 123

    def test_minimize_uses_tk_even_with_native_handle(self):
        self.theme.minimize(self.window)
        self.assertTrue(self.window._glass_restore)
        self.assertEqual(self.window.method_calls, [call.winfo_exists(),
            call.state(), call.tk.call('tk', 'windowingsystem'),
            call.overrideredirect(False), call.iconify()])

    def test_queued_map_while_iconic_does_not_restore_chrome(self):
        self.theme.minimize(self.window)
        self.window.state.return_value = 'iconic'
        self.theme.restore(self.window, SimpleNamespace(widget=self.window))
        callback = self.window.after_idle.call_args.args[0]
        callback()
        self.assertTrue(self.window._glass_restore)
        self.theme.windows_chrome.assert_not_called()
        self.window.state.return_value = 'normal'
        self.theme.restore(self.window, SimpleNamespace(widget=self.window))
        self.window.after_idle.call_args.args[0]()
        self.assertFalse(self.window._glass_restore)
        self.window.overrideredirect.assert_called_with(True)
        self.theme.windows_chrome.assert_called_once_with(self.window)
        # Further Map notifications do not toggle borderless mode again.
        self.window.overrideredirect.reset_mock()
        self.theme.finish_restore(self.window)
        self.window.overrideredirect.assert_not_called()

    def test_child_map_and_destroyed_window_are_ignored(self):
        self.theme.restore(self.window, SimpleNamespace(widget=object()))
        self.window.after_idle.assert_not_called()
        self.window.winfo_exists.return_value = False
        self.theme.finish_restore(self.window)
        self.theme.minimize(self.window)
        self.window.iconify.assert_not_called()
        self.theme.windows_chrome.assert_not_called()

    def test_already_hidden_window_is_not_minimized_again(self):
        for state in ('iconic', 'withdrawn'):
            self.window.state.return_value = state
            self.theme.minimize(self.window)
        self.window.overrideredirect.assert_not_called()
        self.window.iconify.assert_not_called()

    def test_aqua_keeps_native_resizing_policy_during_minimize_and_restore(self):
        self.window.tk.call.return_value = 'aqua'
        self.theme.minimize(self.window)
        self.window.iconify.assert_called_once()
        self.assertFalse(self.window._glass_restore)
        self.theme.finish_restore(self.window)
        self.window.overrideredirect.assert_not_called()
        self.window.resizable.assert_not_called()
