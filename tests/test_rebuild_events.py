"""新事件核心：真實執行緒、順序、背壓、關閉及失敗隔離。"""
import queue
import unittest
from dataclasses import dataclass
from threading import Thread

from wlre.core.application.diagnostics import DiagnosticLog
from wlre.core.events import EventBus


@dataclass(frozen=True)
class Tick:
    value: int


@dataclass(frozen=True)
class Other:
    value: int


class EventBusTests(unittest.TestCase):
    def test_exact_type_order_and_idempotent_subscription(self):
        bus, seen = EventBus(), []
        first = lambda event: seen.append(('first', event.value))
        subscription = bus.subscribe(Tick, first)
        self.assertIs(bus.subscribe(Tick, first), subscription)
        bus.subscribe(Tick, lambda event: seen.append(('second', event.value)))
        bus.subscribe(Other, lambda event: self.fail('wrong event type'))
        self.assertEqual(bus.publish(Tick(1)), 2)
        subscription.close()
        subscription.close()
        self.assertEqual(bus.publish(Tick(2)), 1)
        self.assertEqual(seen, [('first', 1), ('second', 1), ('second', 2)])
        self.assertEqual(bus.sequence, 2)

    def test_failure_and_recursive_publish_are_isolated_without_payload_logging(self):
        diagnostics, seen = DiagnosticLog(), []
        bus = EventBus(record=diagnostics.record)

        def fail(_):
            raise RuntimeError('token=NEVER_LOG_THIS')

        bus.subscribe(Tick, fail)
        bus.subscribe(Tick, lambda event: bus.publish(event))
        bus.subscribe(Tick, lambda event: seen.append(event.value))
        self.assertEqual(bus.publish(Tick(4)), 1)
        self.assertEqual(seen, [4])
        self.assertEqual([r.code for r in diagnostics.snapshot()].count('handler_failed'), 2)
        self.assertNotIn('NEVER_LOG_THIS', repr(diagnostics.snapshot()))

    def test_unsubscribe_during_dispatch_and_new_handler_waits(self):
        bus, seen, late = EventBus(), [], None

        def first(_):
            nonlocal late
            second.close()
            if late is None:
                late = bus.subscribe(Tick, lambda event: seen.append('late'))

        bus.subscribe(Tick, first)
        second = bus.subscribe(Tick, lambda event: seen.append('second'))
        bus.publish(Tick(0))
        self.assertEqual(seen, [])
        bus.publish(Tick(0))
        self.assertEqual(seen, ['late'])

    def test_background_post_only_dispatches_on_owner_and_has_backpressure(self):
        bus, seen, errors = EventBus(2), [], []
        bus.subscribe(Tick, lambda event: seen.append(event.value))

        def producer():
            for n in range(2):
                bus.post(Tick(n))
            try:
                bus.post(Tick(2))
            except queue.Full:
                errors.append('full')
            try:
                bus.publish(Tick(3))
            except RuntimeError:
                errors.append('wrong_thread')

        worker = Thread(target=producer)
        worker.start()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(seen, [])
        self.assertEqual(errors, ['full', 'wrong_thread'])
        self.assertEqual(bus.drain(1), 1)
        self.assertEqual(seen, [0])
        self.assertEqual(bus.drain(5), 1)
        self.assertEqual(seen, [0, 1])

    def test_close_clears_pending_and_subscriptions_and_rejects_late_work(self):
        bus = EventBus()
        subscription = bus.subscribe(Tick, lambda event: self.fail('late dispatch'))
        bus.post(Tick(1))
        bus.close()
        bus.close()
        subscription.close()
        self.assertEqual(bus.subscriber_count, 0)
        for operation in (lambda: bus.post(Tick(2)), lambda: bus.publish(Tick(2)),
                          lambda: bus.subscribe(Tick, lambda event: None), bus.drain):
            with self.assertRaises(RuntimeError):
                operation()

    def test_close_inside_handler_stops_current_dispatch(self):
        bus = EventBus()
        bus.subscribe(Tick, lambda event: bus.close())
        bus.subscribe(Tick, lambda event: self.fail('handler after close'))
        self.assertEqual(bus.publish(Tick(1)), 1)

    def test_reposting_handler_cannot_make_drain_unbounded(self):
        bus, seen = EventBus(), []
        bus.subscribe(Tick, lambda event: (seen.append(event.value), bus.post(Tick(event.value + 1))))
        bus.post(Tick(0))
        self.assertEqual(bus.drain(3), 3)
        self.assertEqual(seen, [0, 1, 2])
        bus.close()

    def test_mutable_or_untyped_events_and_nonfinite_values_rejected(self):
        @dataclass(frozen=True)
        class Unsafe:
            value: object

        bus = EventBus()
        with self.assertRaises(TypeError):
            bus.subscribe(dict, lambda event: None)
        for value in ([], {}, object(), float('nan'), float('inf')):
            with self.subTest(value=type(value)), self.assertRaises(TypeError):
                bus.post(Unsafe(value))
        with self.assertRaises(ValueError):
            bus.post(Unsafe(('a' * 600000, 'b' * 600000)))
        with self.assertRaises(ValueError):
            bus.drain(0)

    def test_foreign_subscription_is_rejected(self):
        bus, other = EventBus(), EventBus()
        subscription = bus.subscribe(Tick, lambda event: None)
        with self.assertRaises(ValueError):
            other.unsubscribe(subscription)
