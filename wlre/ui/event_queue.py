"""Nonblocking display mailbox. Game processing never waits on Tk rendering."""
from collections import OrderedDict, deque
import queue
import threading
import time
from wlre.core.maintenance import PeriodicCleanup


class DisplayQueue:
    def __init__(self, limit=1024, clock=time.monotonic):
        self.limit = limit; self.normal = deque(); self.latest = OrderedDict()
        self.lock = threading.Lock(); self.dropped = 0
        self.clock = clock; self.cleanup_timer = PeriodicCleanup(clock)

    def put(self, item):
        kind, value = item
        key = kind if kind in ('state', 'health', 'error', 'finished', 'session_finished') else None
        if kind == 'event' and value.get('type') in ('connection_closed', 'chat_sent', 'chat_result', 'command_rejected'):
            key = ('event', value['type'])
        with self.lock:
            if key is not None: self.latest[key] = item
            else:
                if len(self.normal) >= self.limit: self.normal.popleft(); self.dropped += 1
                self.normal.append((self.clock(), item))

    def get_nowait(self):
        with self.lock:
            # Fresh state and liveness must not sit behind old display messages.
            for key in ('health', 'state'):
                if key in self.latest: return self.latest.pop(key)
            if self.normal: return self.normal.popleft()[1]
            if self.latest: return self.latest.popitem(last=False)[1]
        raise queue.Empty

    def cleanup(self):
        with self.lock:
            if not self.cleanup_timer.due(): return None
            cutoff = self.clock() - 120
            # Only obsolete display telemetry; never chat, invitations or controls.
            disposable = {'walk', 'position_snapshot', 'attribute_set'}
            before = len(self.normal)
            self.normal = deque((stamp, item) for stamp, item in self.normal
                if not (stamp < cutoff and item[0] == 'event'
                        and item[1].get('type') in disposable))
            return before - len(self.normal)

    def qsize(self):
        with self.lock: return len(self.normal)+len(self.latest)

    def empty(self): return self.qsize() == 0

    def take_dropped(self):
        with self.lock:
            count = self.dropped; self.dropped = 0; return count
