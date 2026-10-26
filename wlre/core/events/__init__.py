"""型別事件：擁有者同步分派，背景執行緒只能送入有界 mailbox。"""
from __future__ import annotations

import queue
from collections.abc import Callable
from dataclasses import is_dataclass
from threading import Lock
from typing import TypeVar

from wlre.core.primitives import Owned, require_immutable

T = TypeVar('T')


class Subscription:
    """可重複 close；重複訂閱同一 callback 取得同一份訂閱。"""

    def __init__(self, bus, token):
        self._bus = bus
        self._token = token

    def close(self):
        self._bus.unsubscribe(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _event_type(event_type):
    if (not isinstance(event_type, type) or not is_dataclass(event_type)
            or not event_type.__dataclass_params__.frozen):
        raise TypeError('event_requires_frozen_dataclass')


class EventBus(Owned):
    def __init__(self, capacity=512, *, record=None):
        super().__init__()
        if type(capacity) is not int or not 1 <= capacity <= 65536:
            raise ValueError('invalid_event_capacity')
        self._mailbox = queue.Queue(maxsize=capacity)
        self._lock = Lock()
        self._closed = False
        self._dispatching = False
        self._next_token = 0
        self._subscriptions = {}
        self._sequence = 0
        self._record = record
        self.diagnostic_failures = 0

    def _note(self, code):
        if self._record is not None:
            try:
                self._record('events', code)
            except Exception:  # noqa: BLE001 -- 診斷 sink 為外部介面，故障不能再遞迴寫入紀錄。
                self.diagnostic_failures += 1

    def _open(self):
        if self._closed:
            raise RuntimeError('event_bus_closed')

    @property
    def sequence(self):
        self.assert_owner()
        return self._sequence

    @property
    def subscriber_count(self):
        self.assert_owner()
        return len(self._subscriptions)

    def subscribe(self, event_type: type[T], callback: Callable[[T], object]) -> Subscription:
        self.assert_owner()
        self._open()
        _event_type(event_type)
        if not callable(callback):
            raise TypeError('event_callback_not_callable')
        for kind, handler, subscription in self._subscriptions.values():
            if kind is event_type and handler == callback:
                return subscription
        self._next_token += 1
        subscription = Subscription(self, self._next_token)
        self._subscriptions[self._next_token] = (event_type, callback, subscription)
        return subscription

    def unsubscribe(self, subscription):
        self.assert_owner()
        if not isinstance(subscription, Subscription) or subscription._bus is not self:
            raise ValueError('subscription_belongs_to_other_bus')
        self._subscriptions.pop(subscription._token, None)

    def publish(self, event: object) -> int:
        self.assert_owner()
        self._open()
        _event_type(type(event))
        require_immutable(event)
        if self._dispatching:
            raise RuntimeError('recursive_event_dispatch_rejected')
        self._dispatching = True
        self._sequence += 1
        delivered = 0
        try:
            # 訂閱中新增 handler 要等下一次；取消訂閱立即生效。
            for token in tuple(self._subscriptions):
                if self._closed:
                    break
                row = self._subscriptions.get(token)
                if row is None or row[0] is not type(event):
                    continue
                try:
                    row[1](event)
                    delivered += 1
                except Exception:  # noqa: BLE001 -- 事件 handler 為隔離邊界，僅記錄固定錯誤碼。
                    self._note('handler_failed')
            self._note('event_dispatched')
        finally:
            self._dispatching = False
        return delivered

    def post(self, event: object) -> None:
        """執行緒安全且不阻塞；滿載會明確拋出 queue.Full，不靜默遺失。"""
        _event_type(type(event))
        require_immutable(event)
        with self._lock:
            self._open()
            self._mailbox.put_nowait(event)

    def drain(self, limit: int = 64) -> int:
        self.assert_owner()
        self._open()
        if type(limit) is not int or not 1 <= limit <= 65536:
            raise ValueError('invalid_event_drain_limit')
        if self._dispatching:
            raise RuntimeError('recursive_event_drain_rejected')
        count = 0
        while count < limit and not self._closed:
            try:
                event = self._mailbox.get_nowait()
            except queue.Empty:
                break
            self.publish(event)
            count += 1
        return count

    def close(self):
        self.assert_owner()
        with self._lock:
            self._closed = True
            self._subscriptions.clear()
            while True:
                try:
                    self._mailbox.get_nowait()
                except queue.Empty:
                    break
