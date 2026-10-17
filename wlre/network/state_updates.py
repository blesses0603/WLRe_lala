"""Coalesce display snapshots; protocol processing and events remain immediate."""
import time


class StatePublisher:
    def __init__(self,callback,interval,clock=time.monotonic):
        self.callback=callback
        self.interval=interval
        self.clock=clock
        self.last=None
        self.pending=False

    def publish(self,state,force=False):
        self.pending=True
        now=self.clock()
        if force or self.last is None or now-self.last>=self.interval:
            snapshot=state.snapshot()
            self.callback(snapshot)
            self.last=self.clock()
            self.pending=False

    def flush(self,state):
        if self.pending:self.publish(state)


def notify_state(callback,state,force=False):
    if isinstance(callback,StatePublisher):callback.publish(state,force=force)
    elif callback:callback(state.snapshot())
