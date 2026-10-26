"""背景工作登記：真實執行緒停止、重複啟動及失敗結果。"""
import unittest
from threading import Event, Thread

from wlre.core.application import LifecycleError
from wlre.core.application.workers import WorkerGroup


class WorkerGroupTests(unittest.TestCase):
    def test_stop_all_and_completed_workers_are_released(self):
        group = WorkerGroup()
        stopped = Event()
        worker = Thread(target=stopped.wait, name='worker')
        group.start(worker, stopped.set)
        self.assertTrue(group.running('worker'))
        self.assertEqual(group.pending(), 1)
        group.request_stop_all()
        group.close(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(group.pending(), 0)
        group.close()
        with self.assertRaises(LifecycleError):
            group.start(Thread(target=lambda: None), lambda: None)

    def test_duplicate_named_worker_is_not_started(self):
        group, stopped = WorkerGroup(), Event()
        first = Thread(target=stopped.wait, name='same')
        second = Thread(target=stopped.wait, name='same')
        group.start(first, stopped.set)
        try:
            with self.assertRaises(LifecycleError):
                group.start(second, stopped.set)
            self.assertIsNone(second.ident)
        finally:
            group.close(timeout=2)

    def test_timeout_and_cancel_failure_are_reported_and_test_releases_threads(self):
        for fail_cancel in (False, True):
            with self.subTest(fail_cancel=fail_cancel):
                group, stopped = WorkerGroup(), Event()
                worker = Thread(target=stopped.wait)

                def cancel(fail_cancel=fail_cancel):
                    if fail_cancel:
                        raise RuntimeError('private details')

                group.start(worker, cancel)
                try:
                    with self.assertRaisesRegex(LifecycleError, '^background_workers_not_released$'):
                        group.close(timeout=0.01)
                    self.assertTrue(worker.is_alive())
                finally:
                    stopped.set()
                    worker.join(2)
                self.assertFalse(worker.is_alive())

    def test_completed_work_is_pruned_before_next_start(self):
        group = WorkerGroup()
        worker = Thread(target=lambda: None, name='quick')
        group.start(worker, lambda: None)
        worker.join(2)
        self.assertEqual(group.pending(), 0)
        next_worker = Thread(target=lambda: None, name='quick')
        group.start(next_worker, lambda: None)
        group.close(timeout=2)
