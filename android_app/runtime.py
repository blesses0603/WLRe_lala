"""Private Unix socket bridge between Android Activity and service process.

The socket lives in getNoBackupFilesDir (0700). No TCP listener or credentials
on disk. Events are retained as current state, so Activity recreation can attach.
"""
import json
import os
import queue
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace

MAX_FRAME = 1024 * 1024


def receive(stream):
    line = stream.readline(MAX_FRAME + 1)
    if not line or len(line) > MAX_FRAME: raise ValueError('Invalid IPC frame')
    return json.loads(line)


def send(stream, value):
    data = json.dumps(value, ensure_ascii=False).encode() + b'\n'
    if len(data) > MAX_FRAME: raise ValueError('IPC frame too large')
    stream.write(data)
    stream.flush()


class Runtime:
    def __init__(self, manager, monitor=None):
        self.manager = manager
        self.latest = {}
        self.monitor = monitor or (lambda: {})
        self.exit_requested = False

    def dispatch(self, request):
        operation = request.get('op')
        if operation == 'start':
            session = self.manager.start(**request['args'])
            return {'id': session.session_id}
        if operation == 'select': return self.manager.select_role(request['id'], request['index'])
        if operation == 'stop': return self.manager.stop(request['id'])
        if operation == 'remove':
            result = self.manager.remove(request['id'])
            if result: self.latest.pop(request['id'], None)
            return result
        if operation == 'shutdown':
            self.manager.stop_all()
            self.exit_requested = True
            return True
        if operation != 'poll': raise ValueError('Unknown IPC operation')
        self.collect_events()
        sessions = []
        with self.manager.lock:
            for sid, session in self.manager.sessions.items():
                with session.lock:
                    sessions.append(dict(id=sid, label=session.label, account=session.account,
                        active=session.active, phase=session.phase, pending=session.selection_pending,
                        stopped=session.stop_event.is_set(), events=self.latest.get(sid, {})))
        return {'sessions': sessions, 'metrics': self.monitor()}

    def collect_events(self):
        while True:
            try: sid, kind, value = self.manager.events.get_nowait()
            except queue.Empty: break
            state = self.latest.setdefault(sid, {})
            state[kind] = value
            if kind == 'roles': state.pop('snapshot', None)
            if kind == 'finished': state.pop('roles', None)

    def serve(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX)
        try:
            server.bind(str(path))
            os.chmod(path, 0o600)
            server.listen(4)
            server.settimeout(1)
            while not self.exit_requested:
                try: client, _ = server.accept()
                except socket.timeout:
                    self.collect_events()
                    self.monitor()
                    continue
                with client:
                    client.settimeout(2)
                    try:
                        with client.makefile('rwb') as stream:
                            request = receive(stream)
                            try: result = {'ok': True, 'value': self.dispatch(request)}
                            except Exception: result = {'ok': False, 'error': '操作失敗，請確認帳號及連線狀態'}
                            send(stream, result)
                    except (OSError, ValueError): pass
        finally:
            self.manager.stop_all()
            server.close()
            path.unlink(missing_ok=True)


class LatestEvents:
    """Coalesce per-account UI state while Android pauses the rendering loop."""
    def __init__(self):
        self.values = {}
        self.lock = threading.Lock()

    def put(self, event):
        with self.lock:
            key = (event[0], event[1])
            # Refresh insertion order so terminal state is always applied last.
            self.values.pop(key, None)
            self.values[key] = event

    def get_nowait(self):
        with self.lock:
            if not self.values: raise queue.Empty
            key = next(iter(self.values))
            return self.values.pop(key)


class ServiceManager:
    """UI adapter. Socket calls run off the Kivy thread; no network sessions here."""
    background = True

    def __init__(self, path):
        self.path = str(path)
        self.sessions = {}
        self.events = LatestEvents()
        self.requests = queue.Queue()
        self.metrics = {}
        self.available = False
        self._last = {}
        threading.Thread(target=self._work, daemon=True, name='service-ui-bridge').start()

    def call(self, request):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(self.path)
            with client.makefile('rwb') as stream:
                send(stream, request)
                reply = receive(stream)
        if not reply['ok']: raise ValueError(reply['error'])
        return reply['value']

    def _work(self):
        while True:
            try:
                try: request = self.requests.get(timeout=0.5)
                except queue.Empty: request = None
                if request:
                    try: self.call(request)
                    except ValueError:
                        self.events.put(('', 'error', '操作失敗，請確認帳號或連線狀態'))
                data = self.call({'op': 'poll'})
                self.metrics = data['metrics']
                if not self.available: self._last.clear()
                self.available = True
                present = set()
                for row in data['sessions']:
                    sid = row['id']
                    present.add(sid)
                    flag = threading.Event()
                    if row['stopped']: flag.set()
                    previous = self.sessions.get(sid)
                    if previous and previous.selection_pending != row['pending']:
                        self._last.pop((sid, 'roles'), None)
                    self.sessions[sid] = SimpleNamespace(session_id=sid, label=row['label'], account=row['account'],
                        active=row['active'], phase=row['phase'], selection_pending=row['pending'], stop_event=flag)
                    for kind, value in row['events'].items():
                        key = (sid, kind)
                        if self._last.get(key) != value:
                            self._last[key] = value
                            self.events.put((sid, kind, value))
                for sid in set(self.sessions) - present:
                    self.sessions.pop(sid, None)
                    self.events.put((sid, 'removed', None))
                    self._last = {k: v for k, v in self._last.items() if k[0] != sid}
            except (OSError, ValueError, KeyError):
                self.available = False
                self.metrics = {}
                time.sleep(0.5)

    def start(self, **args):
        if not self.available: raise ValueError('背景服務尚未就緒，請稍候')
        self.requests.put({'op': 'start', 'args': args})
        return None

    def select_role(self, sid, index):
        session = self.sessions.get(sid)
        if not self.available or not session or session.selection_pending: return False
        session.selection_pending = True
        self.requests.put({'op': 'select', 'id': sid, 'index': index})
        return True

    def stop(self, sid):
        self.requests.put({'op': 'stop', 'id': sid})
        return True

    def remove(self, sid):
        self.requests.put({'op': 'remove', 'id': sid})
        return False  # Removal is confirmed by the next service snapshot.

    def stop_all(self):
        for sid in list(self.sessions): self.stop(sid)
