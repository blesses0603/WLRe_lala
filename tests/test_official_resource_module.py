"""真實 Thread／核心組裝、合成傳輸資料；無正式服或 GUI 依賴。"""
import queue
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from unittest.mock import patch

from test_official_resource_manager import Fixture

from wlre.core.application import Application, Lifecycle, LifecycleError
from wlre.core.application.configuration import ApplicationConfiguration
from wlre.resources_runtime.official.contracts import SCENE_DEFINITIONS
from wlre.resources_runtime.official.manager import ResourceRefreshError
from wlre.resources_runtime.official.module import (
    OfficialResourceModule,
    ResourceRefreshFinished,
)


@dataclass(frozen=True)
class OtherEvent:
    value: int


class ResourceModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = Fixture()
        self.decoder = patch('wlre.resources_runtime.parsers.unity_textasset._loader',
                             side_effect=self.fixture.loader)
        self.decoder.start()
        self.addCleanup(self.decoder.stop)
        self.module = OfficialResourceModule(self.temp.name, opener=self.fixture.open)
        self.app = Application((self.module,), configuration=ApplicationConfiguration(
            event_capacity=1, events_per_tick=1))
        self.addCleanup(self.app.stop)
        self.api = self.module.api

    def start(self):
        self.app.initialize()
        self.app.start()

    def refresh(self):
        return self.api.refresh('2.0.0', scope='scenes', requirements=(SCENE_DEFINITIONS,))

    def settle(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = self.api.poll()
            if status.phase not in ('refreshing', 'cancel_requested') and status.workers == 0:
                return status
            Event().wait(0.002)
        self.fail('受管工作未在測試期限退出')

    def test_initialize_and_start_do_not_make_network_requests(self):
        self.start()
        self.assertEqual(self.fixture.calls, [])
        self.assertEqual(self.api.status().phase, 'idle')
        self.assertEqual(self.api.status().workers, 0)
        with self.assertRaises(ResourceRefreshError):
            self.api.current()

    def test_public_methods_require_ready_and_owner_thread(self):
        saved_poll = self.api.poll
        with self.assertRaises(LifecycleError):
            saved_poll()
        self.start()
        with ThreadPoolExecutor(max_workers=1) as pool, self.assertRaises(RuntimeError):
            pool.submit(saved_poll).result(timeout=2)
        self.app.stop()
        with self.assertRaises(LifecycleError):
            saved_poll()

    def test_real_worker_posts_only_small_completion_on_owner_poll(self):
        self.start()
        seen = []
        self.app.events.subscribe(ResourceRefreshFinished, seen.append)
        self.assertEqual(self.refresh(), 1)
        status = self.settle()
        self.assertEqual(status.phase, 'current')
        self.assertEqual(seen, [])
        self.app.pump()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].snapshot_id, self.api.current().snapshot_id)
        self.assertLess(len(repr(seen[0])), 512)
        self.assertEqual(len(self.api.current().records('scene_definitions')), 2)
        self.assertFalse(self.api.current().protocol_approved)
        self.assertEqual(self.app.events.subscriber_count, 1)
        self.app.stop()
        self.assertEqual(self.app.events.subscriber_count, 0)

    def test_failed_refresh_revokes_old_view_and_preserves_diagnostic_only(self):
        self.start()
        self.refresh()
        self.settle()
        old = self.api.current()
        snapshot = old.snapshot_id
        self.app.pump()
        with patch.object(self.module._manager._transport, 'read', side_effect=OSError('secret-token')):
            self.refresh()
            with self.assertRaises(ResourceRefreshError):
                old.records('scene_definitions')
            status = self.settle()
        self.assertEqual(status.phase, 'failed')
        self.assertNotIn('secret-token', repr(status))
        with self.assertRaises(ResourceRefreshError):
            self.api.current()
        self.assertEqual(self.api.diagnose('scenes')['snapshot'], snapshot)
        self.assertEqual(self.api.diagnose('scenes')['status'], 'unverified_cache_diagnostic_only')
        self.app.pump()
        self.refresh()
        self.assertEqual(self.settle().phase, 'current')

    def test_backpressure_keeps_completion_and_blocks_another_refresh(self):
        self.start()
        self.app.events.post(OtherEvent(1))
        seen = []
        self.app.events.subscribe(ResourceRefreshFinished, seen.append)
        self.refresh()
        self.assertTrue(self.settle().notification_pending)
        with self.assertRaises(ResourceRefreshError):
            self.refresh()
        self.app.pump()
        self.assertFalse(self.api.poll().notification_pending)
        self.app.pump()
        self.assertEqual(len(seen), 1)
        self.api.poll()
        self.app.pump()
        self.assertEqual(len(seen), 1)

    def test_cancel_does_not_publish_a_late_success(self):
        self.start()
        entered, release = Event(), Event()
        original = self.module._manager.refresh

        def delayed(*args, **kwargs):
            value = original(*args, **kwargs)
            entered.set()
            release.wait(5)
            return value

        with patch.object(self.module._manager, 'refresh', side_effect=delayed):
            self.refresh()
            self.assertTrue(entered.wait(3))
            try:
                self.api.cancel()
                self.assertEqual(self.api.status().phase, 'cancel_requested')
                with self.assertRaises(ResourceRefreshError):
                    self.api.current()
                with self.assertRaises(ResourceRefreshError):
                    self.refresh()
            finally:
                release.set()
            self.assertEqual(self.settle().phase, 'cancelled')
        self.app.pump()
        self.refresh()
        self.assertEqual(self.settle().phase, 'current')

    def test_cancel_pending_notification_reports_cancelled(self):
        self.start()
        self.app.events.post(OtherEvent(1))
        seen = []
        self.app.events.subscribe(ResourceRefreshFinished, seen.append)
        self.refresh()
        self.settle()
        view = self.api.current()
        self.api.cancel()
        with self.assertRaises(ResourceRefreshError):
            view.reference_summary()
        self.app.pump()
        self.api.poll()
        self.app.pump()
        self.assertEqual([row.phase for row in seen], ['cancelled'])

    def test_stop_revokes_view_and_drops_unpublished_result_and_event(self):
        self.start()
        self.refresh()
        self.settle()
        view = self.api.current()
        self.app.stop()
        self.assertEqual(self.module.state, Lifecycle.STOPPED)
        self.assertEqual(self.module._workers.pending(), 0)
        self.assertTrue(self.module._results.empty())
        with self.assertRaises(ResourceRefreshError):
            view.records('scene_definitions')
        with self.assertRaises(LifecycleError):
            self.api.poll()

    def test_cooperative_worker_is_cancelled_and_joined_on_stop(self):
        self.start()
        entered, finished = Event(), Event()

        def wait_for_cancel(*args, cancel_event=None, **kwargs):
            entered.set()
            if not cancel_event.wait(5):
                raise AssertionError('工作未收到合作式取消')
            finished.set()
            raise InterruptedError()

        with patch.object(self.module._manager, 'refresh', side_effect=wait_for_cancel):
            self.refresh()
            self.assertTrue(entered.wait(2))
            self.app.stop()
        self.assertTrue(finished.is_set())
        self.assertEqual(self.module._workers.pending(), 0)
        self.assertEqual(self.app.state, Lifecycle.STOPPED)

    def test_uncooperative_worker_marks_stop_failed_until_released(self):
        self.module._shutdown_timeout = 0.01
        self.start()
        entered, release = Event(), Event()

        def uncooperative(*args, **kwargs):
            entered.set()
            release.wait(5)
            raise InterruptedError()

        try:
            with patch.object(self.module._manager, 'refresh', side_effect=uncooperative):
                self.refresh()
                self.assertTrue(entered.wait(2))
                with self.assertRaises(LifecycleError):
                    self.app.stop()
                self.assertEqual(self.app.state, Lifecycle.FAILED)
                self.assertEqual(self.module.state, Lifecycle.FAILED)
        finally:
            release.set()
            self.module._workers.close(timeout=3)
        self.assertEqual(self.module._workers.pending(), 0)
        self.assertTrue(self.module._results.empty())

    def test_worker_start_failure_is_safe_and_can_retry(self):
        self.start()
        with (patch('wlre.core.application.workers.Thread.start', side_effect=RuntimeError('sensitive')),
              self.assertRaisesRegex(ResourceRefreshError, '^official_worker_start_failed$')):
            self.refresh()
        self.assertEqual(self.api.status().workers, 0)
        self.refresh()
        self.assertEqual(self.settle().phase, 'current')

    def test_invalid_requests_do_not_start_work_or_revoke_current_view(self):
        self.start()
        self.refresh()
        self.settle()
        view = self.api.current()
        for scope, requirements in (('../bad', (SCENE_DEFINITIONS,)), ('scenes', [])):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                self.api.refresh('2.0.0', scope=scope, requirements=requirements)
        self.assertEqual(view.get('scene_definitions', 12170)['id'], 12170)
        self.assertEqual(self.api.status().workers, 0)

    def test_result_mailbox_is_bounded(self):
        self.assertEqual(self.module._results.maxsize, 1)
        self.module._results.put_nowait(object())
        with self.assertRaises(queue.Full):
            self.module._results.put_nowait(object())
        self.module._results.get_nowait()


