"""Worker callbacks bound to one session mailbox, with no Tk or App access."""
import copy


class SessionBridge:
    def __init__(self,events):self.events=events
    def receive(self,event):
        self.events.put(('health' if event.get('type')=='connection_health' else 'event',copy.deepcopy(event)))
    def snapshot(self,value):self.events.put(('state',value))
    def finished(self):self.events.put(('session_finished',None))
