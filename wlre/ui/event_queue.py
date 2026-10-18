"""Nonblocking display mailbox. Game processing never waits on Tk rendering."""
from collections import OrderedDict, deque
import queue
import threading


class DisplayQueue:
    def __init__(self, limit=1024):
        self.limit = limit; self.normal = deque(); self.latest = OrderedDict()
        self.lock = threading.Lock(); self.dropped = 0

    def put(self, item):
        kind, value = item
        key = kind if kind in ('state', 'health', 'error', 'finished', 'session_finished') else None
        if kind == 'event' and value.get('type') in ('connection_closed', 'chat_sent', 'chat_result', 'command_rejected'):
            key = ('event', value['type'])
        with self.lock:
            if key is not None: self.latest[key] = item
            else:
                if len(self.normal) >= self.limit: self.normal.popleft(); self.dropped += 1
                self.normal.append(item)

    def get_nowait(self):
        with self.lock:
            # Fresh state and liveness must not sit behind old display messages.
            for key in ('health', 'state'):
                if key in self.latest: return self.latest.pop(key)
            if self.normal: return self.normal.popleft()
            if self.latest: return self.latest.popitem(last=False)[1]
        raise queue.Empty

    def qsize(self):
        with self.lock: return len(self.normal)+len(self.latest)

    def empty(self): return self.qsize() == 0

    def take_dropped(self):
        with self.lock:
            count = self.dropped; self.dropped = 0; return count
