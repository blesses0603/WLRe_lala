"""Monotonic maintenance deadlines, independent of wall-clock adjustments."""
import time

CLEANUP_INTERVAL = 2 * 60 * 60


class PeriodicCleanup:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.next_cleanup = clock() + CLEANUP_INTERVAL

    def due(self):
        now = self.clock()
        if now < self.next_cleanup:
            return False
        self.next_cleanup = now + CLEANUP_INTERVAL
        return True
