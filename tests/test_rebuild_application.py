"""核心生命週期與失敗回復；不依賴遊戲帳號或桌面環境。"""
import io
import logging
import unittest
from dataclasses import dataclass
from threading import Event, Thread

from wlre.core.application import (
    Application,
    ApplicationConfiguration,
    Lifecycle,
    LifecycleError,
    ManagedModule,
    ModuleSpec,
)
from wlre.core.application.diagnostics import DiagnosticLog
from wlre.core.application.state import StateManager


@dataclass(frozen=True)
class Notice:
    value: int


class API:
    def status(self):
        return 'ready'

    def private_action(self):
        raise AssertionError('not public')


class Probe(ManagedModule):
    def __init__(self, name, trace, *, dependencies=(), failure=None):
        super().__init__(ModuleSpec(name, '驗證初始化與關閉契約', ('status',), dependencies), api=API())
        self.trace, self.failure = trace, failure
        self.context = None

    def on_initialize(self, context):
        self.context = context
        self.trace.append((self.spec.name, 'initialize'))
        self.own(self.trace.append, (self.spec.name, 'release'))
        if self.failure == 'initialize':
            raise RuntimeError('password=DO_NOT_RECORD')

    def on_ready(self):
        self.trace.append((self.spec.name, 'ready'))
        if self.failure == 'ready':
            raise RuntimeError('bad resource')

    def on_start(self):
        self.trace.append((self.spec.name, 'start'))
        if self.failure == 'start':
            raise RuntimeError('bad start')

    def on_stop(self):
        self.trace.append((self.spec.name, 'stop'))
        if self.failure == 'stop':
            raise RuntimeError('bad stop')


class ApplicationTests(unittest.TestCase):
    def test_dependency_order_api_lifecycle_and_reverse_release(self):
        trace = []
        first, second = Probe('first', trace), Probe('second', trace, dependencies=('first',))
        app = Application([second, first])
        saved_method = first.api.status
        with self.assertRaises(LifecycleError):
            saved_method()
        with self.assertRaises(AttributeError):
            first.api.private_action()
        with self.assertRaises(LifecycleError):
            first.start()
        app.initialize()
        self.assertEqual(app.state, Lifecycle.READY)
        self.assertEqual(app.modules.order, ('first', 'second'))
        self.assertEqual(second.context.dependencies['first'].status(), 'ready')
        with self.assertRaises(TypeError):
            second.context.dependencies['unlisted'] = API()
        self.assertEqual(saved_method(), 'ready')
        app.start()
        self.assertEqual(app.state, Lifecycle.RUNNING)
        self.assertTrue(all(s is Lifecycle.RUNNING for s in app.modules.statuses().values()))
        app.stop()
        app.stop()
        self.assertEqual(app.state, Lifecycle.STOPPED)
        self.assertEqual(trace[-4:], [('second', 'stop'), ('second', 'release'),
                                     ('first', 'stop'), ('first', 'release')])
        with self.assertRaises(LifecycleError):
            saved_method()

    def test_unknown_duplicate_and_cyclic_dependencies_before_side_effects(self):
        for setup in ('unknown', 'duplicate', 'cycle'):
            with self.subTest(setup=setup):
                trace = []
                modules = ([Probe('one', trace, dependencies=('missing',))] if setup == 'unknown'
                           else [Probe('one', trace), Probe('one', trace)] if setup == 'duplicate'
                           else [Probe('one', trace, dependencies=('two',)),
                                 Probe('two', trace, dependencies=('one',))])
                with self.assertRaises(LifecycleError):
                    Application(modules)
                self.assertEqual(trace, [])

    def test_failed_initialize_ready_and_start_roll_back_all_resources(self):
        for failure in ('initialize', 'ready', 'start'):
            with self.subTest(failure=failure):
                trace = []
                first = Probe('first', trace)
                broken = Probe('broken', trace, dependencies=('first',), failure=failure)
                never = Probe('never', trace, dependencies=('broken',))
                app = Application([never, broken, first])
                with self.assertRaises(LifecycleError) as raised:
                    app.initialize()
                    app.start()
                self.assertNotIn('DO_NOT_RECORD', str(raised.exception))
                self.assertEqual(app.state, Lifecycle.FAILED)
                self.assertEqual(broken.state, Lifecycle.FAILED)
                self.assertEqual(trace.count(('broken', 'release')), 1)
                self.assertEqual(trace.count(('first', 'release')), 1)
                self.assertEqual(app.events.subscriber_count, 0)
                self.assertEqual(dict(app.states.snapshot()), {})
                self.assertNotIn('DO_NOT_RECORD', repr(app.diagnostics.snapshot()))
                app.stop()
                with self.assertRaises(LifecycleError):
                    app.start()

    def test_stop_failure_does_not_prevent_other_cleanup_and_is_not_success(self):
        trace = []
        first = Probe('first', trace)
        broken = Probe('broken', trace, failure='stop', dependencies=('first',))
        app = Application([first, broken])
        app.initialize()
        app.start()
        with self.assertRaises(LifecycleError):
            app.stop()
        self.assertEqual(app.state, Lifecycle.FAILED)
        self.assertIn(('first', 'release'), trace)
        self.assertIn(('broken', 'release'), trace)
        app.stop()

    def test_shutdown_quiesces_dependency_apis_before_cleanup_begins(self):
        blocked = []

        class Consumer(Probe):
            def on_stop(self):
                try:
                    self.context.dependencies['source'].status()
                except LifecycleError:
                    blocked.append(True)

        trace = []
        app = Application([Probe('source', trace),
                           Consumer('consumer', trace, dependencies=('source',))])
        app.initialize()
        app.start()
        app.stop()
        self.assertEqual(blocked, [True])

    def test_cleanup_failure_still_runs_remaining_callbacks(self):
        trace = []
        module = Probe('one', trace)
        app = Application([module])
        app.initialize()

        def fail():
            raise RuntimeError('cleanup failure')

        module.own(fail)
        module.own(trace.append, ('one', 'last_cleanup'))
        with self.assertRaises(LifecycleError):
            app.stop()
        self.assertEqual(trace[-2:], [('one', 'last_cleanup'), ('one', 'release')])

    def test_owned_worker_and_event_subscription_are_released(self):
        class WorkerModule(Probe):
            def on_initialize(self, context):
                super().on_initialize(context)
                self.stop_requested = Event()
                self.worker = Thread(target=self.stop_requested.wait)
                self.own(context.events.subscribe(Notice, lambda event: None).close)
                self.own_worker(self.worker, self.stop_requested.set)
                self.worker.start()

        module = WorkerModule('worker', [])
        app = Application([module])
        app.initialize()
        app.start()
        self.assertTrue(module.worker.is_alive())
        self.assertEqual(app.events.subscriber_count, 1)
        app.stop()
        self.assertFalse(module.worker.is_alive())
        self.assertEqual(app.events.subscriber_count, 0)

    def test_worker_timeout_is_failed_shutdown_and_test_releases_worker(self):
        trace, stopped = [], Event()
        module = Probe('worker', trace)
        app = Application([module])
        app.initialize()
        worker = Thread(target=stopped.wait)
        module.own_worker(worker, lambda: None, timeout=0.01)
        worker.start()
        try:
            with self.assertRaises(LifecycleError):
                app.stop()
            self.assertEqual(app.state, Lifecycle.FAILED)
            self.assertTrue(worker.is_alive())
        finally:
            stopped.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_pump_is_bounded_and_only_available_while_running(self):
        app = Application(configuration=ApplicationConfiguration(4, 2))
        seen = []
        with self.assertRaises(LifecycleError):
            app.pump()
        app.initialize()
        app.start()
        app.events.subscribe(Notice, lambda event: seen.append(event.value))
        for n in range(3):
            app.events.post(Notice(n))
        self.assertEqual(app.pump(), 2)
        self.assertEqual(seen, [0, 1])
        app.stop()
        with self.assertRaises(LifecycleError):
            app.pump()

    def test_recursive_stop_during_start_fails_and_rolls_back(self):
        class Recursive(Probe):
            def on_start(self):
                app.stop()

        trace = []
        app = Application([Recursive('recursive', trace)])
        app.initialize()
        with self.assertRaises(LifecycleError):
            app.start()
        self.assertEqual(app.state, Lifecycle.FAILED)
        self.assertIn(('recursive', 'release'), trace)

    def test_cross_thread_application_and_projection_access_rejected(self):
        app, failures = Application(), []

        def other_thread():
            for action in (app.initialize, app.stop, app.states.snapshot):
                try:
                    action()
                except RuntimeError:
                    failures.append(True)

        worker = Thread(target=other_thread)
        worker.start()
        worker.join(2)
        self.assertEqual(failures, [True, True, True])
        self.assertEqual(app.state, Lifecycle.CREATED)
        app.stop()

    def test_module_resources_cannot_be_started_before_initialize(self):
        module = Probe('one', [])
        with self.assertRaises(LifecycleError):
            module.own(lambda: None)


