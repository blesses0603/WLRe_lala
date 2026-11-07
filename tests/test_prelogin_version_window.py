"""Dedicated version-check window must use official server results exclusively."""

from gui_support import isolate_gui_background_checks
from test_background_version_observer import identity
import os
import time
import tkinter as tk
import unittest
from unittest.mock import ANY, patch
from tkinter import ttk

from wlre.ui.gui import App
from wlre.ui.version_gate_controller import VersionGateController
from wlre.ui.window_layout import wait_for_widget_mapping


_UNPATCHED_START_VERSION_CHECK = VersionGateController.start_version_check


def official_result(main="1262", data="1262", status="version_identifiers_match"):
    versions = {"MainPackage": main, "DataPackage": data}
    return {
        "runtime_identity": identity(),
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
        isolate_gui_background_checks(self)
        self.root = tk.Tk()
        self.patcher = patch.object(VersionGateController, "start_version_check")
        self.patcher.start()
        self.app = App(self.root)
        wait_for_widget_mapping(self.app.version_window)

    def tearDown(self):
        self.patcher.stop()
        if self.root.winfo_exists():
            for job in self.root.tk.call("after", "info"):
                self.root.tk.call("after", "cancel", job)
            self.root.destroy()

    def deliver(self, data, generation=1):
        self.app._version_gate_generation = generation
        self.app._version_gate_messages.put((generation, data, time.monotonic()))
        self.app.drain_version_checks()
        self.root.update_idletasks()

    def test_late_startup_timer_while_live_uses_nonmodal_notice(self):
        self.app.live_active = True
        errors = []
        self.root.report_callback_exception = lambda *args: errors.append(args)
        with (patch('wlre.ui.version_gate_controller.messagebox.showinfo',
                    side_effect=AssertionError('Timer must not open a modal')) as modal,
              patch('wlre.ui.version_gate_controller.prepare_on_launch') as prepare,
              patch('wlre.ui.version_gate_controller.run_prelogin_check') as verify):
            self.root.after(0, lambda: _UNPATCHED_START_VERSION_CHECK(self.app))
            self.root.update()
        modal.assert_not_called()
        prepare.assert_not_called()
        verify.assert_not_called()
        self.assertEqual(errors, [])
        self.assertTrue(self.app.live_active)
        self.assertIn('先安全中斷', self.app.version_gate_text.get())
        self.assertTrue(self.app._version_retry_button.instate(['disabled']))

    def test_direct_app_uses_same_window_for_preparation_official_check_and_login(self):
        original_window = self.app.version_window
        initial_windows = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        stages = []
        def prepare(*, progress):
            progress('bundle_item', {'completed': 8, 'total': 24})
            self.app.drain_version_checks()
            self.root.update_idletasks()
            stages.append(self.app._version_heading.get())
            self.assertIn('8 / 24', self.app.version_gate_text.get())
            self.assertEqual(self.app._version_progress._counts, (8, 24))
            self.assertTrue(self.app._version_continue_button.instate(['disabled']))
            self.assertEqual(self.app.login_window.state(), 'withdrawn')
            return {'status': 'verified_official'}
        def official(*, progress):
            progress('official_metadata', {})
            self.app.drain_version_checks()
            stages.append(self.app._version_heading.get())
            self.assertEqual(self.app._startup_phase, 'official')
            self.assertIsNone(self.app._version_progress._counts)
            self.assertEqual(self.app.login_window.state(), 'withdrawn')
            return official_result()
        with (patch('wlre.ui.version_gate_controller.prepare_on_launch', side_effect=prepare) as resource,
              patch('wlre.ui.version_gate_controller.run_prelogin_check', side_effect=official) as check,
              patch('wlre.ui.version_gate_controller.threading.Thread') as thread,
              patch.object(self.app, 'start_lala_release_check')):
            _UNPATCHED_START_VERSION_CHECK(self.app)
            thread.call_args.kwargs['target']()
            self.app.drain_version_checks()
        resource.assert_called_once()
        check.assert_called_once_with(progress=ANY)
        self.assertIn('收集', stages[0])
        self.assertIn('官方版本查詢', stages[1])
        self.assertIs(self.app.version_window, original_window)
        self.assertEqual(initial_windows,
                         [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)])
        self.assertEqual(self.app.version_gate_state, 'ready')
        self.assertEqual(self.app.login_window.state(), 'withdrawn')
        self.assertFalse(self.app._version_retry_button.instate(['disabled']))
        self.app.continue_to_login()
        self.assertEqual(original_window.state(), 'withdrawn')
        self.assertTrue(self.app._version_gate_entry_approved)

    def test_safe_close_keeps_window_responsive_and_blocks_all_entry(self):
        import threading
        entered, release = threading.Event(), threading.Event()
        def prepare(**kwargs):
            entered.set()
            release.wait(3)
            return {'status': 'verified_official'}
        with (patch('wlre.ui.version_gate_controller.prepare_on_launch', side_effect=prepare),
              patch('wlre.ui.version_gate_controller.run_prelogin_check') as check,
              patch.object(self.app, 'start_lala_release_check')):
            try:
                _UNPATCHED_START_VERSION_CHECK(self.app)
                self.assertTrue(entered.wait(2))
                self.app.close()
                self.root.update_idletasks()
                self.assertTrue(self.app.version_window.winfo_ismapped())
                self.assertFalse(self.app._closing)
                self.assertIn('安全結束', self.app._version_heading.get())
                self.assertTrue(self.app._version_retry_button.instate(['disabled']))
                self.assertTrue(self.app._version_continue_button.instate(['disabled']))
                self.assertFalse(self.app.can_login_after_version_check())
                self.assertEqual(self.app.login_window.state(), 'withdrawn')
            finally:
                release.set()
                self.assertTrue(self.app._version_worker_done.wait(3))
            check.assert_not_called()
            with patch.object(self.root, 'destroy') as destroy:
                self.app._finish_startup_close()
                destroy.assert_called_once()
                self.assertTrue(self.app._closing)

    def test_session_end_returns_account_login_without_automatic_version_popup(self):
        # All connection outcomes converge on the same session_finished event.
        for outcome in ('manual_disconnect', 'remote_disconnect', 'failed_connect'):
            with self.subTest(outcome=outcome):
                self.deliver(official_result())
                self.app.continue_to_login()
                self.app.live_active = True
                self.app.login_window.withdraw()
                self.app.start_version_check.reset_mock()
                self.app.events.put(('session_finished', None))
                App._poll_once(self.app)
                wait_for_widget_mapping(self.app.login_window)
                self.assertFalse(self.app.live_active)
                self.assertEqual(self.app.version_window.state(), 'withdrawn')
                self.assertTrue(self.app.login_window.winfo_ismapped())
                self.app.start_version_check.assert_not_called()
                self.assertTrue(self.app._version_gate_entry_approved)
                self.assertTrue(self.app.can_login_after_version_check())
                self.assertFalse(self.app.connect_button.instate(['disabled']))
                self.assertEqual(self.app.role_map, {})

    def test_expired_relogin_checks_on_login_click_not_on_disconnect(self):
        import time
        self.deliver(official_result())
        self.app.continue_to_login()
        self.app._observer_fresh_at = time.monotonic() - 301
        self.app.live_active = True
        self.app.start_version_check.reset_mock()
        self.app.events.put(('session_finished', None))
        App._poll_once(self.app)
        self.app.start_version_check.assert_not_called()
        self.assertEqual(self.app.version_window.state(), 'withdrawn')
        self.assertFalse(self.app.connect_button.instate(['disabled']))
        with (patch('wlre.ui.background_version_controller.threading.Thread') as thread,
              patch('wlre.ui.version_gate_controller.messagebox.showinfo'),
              patch('wlre.ui.gui.run_client') as client):
            self.app.connect()
        client.assert_not_called()
        self.assertEqual(thread.call_args.kwargs['name'], 'background-version-observer')
        self.assertNotEqual(self.app.login_window.state(), 'withdrawn')
        self.assertEqual(self.app.version_window.state(), 'withdrawn')
        self.assertTrue(self.app._version_gate_entry_approved)
        self.assertEqual(self.app.version_gate_state, 'ready')
        self.app.start_version_check.assert_not_called()

    def test_inconsistent_result_never_gains_approval_after_disconnect(self):
        self.deliver(official_result())
        self.app.continue_to_login()
        self.app._version_gate_result['remote']['status'] = 'unverified'
        self.app.live_active = True
        self.app.start_version_check.reset_mock()
        self.app.events.put(('session_finished', None))
        App._poll_once(self.app)
        self.assertEqual(self.app.version_window.state(), 'withdrawn')
        self.app.start_version_check.assert_not_called()
        self.assertTrue(self.app.connect_button.instate(['disabled']))
        with (patch('wlre.ui.version_gate_controller.messagebox.showwarning'),
              patch('wlre.ui.gui.run_client') as client):
            self.app.connect()
        client.assert_not_called()
        self.assertNotEqual(self.app.version_window.state(), 'withdrawn')

    def test_runtime_row_label_is_not_forced_into_narrow_character_width(self):
        self.root.update_idletasks()
        label = self.app._version_resource_labels[3]
        self.assertEqual(label.cget('text'), '目前 Runtime 資源版本')
        self.assertIn(str(label.cget('width')), ('', '0'))
        self.assertGreaterEqual(label.winfo_width(), label.winfo_reqwidth())

    def test_login_reloads_official_server_database_after_startup_preparation(self):
        row = {'id': 101, 'name': '官方測試｜1線 (101)',
               'host': '8.8.8.8', 'port': 16988}
        self.app.line_catalog = []
        self.app.host.set(row['host'])
        self.app.port.set(str(row['port']))
        self.app.server_list_status_label.configure(text='先前尚無官方清單')
        with (patch('wlre.ui.login_controller.server_lines.load', return_value=[row]) as load,
              patch('wlre.ui.login_controller.server_lines.status_label',
                    return_value='官方伺服器清單 · 已更新')):
            self.app.show_login()
        load.assert_called()
        self.assertEqual(self.app.line_catalog, [row])
        self.assertEqual(self.app.line_choices[row['name']], row)
        self.assertEqual(self.app.server_list_status_label.cget('text'),
                         '官方伺服器清單 · 已更新')
        self.assertEqual(self.app.server_group.get(), '地球')
        self.assertEqual(self.app.line_display.get(), '1線')
        self.assertFalse(self.app._version_gate_entry_approved)
        self.assertTrue(self.app.connect_button.instate(['disabled']))

    def test_server_database_refresh_preserves_manual_login_fields(self):
        from wlre.storage import server_lines
        row = {'id': 101, 'name': '官方測試｜1線 (101)',
               'host': '8.8.8.8', 'port': 16988}
        self.app.host.set('manual.example.invalid')
        self.app.account.set('offline-fixture')
        self.app.password.set('offline-fixture')
        self.app.server_line.set(server_lines.CUSTOM)
        with (patch('wlre.ui.login_controller.server_lines.load', return_value=[row]),
              patch('wlre.ui.login_controller.login_memory.save') as save):
            for port in ('12345', ''):
                with self.subTest(port=port):
                    self.app.port.set(port)
                    self.app.show_login()
                    self.assertEqual(self.app.host.get(), 'manual.example.invalid')
                    self.assertEqual(self.app.port.get(), port)
                    self.assertEqual(self.app.account.get(), 'offline-fixture')
                    self.assertEqual(self.app.password.get(), 'offline-fixture')
                    self.assertEqual(self.app.server_group.get(), '自訂')
        save.assert_not_called()

    def test_login_status_explains_fresh_expired_and_invalid_results(self):
        import time
        self.deliver(official_result())
        self.app.continue_to_login()
        wait_for_widget_mapping(self.app.login_version_label)
        self.assertTrue(self.app.login_version_label.winfo_ismapped())
        for label in self.app.login_tab.winfo_children():
            if isinstance(label, ttk.Label):
                self.assertGreaterEqual(label.winfo_height(), label.winfo_reqheight())
        self.assertIn('版本識別最多沿用 5 分鐘', self.app._login_version_status.get())
        self.assertIn('非即時監測', self.app._login_version_status.get())
        self.app._observer_fresh_at = time.monotonic() - 301
        self.app.show_login()
        self.assertIn('已過期', self.app._login_version_status.get())
        self.app._version_gate_result['remote']['status'] = 'unverified'
        self.app._set_login_gate_button()
        self.assertIn('資料不一致', self.app._login_version_status.get())
        self.assertTrue(self.app.connect_button.instate(['disabled']))

    def test_network_check_error_cannot_connect_even_with_previous_approval(self):
        self.deliver(official_result())
        self.app.continue_to_login()
        with (patch('wlre.ui.version_gate_controller.run_prelogin_check',
                    side_effect=OSError('offline fixture')),
              patch('wlre.ui.version_gate_controller.threading.Thread') as thread,
              patch.object(self.app, 'start_lala_release_check')):
            _UNPATCHED_START_VERSION_CHECK(self.app)
            thread.call_args.kwargs['target']()
        self.app.drain_version_checks()
        self.assertEqual(self.app.version_gate_state, 'blocked')
        self.assertFalse(self.app._version_gate_entry_approved)
        self.assertIn('版本尚未確認', self.app._login_version_status.get())
        with (patch('wlre.ui.version_gate_controller.messagebox.showinfo'),
              patch('wlre.ui.gui.run_client') as client):
            self.app.connect()
        client.assert_not_called()

    def test_verified_unexpired_login_reaches_account_verification(self):
        # Explicit offline fixture: do not rely on pre-migration seeded state.
        self.app.set_profile({
            'rx_xor': 0, 'tx_xor': 0, 'platform': 3, 'language': 0,
            'verification_endpoint': {'host': 'example.invalid', 'port': 16988},
            'game_endpoint': {'host': 'example.invalid', 'port': 16988}})
        self.deliver(official_result())
        self.app.continue_to_login()
        self.app.account.set('offline-fixture')
        self.app.password.set('offline-fixture')
        with (patch.object(self.app, 'activate_account_settings'),
              patch.object(self.app, 'save_saved_login', return_value=True),
              patch.object(self.app, 'background', return_value=True) as background,
              patch('wlre.ui.gui.run_client') as client):
            self.app.connect()
            background.assert_called_once()
            background.call_args.args[0]()
        client.assert_called_once()
        self.assertIs(client.call_args.kwargs['verify_first'], True)
        self.assertEqual(self.app.version_window.state(), 'withdrawn')

    def test_shared_cyan_bar_stops_restarts_and_cleans_up(self):
        from wlre.progress_widgets import ACCENT, TRACK, CyanProgress
        progress = self.app._version_progress
        self.assertIsInstance(progress, CyanProgress)
        self.app.version_gate_state = 'checking'
        self.app._render_version_window()
        timer = progress._timer
        self.assertIsNotNone(timer)
        self.app._render_version_window()
        self.assertEqual(progress._timer, timer)
        self.root.update_idletasks()
        self.assertEqual(progress.canvas.cget('background'), TRACK)
        self.assertEqual(progress.canvas.itemcget(progress._fill, 'fill'), ACCENT)
        self.deliver(official_result('1275', '1262', 'blocked'))
        self.assertIsNone(progress._timer)
        self.assertTrue(self.app._version_continue_button.instate(['disabled']))
        self.app.version_gate_state = 'checking'
        progress.reset()  # Only a new attempt may release the terminal latch.
        self.app._render_version_window()
        self.assertIsNotNone(progress._timer)
        progress.canvas.destroy()
        self.assertIsNone(progress._timer)

    def test_formal_result_is_separate_from_collection_summary_and_stops_animation(self):
        import time
        self.app._launcher_catalog_status = '官方原始資源已保存；各類解析結果另列｜收集階段解析 7/7'
        self.app._startup_started_at = time.monotonic() - 27
        self.app._startup_stage_started_at = self.app._startup_started_at
        for phase, title in (('official_metadata', '官方版本查詢'),
                             ('official_runtime', '正式 Runtime 驗證'),
                             ('official_database', '資料庫內容比對')):
            self.app._official_progress.report(phase, {})
            self.app.drain_version_checks()
            self.assertIn(title, self.app._version_heading.get())
            self.assertIn('已用 27 秒', self.app._startup_elapsed.get())
            self.assertIsNotNone(self.app._version_progress._timer)
        self.deliver(official_result())
        self.assertIn('正式 Runtime／登入驗證：', self.app._version_remote.get())
        self.assertIn('\n資源收集紀錄：', self.app._version_remote.get())
        self.assertIn('7/7', self.app._version_remote.get())
        self.assertIn('完成 · 共用 27 秒', self.app._startup_elapsed.get())
        progress = self.app._version_progress
        self.assertTrue(progress._finished)
        self.assertIsNone(progress._timer)
        for _ in range(5):
            self.app._official_progress.report('official_runtime', {})
            self.app.drain_version_checks()
            self.app._render_version_window()
            progress.set_counts(None)
        self.assertIsNone(progress._timer)
        self.assertTrue(progress._finished)

    def test_progress_timer_has_bounded_rate_and_zero_terminal_ticks(self):
        import time
        progress = self.app._version_progress
        progress.stop()
        with patch.object(progress.canvas, 'after', wraps=progress.canvas.after) as after:
            progress.reset()
            deadline = time.perf_counter() + 1.05
            while time.perf_counter() < deadline:
                self.root.update()
                time.sleep(.004)
            active_calls = after.call_count
            self.assertGreaterEqual(active_calls, 2)
            self.assertLessEqual(active_calls, 28)  # One 40 ms loop, never duplicate timers.
            self.deliver(official_result('1275', '1262', 'blocked'))
            offset = progress._offset
            terminal_calls = after.call_count
            deadline = time.perf_counter() + .25
            while time.perf_counter() < deadline:
                self.root.update()
                time.sleep(.004)
            self.assertEqual(after.call_count, terminal_calls)
            self.assertEqual(progress._offset, offset)
            self.assertIsNone(progress._timer)

    def test_version_screen_before_account_fields(self):
        self.assertTrue(self.app.version_window.winfo_ismapped())
        self.assertEqual(self.app.login_window.state(), "withdrawn")
        self.assertEqual(str(self.app.connect_button.cget("state")), "disabled")
        self.assertEqual(self.app._version_baseline.get(), "等待官方版本確認")
        self.assertNotIn("選擇遊戲目錄",
                         [str(x.cget("text")) for x in self.app.version_window.winfo_children()
                          if "text" in x.keys()])

    def test_matching_current_database_allows_login_without_protocol_acceptance(self):
        remote={'status':'resources_changed','resource_path':'1.3.22.1',
                'official_exe_version':'1.3.0','newer_official_client':False,
                'packages':{row['name']:{'remote':row['full_version'],'comparison':'newer'}
                            for row in identity()['packages']}}
        result={'status':'database_matches_official','blocked':False,
                'login_allowed':True,'database_verified':True,'database_comparison':'same',
                'dynamic_runtime':'verified','data_compatibility':'compatible',
                'protocol_compatibility':'unverified','remote':remote,
                'baseline_label':'DataPackage 1286／MainPackage 1284',
                'runtime_identity':identity()}
        self.deliver(result)
        self.assertEqual(self.app.version_gate_state,'ready')
        self.assertFalse(self.app._version_continue_button.instate(['disabled']))
        self.assertIn('可以登入',self.app._version_heading.get())
        self.app.continue_to_login()
        self.assertTrue(self.app._version_gate_entry_approved)
        self.assertEqual(self.app.version_window.state(),'withdrawn')
        self.assertTrue(self.app.can_login_after_version_check())

    def test_confirmed_remote_change_blocks(self):
        self.deliver(official_result("1275", "1262", "blocked"))
        self.assertTrue(self.app._version_continue_button.instate(["disabled"]))
        self.assertIn("等待 LaLa 更新", self.app._version_heading.get())
        self.assertIn("1275", self.app._version_main.get())
        self.assertEqual(self.app.login_window.state(), "withdrawn")
        self.assertFalse(self.app._version_gate_entry_approved)

    def test_same_official_version_with_missing_formal_assets_is_not_mislabeled_update(self):
        response = official_result('1275', '1275', 'blocked')
        response['remote']['status'] = 'same_resources'
        response['message'] = ('LaLa 1275 缺少已校驗的 NPC／商店／製作／場景資料；'
                               '仍禁止登入。')
        self.deliver(response)
        self.assertIn('正式資源尚未就緒', self.app._version_heading.get())
        self.assertNotIn('官方版本異動', self.app._version_heading.get())
        self.assertTrue(self.app._version_continue_button.instate(['disabled']))

    def test_confirmed_online_1262_requires_explicit_continue(self):
        self.deliver(official_result())
        self.assertEqual(self.app.login_window.state(), "withdrawn")
        self.assertEqual(self.app._version_continue_button.cget("text"), "進入登入畫面")
        self.app.continue_to_login()
        self.assertEqual(self.app.version_window.state(), "withdrawn")
        self.assertNotEqual(self.app.login_window.state(), "withdrawn")
        self.assertTrue(self.app._version_gate_entry_approved)

    def test_baseline_display_is_loaded_from_bundled_declaration(self):
        from types import SimpleNamespace
        from wlre.services.resource_compatibility import baseline_label
        supported = {"DataPackage": "1275", "MainPackage": "1275"}
        with patch.dict("wlre.ui.version_gate_controller.BASELINE",
                        supported, clear=True):
            fake = SimpleNamespace()
            VersionGateController.initialize_version_gate(fake)
            self.assertEqual(fake._version_baseline.get(), "等待官方版本確認")
            self.assertIn("官方", fake.version_gate_text.get())
            # An actual redraw uses the current package baselines instead of
            # keeping a hard-coded 1262 in its comparison text.
            self.deliver(official_result("1280", "1280", "blocked"))
            self.assertIn("與 1275 不同", self.app._version_main.get())
            self.assertIn("與 1275 不同", self.app._version_data.get())
            self.assertNotIn("1262", self.app._version_main.get())
            self.assertNotIn("1262", self.app._version_data.get())
            self.root.update()

    def test_unknown_state_blocks_login_even_if_worker_sets_blocked_false(self):
        self.deliver(official_result(status="unverified"))
        self.assertEqual(self.app.login_window.state(), "withdrawn")
        self.assertEqual(self.app._version_continue_button.cget("text"), "禁止登入")
        self.assertTrue(self.app._version_continue_button.instate(["disabled"]))
        self.assertEqual(self.app.version_gate_state, "blocked")
        self.assertTrue(self.app._version_gate_result["blocked"])
        self.assertIn("無法驗證", self.app._version_main.get())
        with patch("wlre.ui.version_gate_controller.messagebox.showwarning"):
            self.app.continue_to_login()
        self.assertEqual(self.app.login_window.state(), "withdrawn")
        self.assertFalse(self.app._version_gate_entry_approved)
        self.assertEqual(str(self.app.connect_button.cget("state")), "disabled")

    def test_conflicting_verified_flag_still_blocks_login(self):
        result = official_result()
        result["remote"]["status"] = "unverified"
        self.deliver(result)
        self.assertEqual(self.app.version_gate_state, "blocked")
        self.assertEqual(self.app._version_gate_result["status"], "unverified")
        self.assertTrue(self.app._version_continue_button.instate(["disabled"]))

    def test_worker_exception_fails_closed_without_exposing_exception(self):
        with (patch("wlre.ui.version_gate_controller.run_prelogin_check",
                    side_effect=RuntimeError("private credential path")),
              patch("wlre.ui.version_gate_controller.threading.Thread") as thread,
              patch.object(self.app, "start_lala_release_check")):
            _UNPATCHED_START_VERSION_CHECK(self.app)
            thread.call_args.kwargs["target"]()
        self.app.drain_version_checks()
        self.assertEqual(self.app.version_gate_state, "blocked")
        self.assertTrue(self.app._version_continue_button.instate(["disabled"]))
        self.assertNotIn("private credential path", self.app.version_gate_text.get())

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

    def test_responsive_version_window_has_no_scrollbars_or_blank_canvas(self):
        self.deliver(official_result("1275", "1275", "blocked"))
        wait_for_widget_mapping(self.app._lala_download_button)
        self.root.update()
        window = self.app.version_window
        widgets = []

        def collect(parent):
            for child in parent.winfo_children():
                widgets.append(child)
                collect(child)

        collect(window)
        self.assertEqual([w for w in widgets if isinstance(w, tk.Canvas)],
                         [self.app._version_progress.canvas])
        self.assertFalse(any(isinstance(w, __import__("tkinter").ttk.Scrollbar)
                             for w in widgets))
        self.assertGreaterEqual(window.winfo_height(), min(590, window.winfo_screenheight() - 24))
        # 710 is the initial size; truthful phase/elapsed text may grow it to
        # the content request, still bounded by the existing screen margin.
        self.assertLessEqual(window.winfo_height(), window.winfo_screenheight() - 48)
        self.assertTrue(self.app._version_elapsed_label.winfo_ismapped())
        self.assertLessEqual(
            self.app._version_elapsed_label.winfo_rooty() + self.app._version_elapsed_label.winfo_height(),
            window.winfo_rooty() + window.winfo_height())
        self.assertTrue(window.resizable()[0])
        self.assertTrue(window.resizable()[1])
        self.assertTrue(self.app._version_release_panel.winfo_ismapped())
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

    def test_three_sections_and_buttons_keep_separate_vertical_space(self):
        self.deliver(official_result("1275", "1275", "blocked"))
        self.app.version_gate_text.set(
            "1275 正式資源尚未就緒，候選資料未經安全驗證。" * 4)
        self.app._version_remote.set(
            "缺少 DataCatalog 與 NPC 正式索引，尚未允許登入。" * 5)
        self.app._lala_release_text.set(
            "LaLa v0.6.0 · GitHub Release 狀態已檢查；暫無更新。" * 2)
        self.root.update()
        alert = self.app._version_alert_panel
        resource = self.app._version_resource_panel
        release = self.app._version_release_panel
        progress = self.app._version_progress.canvas
        button = self.app._version_continue_button
        self.assertLessEqual(
            alert.winfo_rooty() + alert.winfo_height(),
            resource.winfo_rooty())
        self.assertLessEqual(
            resource.winfo_rooty() + resource.winfo_height(),
            release.winfo_rooty())
        self.assertLessEqual(
            release.winfo_rooty() + release.winfo_height(),
            progress.winfo_rooty())
        self.assertGreater(button.winfo_height(), 15)
        self.assertLessEqual(
            button.winfo_rooty() + button.winfo_height(),
            self.app.version_window.winfo_rooty()
            + self.app.version_window.winfo_height())

    def test_resizing_reflows_every_long_text_label(self):
        window = self.app.version_window
        self.root.update()
        before = self.app._version_release_label.cget("wraplength")
        w = window.winfo_width()
        h = window.winfo_height()
        available = window.winfo_screenwidth() - 24
        if available - w < 35:
            self.skipTest("Viewport is already at its widest usable size")
        window.geometry(f"{min(available, w + 80)}x{h}")
        self.root.update()
        self.assertGreater(
            int(self.app._version_release_label.cget("wraplength")),
            int(before))
        self.assertEqual(
            int(self.app._version_alert_message_label.cget("wraplength")),
            int(self.app._version_alert_heading_label.cget("wraplength")))
        self.assertEqual(len(self.app._version_resource_values), 5)
        self.assertTrue(self.app._version_continue_button.winfo_ismapped())

    def test_late_status_growth_refits_sections_including_theme_title_bar(self):
        window = self.app.version_window
        if window.winfo_screenheight() < 900:
            self.skipTest('Requires enough vertical space to test automatic growth')
        window.geometry('1000x590')
        self.root.update()
        self.app.version_gate_text.set('1275 正式資源尚未就緒，候選資料未經安全驗證。' * 4)
        self.app._version_remote.set('缺少 DataCatalog 與 NPC 正式索引，尚未允許登入。' * 5)
        self.app._lala_release_text.set('LaLa 正式 Release 狀態已檢查，暫無更新。' * 2)
        self.root.update()
        release = self.app._version_release_panel
        self.assertTrue(release.winfo_ismapped())
        self.assertLessEqual(release.winfo_rooty() + release.winfo_height(),
                             self.app._version_progress.canvas.winfo_rooty())
        self.assertGreater(window.winfo_height(), 590)

    def test_reopen_revokes_previous_approval(self):
        self.deliver(official_result())
        self.app.continue_to_login()
        self.app.reopen_version_check()
        self.assertFalse(self.app._version_gate_entry_approved)
        self.assertTrue(self.app.version_window.winfo_ismapped())
        self.assertEqual(self.app.login_window.state(), "withdrawn")

    def test_stale_background_result_cannot_override_newer_check(self):
        self.app._version_gate_generation = 2
        self.app._version_gate_messages.put((1, official_result("1275", "1262", "blocked"), time.monotonic()))
        self.app._version_gate_messages.put((2, official_result(status="unverified"), time.monotonic()))
        self.app.drain_version_checks()
        self.assertEqual(self.app.version_gate_state, "blocked")
        self.assertTrue(self.app._version_continue_button.instate(["disabled"]))
        self.assertEqual(self.app.version_gate_text.get(), "官方線上版本檢測結果")

    def observe(self, result):
        token = self.app._background_schedule.begin(force=True)
        self.assertIsNotNone(token)
        import time
        self.app._background_messages.put((token, result, time.monotonic()))
        self.app.poll_background_versions()
        self.root.update()

    def test_live_observer_alarm_shows_true_comparison_and_safe_controls(self):
        from dataclasses import replace
        from wlre.services.background_version_observer import ObservationResult
        self.deliver(official_result())
        self.app.continue_to_login()
        self.app.live_active = True
        anchor = self.app._observer_anchor
        changed = replace(anchor, data_package='1297_2026_11_07_13_34_19_13')
        self.observe(ObservationResult('identifiers_differ', 'observed', changed, anchor,
                                      '2026-11-07T11:00:00+00:00'))
        self.assertNotEqual(self.app.version_window.state(), 'withdrawn')
        self.assertEqual(self.app.login_window.state(), 'withdrawn')
        self.assertTrue(self.app._session_resource_hold.is_set())
        self.assertTrue(self.app._version_retry_button.instate(['disabled']))
        self.assertTrue(self.app._version_continue_button.instate(['disabled']))
        self.assertFalse(self.app._observer_disconnect_button.instate(['disabled']))
        self.assertFalse(self.app._observer_retry_button.instate(['disabled']))
        self.assertIsNone(self.app._version_progress._timer)
        self.assertIn('官方 1297_', self.app._version_data.get())
        self.assertIn('資料庫 1296_', self.app._version_data.get())
        self.assertIn('1.3.0', self.app._version_path.get())
        self.assertIn('1.3.22.1', self.app._version_path.get())
        self.assertIn('連線保持', self.app.version_gate_text.get())
        window_bottom = self.app.version_window.winfo_rooty() + self.app.version_window.winfo_height()
        for widget in (self.app._background_label, self.app._observer_retry_button,
                       self.app._observer_disconnect_button, self.app._version_continue_button,
                       self.app._version_release_panel):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), window_bottom)
        self.assertLessEqual(self.app._version_release_panel.winfo_rooty() + self.app._version_release_panel.winfo_height(),
                             self.app._version_elapsed_label.winfo_rooty())
        self.app._observer_disconnect_button.invoke()
        self.assertTrue(self.app.stop_event.is_set())
        self.assertTrue(self.app._session_resource_hold.is_set())
        self.app.events.put(('session_finished', None))
        App._poll_once(self.app)
        self.root.update()
        self.assertFalse(self.app.live_active)
        self.assertFalse(self.app._version_retry_button.instate(['disabled']))
        self.assertTrue(self.app._observer_disconnect_button.instate(['disabled']))
        self.assertNotEqual(self.app.version_window.state(), 'withdrawn')

    def test_unknown_observation_does_not_display_old_success_as_current(self):
        from wlre.services.background_version_observer import ObservationResult
        self.deliver(official_result())
        anchor = self.app._observer_anchor
        self.observe(ObservationResult('identifiers_match', 'observed', anchor, anchor,
                                      '2026-11-07T11:00:00+00:00'))
        self.observe(ObservationResult('unverified', 'official_unavailable', None, None,
                                      '2026-11-07T11:05:00+00:00'))
        self.assertIn('官方 未知', self.app._version_data.get())
        self.assertIn('資料庫 未知', self.app._version_main.get())
        self.assertIn('11:00:00 UTC', self.app._background_status.get())
        self.assertIn('查詢失敗', self.app._background_status.get())
        self.assertNotIn('11:05:00 UTC', self.app._background_status.get())
        self.assertTrue(self.app._version_continue_button.instate(['disabled']))

    def test_late_matching_recovery_and_release_rerender_cannot_resume_animation(self):
        from wlre.services.background_version_observer import ObservationResult
        self.deliver(official_result())
        anchor = self.app._observer_anchor
        self.observe(ObservationResult('unverified', 'official_unavailable', None, None,
                                      '2026-11-07T11:00:00+00:00'))
        self.observe(ObservationResult('identifiers_match', 'observed', anchor, anchor,
                                      '2026-11-07T11:05:00+00:00'))
        for _ in range(100):
            self.app._render_version_window()
            self.app.drain_version_checks()
        self.assertIsNone(self.app._version_progress._timer)
        self.assertTrue(self.app._observer_requires_full_check)
        self.assertTrue(self.app._version_continue_button.instate(['disabled']))
        self.assertIn('先前異常', self.app._background_status.get())



if __name__ == "__main__":
    unittest.main()
