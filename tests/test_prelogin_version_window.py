"""Dedicated version-check window must use official server results exclusively."""
import os
import tkinter as tk
import unittest
from unittest.mock import patch

from wlre.ui.gui import App
from wlre.ui.version_gate_controller import VersionGateController


def official_result(main="1262", data="1262", status="version_identifiers_match"):
    versions = {"MainPackage": main, "DataPackage": data}
    return {
        "blocked": status == "blocked",
        "status": status,
        "message": "官方更新，請等待 LaLa 更新" if status == "blocked" else "官方線上版本檢測結果",
        "remote": {
            "status": "resources_changed" if status == "blocked" else
                      "same_resources" if status == "version_identifiers_match" else "unverified",
            "packages": {
                name: {
                    "remote": value if status != "unverified" else None,
                    "comparison": "newer" if status == "blocked" and value != "1262" else
                                  "unverified" if status == "unverified" else "same",
                }
                for name, value in versions.items()
            },
        },
    }


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt",
                     "需要桌面顯示環境")
class PreloginVersionWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.patcher = patch.object(VersionGateController, "start_version_check")
        self.patcher.start()
        self.app = App(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.patcher.stop()
        if self.root.winfo_exists():
            for job in self.root.tk.call("after", "info"):
                self.root.tk.call("after", "cancel", job)
            self.root.destroy()

    def deliver(self, data, generation=1):
        self.app._version_gate_generation = generation
        self.app._version_gate_messages.put((generation, data))
        self.app.drain_version_checks()
        self.root.update_idletasks()

    def test_version_screen_before_account_fields(self):
        self.assertTrue(self.app.version_window.winfo_ismapped())
        self.assertEqual(self.app.login_window.state(), "withdrawn")
        self.assertEqual(str(self.app.connect_button.cget("state")), "disabled")
        self.assertIn("1262", self.app.version_window.winfo_children()[0].winfo_children()[1].cget("text"))
        self.assertNotIn("選擇遊戲目錄",
                         [str(x.cget("text")) for x in self.app.version_window.winfo_children()
                          if "text" in x.keys()])

    def test_confirmed_remote_change_blocks(self):
        self.deliver(official_result("1275", "1262", "blocked"))
        self.assertTrue(self.app._version_continue_button.instate(["disabled"]))
        self.assertIn("等待 LaLa 更新", self.app._version_heading.get())
        self.assertIn("1275", self.app._version_main.get())
        self.assertEqual(self.app.login_window.state(), "withdrawn")
        self.assertFalse(self.app._version_gate_entry_approved)

    def test_confirmed_online_1262_requires_explicit_continue(self):
        self.deliver(official_result())
        self.assertEqual(self.app.login_window.state(), "withdrawn")
        self.assertEqual(self.app._version_continue_button.cget("text"), "進入登入畫面")
        self.app.continue_to_login()
        self.assertEqual(self.app.version_window.state(), "withdrawn")
        self.assertNotEqual(self.app.login_window.state(), "withdrawn")
        self.assertTrue(self.app._version_gate_entry_approved)

    def test_unknown_state_requires_explicit_acknowledgement(self):
        self.deliver(official_result(status="unverified"))
        self.assertEqual(self.app.login_window.state(), "withdrawn")
        self.assertEqual(self.app._version_continue_button.cget("text"),
                         "了解風險，繼續登入")
        self.assertIn("無法驗證", self.app._version_main.get())
        self.app.continue_to_login()
        self.assertNotEqual(self.app.login_window.state(), "withdrawn")

    def test_reopen_revokes_previous_approval(self):
        self.deliver(official_result(status="unverified"))
        self.app.continue_to_login()
        self.app.reopen_version_check()
        self.assertFalse(self.app._version_gate_entry_approved)
        self.assertTrue(self.app.version_window.winfo_ismapped())
        self.assertEqual(self.app.login_window.state(), "withdrawn")

    def test_stale_background_result_cannot_override_newer_check(self):
        self.app._version_gate_generation = 2
        self.app._version_gate_messages.put((1, official_result("1275", "1262", "blocked")))
        self.app._version_gate_messages.put((2, official_result(status="unverified")))
        self.app.drain_version_checks()
        self.assertEqual(self.app.version_gate_state, "ready")
        self.assertEqual(self.app.version_gate_text.get(), "官方線上版本檢測結果")


if __name__ == "__main__":
    unittest.main()