class SnapshotLifecycleToolTests(unittest.TestCase):
    def test_tool_composes_real_module_and_revokes_context_view(self):
        from tools.check_official_resource_snapshot import managed_snapshot
        fixture = Fixture()
        with (tempfile.TemporaryDirectory() as root,
              patch('wlre.resources_runtime.parsers.unity_textasset._loader', fixture.loader)):
            with managed_snapshot(root, '2.0.0', scope='scenes', requirements=(SCENE_DEFINITIONS,),
                                  opener=fixture.open) as (service, receipt):
                self.assertEqual(service.get('scene_definitions', 12170)['id'], 12170)
                self.assertEqual(receipt['acceptance'], 'validated_requested_scope')
            with self.assertRaises(ResourceRefreshError):
                service.reference_summary()

    def test_tool_deadline_cancels_and_joins_cooperative_worker(self):
        from tools.check_official_resource_snapshot import managed_snapshot
        from wlre.resources_runtime.official.manager import OfficialResourceManager
        finished = Event()

        def delayed(*args, cancel_event=None, **kwargs):
            if not cancel_event.wait(5):
                raise AssertionError('截止後未取消')
            finished.set()
            raise InterruptedError()

        with (tempfile.TemporaryDirectory() as root,
              patch.object(OfficialResourceManager, 'refresh', side_effect=delayed),
              self.assertRaises(TimeoutError),
              managed_snapshot(root, '2.0.0', scope='scenes', requirements=(SCENE_DEFINITIONS,),
                               timeout=0.02)):
            self.fail('逾時不可提供查詢服務')
        self.assertTrue(finished.is_set())

    def test_tool_invalid_deadlines_do_not_initialize_module(self):
        from tools.check_official_resource_snapshot import managed_snapshot
        for timeout in (0, -1, float('inf'), float('nan'), 301, True):
            with (self.subTest(timeout=timeout), self.assertRaises(ValueError),
                  patch('tools.check_official_resource_snapshot.OfficialResourceModule') as module,
                  managed_snapshot('/unused', '2.0.0', scope='scenes', requirements=(SCENE_DEFINITIONS,),
                                   timeout=timeout)):
                self.fail('無效截止不可初始化')
            module.assert_not_called()

    def test_tool_does_not_publish_report_when_lifecycle_cleanup_fails(self):
        import contextlib
        from pathlib import Path

        from tools.check_official_resource_snapshot import main

        @contextlib.contextmanager
        def failed_cleanup(*args, **kwargs):
            fixture = Fixture()
            from wlre.resources_runtime.official.manager import OfficialResourceManager
            with (tempfile.TemporaryDirectory() as cache,
                  patch('wlre.resources_runtime.parsers.unity_textasset._loader', fixture.loader),
                  OfficialResourceManager(cache, opener=fixture.open) as manager):
                service = manager.refresh('2.0.0', scope='scene_definitions',
                                          requirements=(SCENE_DEFINITIONS,))
                yield service, manager.diagnose('scene_definitions')['document']
            raise LifecycleError('application_stop_failed')

        with (tempfile.TemporaryDirectory() as root,
              patch('tools.check_official_resource_snapshot.private_cache', return_value=Path(root)),
              patch('tools.check_official_resource_snapshot.managed_snapshot', failed_cleanup),
              patch('builtins.print')):
            report = Path(root) / 'report.json'
            self.assertEqual(main(['--exe-version', '2.0.0', '--cache-root', root,
                                   '--report', str(report)]), 2)
            self.assertFalse(report.exists())


class ResourceFailureCodeTests(unittest.TestCase):
    def test_only_reviewed_codes_reach_owner_status(self):
        from wlre.resources_runtime.official.module import _refresh
        for incoming, expected in (
            ('official_versions_changed_during_refresh', 'official_versions_changed_during_refresh'),
            ('private-token-example', 'official_resource_refresh_failed')):
            with self.subTest(incoming=incoming):
                from queue import Queue
                from threading import Lock
                manager = unittest.mock.Mock()
                manager.refresh.side_effect = ResourceRefreshError(incoming)
                results = Queue(1)
                _refresh(manager, '2.0.0', 'scenes', (SCENE_DEFINITIONS,), Event(), results, Lock(), Event())
                self.assertEqual(results.get_nowait().code, expected)
