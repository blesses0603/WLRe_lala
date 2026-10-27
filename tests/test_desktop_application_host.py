"""新核心與實際 Tk／既有主頁的整合，禁止測試連線官方站。"""
import os
import sys
import time
import tkinter as tk
import unittest
from dataclasses import dataclass
from threading import Event, Thread
from unittest.mock import patch

from _tk_native_pump import create_root

from wlre.core.application import Lifecycle, LifecycleError
from wlre.ui.application_host import DesktopHost
from wlre.ui.gui import App


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin', '需要桌面顯示環境')
class DesktopHostTests(unittest.TestCase):
    def setUp(self):
        self.root = create_root()
        self.patcher = patch('wlre.ui.version_gate_controller.VersionGateController.start_version_check')
        self.patcher.start()
        self.host = DesktopHost(self.root)
        self.host.start()
        self.root.update_idletasks()

    def tearDown(self):
        self.patcher.stop()
        if self.host.core.state not in (Lifecycle.STOPPED, Lifecycle.FAILED):
            self.host.finish()

    def test_existing_dashboard_and_feature_entrypoints_survive_new_host(self):
        app = self.host.module.app
        self.assertIsInstance(app, App)
        app.show_main()
        self.root.update_idletasks()
        # Windows 的原生 Map 訊息不屬於 idle 工作，必須讓真實事件迴圈處理。
        # 只等待必要的可見狀態，2 秒截止，不以跳過斷言掩蓋啟動失敗。
        visible = tk.BooleanVar(self.root, value=False)
        deadline = time.monotonic() + 2

        def wait_for_map():
            mapped = bool(app.overview_panel.winfo_ismapped())
            if mapped or time.monotonic() >= deadline:
                visible.set(mapped)
            else:
                self.root.after(10, wait_for_map)

        self.root.after(0, wait_for_map)
        self.root.wait_variable(visible)
        self.assertTrue(visible.get(), '桌面啟動後 2 秒內主頁仍未顯示')
        self.assertTrue(app.overview_panel.winfo_ismapped())
        for method in ('open_feature', 'start_roaming', 'send', 'stop', 'close'):
            self.assertTrue(callable(getattr(app, method)))
        self.assertEqual(self.host.core.state, Lifecycle.RUNNING)
        self.assertFalse(self.host.module.api.status().closing)
        app.close()
        self.assertEqual(self.host.core.state, Lifecycle.STOPPED)
        self.host.finish()

    def test_close_is_nonblocking_and_waits_for_worker_without_accepting_commands(self):
        app, cancel, released = self.host.module.app, Event(), Event()

        def work():
            cancel.wait()
            released.wait()

        worker = Thread(target=work, name='desktop-test')
        app.launch_worker(worker, cancel.set)
        try:
            app.close()
            self.assertTrue(cancel.is_set())
            self.assertTrue(worker.is_alive())
            self.assertTrue(app._closing)
            self.assertFalse(app.send({'type': 'stop_roaming'}))
            self.assertEqual(self.host.core.state, Lifecycle.RUNNING)
            # 回呼確實能繼續執行，沒有在關閉處阻塞 join。
            heartbeat = []
            self.root.after(0, lambda: heartbeat.append(True))
            self.root.update()
            self.assertEqual(heartbeat, [True])
        finally:
            released.set()
            worker.join(2)
        self.host._wait_for_workers()
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.host.core.state, Lifecycle.STOPPED)

    def test_expired_shutdown_is_failed_and_not_reported_successful(self):
        app, stopped = self.host.module.app, Event()
        worker = Thread(target=stopped.wait, name='uncooperative-test')
        app.launch_worker(worker, lambda: None)
        try:
            app.close()
            self.host._deadline = -1
            self.host._wait_for_workers()
            self.assertEqual(self.host.core.state, Lifecycle.FAILED)
            with self.assertRaisesRegex(LifecycleError, '^desktop_shutdown_failed$'):
                self.host.finish()
        finally:
            stopped.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())


    def test_resource_worker_close_keeps_tk_responsive_and_releases_all_workers(self):
        app, entered, release = self.host.module.app, Event(), Event()

        def waiting(*args, cancel_event=None, **kwargs):
            entered.set()
            cancel_event.wait(3)
            release.wait(3)
            raise InterruptedError()

        with patch.object(self.host.resources._manager, 'refresh', side_effect=waiting):
            from wlre.resources_runtime.official.contracts import SCENE_DEFINITIONS
            self.host.resources.api.refresh('2.0.0', scope='scenes', requirements=(SCENE_DEFINITIONS,))
            try:
                self.assertTrue(entered.wait(2))
                app.close()
                self.assertEqual(self.host.core.state, Lifecycle.RUNNING)
                self.assertEqual(self.host.resources.api.status().phase, 'cancel_requested')
                heartbeat = tk.BooleanVar(self.root, value=False)
                self.root.after(0, lambda: heartbeat.set(True))
                self.root.wait_variable(heartbeat)
                self.assertTrue(heartbeat.get())
            finally:
                release.set()
            # root 會在 shutdown 時銷毀；改以既有工作群有界等待後由 host 收尾。
            deadline = time.monotonic() + 2
            while self.host.resources.api.status().workers and time.monotonic() < deadline:
                Event().wait(0.002)
            self.host._wait_for_workers()
            self.assertEqual(self.host.core.state, Lifecycle.STOPPED)
            self.assertEqual(self.host.resources._workers.pending(), 0)

    def test_scene_data_entry_is_attached_to_public_resource_api(self):
        app = self.host.module.app
        self.assertEqual(str(app.home_map.official_data_button['state']), 'normal')
        app.open_official_scene_data()
        self.root.update_idletasks()
        self.assertTrue(app._official_scene_data.window.winfo_exists())
        self.assertEqual(app._official_scene_data.window.tree.get_children(), ())
        self.assertEqual(self.host.resources.api.status().phase, 'idle')

    def test_event_handler_can_close_desktop_without_scheduling_after_destroy(self):
        @dataclass(frozen=True)
        class CloseRequested:
            pass

        self.host.core.events.subscribe(CloseRequested, lambda event: self.host.request_close())
        self.host.core.events.post(CloseRequested())
        self.host._pump()
        self.assertEqual(self.host.core.state, Lifecycle.STOPPED)
