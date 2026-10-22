"""Desktop version verification must be a separate screen before credentials."""
import os
import tkinter as tk
import unittest
from unittest.mock import patch

from wlre.ui.gui import App
from wlre.ui.version_gate_controller import VersionGateController


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt",
                     "需要桌面顯示環境")
class PreloginVersionWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.start_patcher = patch.object(VersionGateController, "start_version_check")
        self.start_patcher.start()
        self.app = App(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.start_patcher.stop()
        if self.root.winfo_exists():
            for job in self.root.tk.call("after", "info"):
                self.root.tk.call("after", "cancel", job)
            self.root.destroy()

    def deliver(self, data, generation=1):
        self.app._version_gate_generation = generation
        self.app._version_gate_messages.put((generation, data))
        self.app.drain_version_checks()
        self.root.update_idletasks()

    def test_only_version_window_visible_before_login(self):
        self.assertTrue(self.app.version_window.winfo_ismapped())
        self.assertEqual(self.app.login_window.state(), "withdrawn")
        self.assertEqual(str(self.app.connect_button.cget("state")), "disabled")
        self.assertIn("1262", self.app.version_window.winfo_children()[0].winfo_children()[1].cget("text"))

    def test_detected_change_stays_on_screen_and_blocks_login(self):
        self.deliver({
            "blocked": True, "status": "blocked",
            "message": "1275 已更新，禁止登入，請等待更新",
            "local": {"root": "/fake/game/yoo", "packages": {
                "MainPackage": {"version": "1275", "status": "changed"},
                "DataPackage": {"version": "1262", "status": "same"}}},
            "remote": {"status": "unverified"}
        })
        self.assertEqual(self.app.version_gate_state, "blocked")
        self.assertTrue(self.app._version_continue_button.instate(["disabled"]))
        self.assertIn("等待 LaLa 更新", self.app._version_heading.get())
        self.assertIn("1275", self.app._version_main.get())
        self.assertEqual(self.app.login_window.state(), "withdrawn")

    def test_unverified_requires_explicit_continue(self):
        self.deliver({
            "blocked": False, "status": "unverified",
            "message": "官方即時版號未知，本機沒有證實已更新",
            "local": {"root": None, "packages": {}},
            "remote": {"status": "unverified"}
        })
        self.assertEqual(self.app.login_window.state(), "withdrawn")
        self.assertEqual(self.app._version_continue_button.cget("text"),
                         "了解風險，繼續登入")
        with patch.object(self.app, "can_login_after_version_check", return_value=True):
            self.app.continue_to_login()
        self.assertEqual(self.app.version_window.state(), "withdrawn")
        self.assertNotEqual(self.app.login_window.state(), "withdrawn")

    def test_login_can_reopen_separate_version_check(self):
        self.deliver({
            "blocked": False, "status": "unverified",
            "message": "未知",
            "local": {"root": None, "packages": {}},
            "remote": {"status": "unverified"}
        })
        with patch.object(self.app, "can_login_after_version_check", return_value=True):
            self.app.continue_to_login()
        self.app.reopen_version_check()
        self.assertNotEqual(self.app.version_window.state(), "withdrawn")
        self.assertEqual(self.app.login_window.state(), "withdrawn")

    def test_stale_completed_check_cannot_override_latest_result(self):
        self.app._version_gate_generation = 2
        self.app._version_gate_messages.put((1, {"blocked": True, "message": "stale"}))
        self.app._version_gate_messages.put((2, {
            "blocked": False, "status": "unverified", "message": "current",
            "local": {"packages": {}}, "remote": {"status": "unverified"}}))
        self.app.drain_version_checks()
        self.assertEqual(self.app.version_gate_state, "ready")
        self.assertEqual(self.app.version_gate_text.get(), "current")


if __name__ == "__main__":
    unittest.main()
