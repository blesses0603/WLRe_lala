"""Dedicated version-check window must use official server results exclusively."""
import os
import tkinter as tk
import unittest
from unittest.mock import patch
from tkinter import ttk

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
        self.assertEqual(self.app._version_baseline.get(), "1262")
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

    def test_unknown_source_exposes_failure_stage(self):
        response = official_result(status="unverified")
        response["remote"]["failed_stage"] = "ResourcePath_PC.dat"
        response["remote"]["reason"] = "DNS 無法解析官方網域"
        self.deliver(response)
        self.assertIn("ResourcePath_PC.dat", self.app._version_remote.get())
        self.assertIn("DNS", self.app._version_remote.get())

    def test_action_buttons_remain_visible_with_long_status(self):
        # A high-DPI viewport must not swallow the last action row.
        self.app.version_gate_text.set("官方版本回應尚待驗證。" * 35)
        self.app._lala_release_text.set("正在核對 GitHub 正式發行版本。" * 35)
        self.root.update()
        window = self.app.version_window
        button = self.app._version_continue_button
        self.assertTrue(button.winfo_ismapped())
        window_bottom = window.winfo_rooty() + window.winfo_height()
        button_bottom = button.winfo_rooty() + button.winfo_height()
        self.assertLessEqual(button_bottom, window_bottom)
        self.assertFalse(hasattr(self.app, "_version_canvas"))
        self.assertTrue(hasattr(self.app, "_version_body"))
        self.assertFalse(any(
            isinstance(child, (tk.Canvas, ttk.Scrollbar))
            for child in self.app.version_window.winfo_children()
        ))

    def test_compact_version_window_has_no_scrollbars_or_blank_canvas(self):
        self.deliver(official_result("1275", "1275", "blocked"))
        self.root.update()
        window = self.app.version_window
        widgets = []

        def collect(parent):
            for child in parent.winfo_children():
                widgets.append(child)
                collect(child)

        collect(window)
        self.assertFalse(any(isinstance(w, tk.Canvas) for w in widgets))
        self.assertFalse(any(isinstance(w, __import__("tkinter").ttk.Scrollbar)
                             for w in widgets))
        self.assertLessEqual(window.winfo_height(), 480)
        self.assertTrue(self.app._version_continue_button.winfo_ismapped())
        self.assertTrue(self.app._lala_download_button.winfo_ismapped())
        self.assertTrue(self.app._lala_open_button.winfo_ismapped())
        self.assertIn("1275", self.app._version_main.get())
        self.assertIn("1275", self.app._version_data.get())
        # Check the darker window and single-pane cards within the existing
        # app instance, rather than creating two extra Tk interpreters on
        # Windows. Tk widgets must only be cleaned up by their owning thread.
        self.assertAlmostEqual(window._glass_background_dim, 0.79)
        self.assertTrue(self.app._version_resource_panel._section_outline)
        self.assertTrue(self.app._version_release_panel._section_outline)
        self.assertEqual(
            self.app._version_resource_panel._surface_fill, (6, 20, 36, 226))
        self.assertEqual(
            self.app._version_release_panel._surface_fill, (6, 20, 36, 226))
        self.assertFalse(any(isinstance(w, ttk.LabelFrame) for w in widgets))
        self.assertEqual(
            sum(bool(getattr(w, "_section_outline", False)) for w in widgets),
            3)
        self.assertTrue(self.app._version_alert_panel._section_outline)
        self.assertEqual(self.app._version_alert_panel._surface_fill,
                         (9, 27, 46, 235))
        self.assertTrue(self.app._version_alert_heading_label.winfo_ismapped())
        self.assertTrue(self.app._version_alert_message_label.winfo_ismapped())
        # The two duplicate labels highlighted in the user's screenshot
        # must no longer appear in the version dialog.
        visible_static_text = [
            str(w.cget("text")) for w in widgets
            if isinstance(w, ttk.Label) and not str(w.cget("textvariable"))
        ]
        self.assertNotIn("官方資源版本檢測", visible_static_text)
        self.assertFalse(any("線上取得 DataVer，再比對" in label
                             for label in visible_static_text))
        self.assertTrue(
            self.app._version_alert_heading_label.cget("style")
            .endswith("VersionAlertHeading.TLabel"))
        self.assertTrue(
            self.app._version_alert_message_label.cget("style")
            .endswith("VersionAlertMessage.TLabel"))
        style = ttk.Style(self.root)
        self.assertIn("-20", str(style.lookup("VersionAlertHeading.TLabel", "font")))
        self.assertIn("-16", str(style.lookup("VersionAlertMessage.TLabel", "font")))
        self.assertFalse(hasattr(self.app.root, "_glass_background_dim"))

    def test_compact_window_data_above_pinned_footer(self):
        self.deliver(official_result("1275", "1275", "blocked"))
        self.root.update()
        body = self.app._version_body
        button = self.app._version_continue_button
        self.assertLess(body.winfo_rooty(), button.winfo_rooty())
        self.assertLessEqual(
            body.winfo_rooty() + body.winfo_height(),
            button.winfo_rooty())
        self.assertLessEqual(
            self.app._version_release_panel.winfo_rooty()
            + self.app._version_release_panel.winfo_height(),
            button.winfo_rooty())
        self.assertLess(
            self.app._version_alert_panel.winfo_rooty()
            + self.app._version_alert_panel.winfo_height(),
            self.app._version_resource_panel.winfo_rooty())
        self.assertGreater(
            self.app._version_alert_panel.winfo_height(), 55)

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