class ConfigurationAndProjectionTests(unittest.TestCase):
    def test_invalid_configuration_and_module_contracts(self):
        with self.assertRaises(TypeError):
            Application(configuration=False)
        with self.assertRaises(TypeError):
            Application(diagnostics={})
        for args in ((0, 1), (4, 5), (True, 1), (4, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ApplicationConfiguration(*args)
        with self.assertRaises(ValueError):
            ModuleSpec('bad/name', '責任', ('status',))
        with self.assertRaises(ValueError):
            ModuleSpec('valid', '', ('status',))
        with self.assertRaises(TypeError):
            ManagedModule(ModuleSpec('valid', '責任', ('missing',)), api=API())

    def test_projection_revisions_and_detached_immutable_snapshot(self):
        states = StateManager()
        states.replace('battle', Notice(1), revision=2)
        before = states.snapshot()
        with self.assertRaises(TypeError):
            before['other'] = None
        for revision in (1, 2, -1, True):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                states.replace('battle', Notice(5), revision=revision)
        with self.assertRaises(TypeError):
            states.replace('battle', {'value': 4}, revision=3)
        states.replace('battle', Notice(2), revision=3)
        self.assertEqual(before['battle'].value, Notice(1))
        states.close()
        self.assertEqual(before['battle'].revision, 2)
        with self.assertRaises(RuntimeError):
            states.replace('battle', Notice(3), revision=4)

    def test_diagnostics_are_bounded_and_never_format_exception_payloads(self):
        output = io.StringIO()
        logger = logging.Logger('test_core_log')  # noqa: LOG001 -- 此測試必須隔離全域 logger。
        logger.addHandler(logging.StreamHandler(output))
        diagnostics = DiagnosticLog(2, logger=logger)
        for i in range(3):
            diagnostics.record('application', 'counter', count=i)
        self.assertEqual(len(diagnostics.snapshot()), 2)
        with self.assertRaises(TypeError):
            diagnostics.record('application', 'failed', password='secret')
        with self.assertRaises(ValueError):
            diagnostics.record('application', 'token=secret')
        self.assertNotIn('secret', output.getvalue())
        diagnostics.close()
        diagnostics.record('application', 'late')
        self.assertEqual(diagnostics.snapshot()[-1].counters, (('count', 2),))
