"""Android sessions use fake runners only; never connect to a game server."""
import queue
import threading
import unittest
from unittest.mock import patch

from android_app.sessions import SessionManager
from wlre.core.state import State


class AndroidSessions(unittest.TestCase):
    def setUp(self):
        self.manager = SessionManager()
        self.release = threading.Event()
        self.ready = threading.Event()
        self.calls = []
        self.patch = patch('wlre.network.client.run_client', self.runner)
        self.patch.start()
        self.addCleanup(self.cleanup)

    def runner(self, host, port, profile, emit, **kwargs):
        self.calls.append((emit, kwargs))
        emit({'type': 'role_list_available', 'roles': [
            dict(index=1, name='測試', level=14, locked=False),
            dict(index=2, name='鎖定', level=10, locked=True)]})
        self.ready.set(); self.release.wait(5)

    def start(self, account='fixture-user', password='fixture-secret'):
        session = self.manager.start(label='fixture', host='fixture.invalid', port=1234,
                                     account=account, password=password)
        self.assertTrue(self.ready.wait(2))
        return session

    def cleanup(self):
        self.release.set(); self.manager.stop_all()
        for session in list(self.manager.sessions.values()):
            if session.worker: session.worker.join(2)
        self.patch.stop()

    def drain(self):
        events = []
        while not self.manager.events.empty(): events.append(self.manager.events.get_nowait())
        return events

    def test_verify_first_and_isolated_commands(self):
        first = self.start()
        self.ready.clear(); second = self.start('second-user')
        self.assertIsNot(first.commands, second.commands)
        self.assertIsNot(first.stop_event, second.stop_event)
        self.assertTrue(self.calls[0][1]['verify_first'])
        self.assertIsNone(self.calls[0][1]['duration'])
        self.manager.stop(first.session_id)
        self.assertTrue(first.stop_event.is_set())
        self.assertFalse(second.stop_event.is_set())

    def test_locked_and_duplicate_selections_are_not_sent(self):
        session = self.start()
        payload = next(value for _, kind, value in self.drain() if kind == 'roles')
        self.assertTrue(payload[1]['locked'])
        self.assertFalse(self.manager.select_role(session.session_id, 2))
        self.assertFalse(self.manager.select_role(session.session_id, 99))
        self.assertTrue(self.manager.select_role(session.session_id, 1))
        self.assertFalse(self.manager.select_role(session.session_id, 1))
        self.assertEqual(session.commands.get_nowait(), {'type': 'select_role', 'index': 1})
        self.assertTrue(session.commands.empty())

    def test_duplicate_live_account_is_rejected(self):
        self.start()
        with self.assertRaises(ValueError): self.start()
        self.assertEqual(len(self.manager.sessions), 1)

    def test_snapshot_accepts_dict_and_preserves_unknowns_and_zero_sp(self):
        self.start(); self.drain()
        state = State().snapshot()
        state['phase'] = 'world_ready'
        state['player'] = dict(name='測試', scene=60000)
        state['knowledge']['player']['stats'] = dict(level=14, hp=20, max_hp=50, sp=0, max_sp=30)
        self.calls[0][1]['on_state'](state)
        snapshot = self.drain()[-1][2]
        self.assertEqual(snapshot['hp'], 20)
        self.assertEqual(snapshot['sp'], 0)
        self.assertIsNone(snapshot['position'])

    def test_stop_discards_late_state_and_role_events(self):
        session = self.start(); self.manager.stop(session.session_id); self.drain()
        self.calls[0][1]['on_state'](State().snapshot())
        self.calls[0][0]({'type': 'role_list_available', 'roles': []})
        self.assertFalse(self.drain())
        self.assertFalse(self.manager.select_role(session.session_id, 1))

    def test_rejection_allows_valid_retry(self):
        session = self.start(); self.manager.select_role(session.session_id, 1)
        self.calls[0][0]({'type': 'command_rejected', 'command_type': 'select_role'})
        self.assertTrue(self.manager.select_role(session.session_id, 1))

    def test_failure_reason_is_terminal_and_never_contains_exception_text(self):
        def fail(*args, **kwargs): raise RuntimeError(repr(kwargs['password']))
        with patch('wlre.network.client.run_client', fail):
            session = self.manager.start(label='fixture', host='fixture.invalid', port=1234,
                account='fixture-user', password='secret\nvalue')
            session.worker.join(2)
        events = self.drain()
        self.assertEqual(events[-1][1], 'finished')
        self.assertIn('連線流程發生錯誤', events[-1][2])
        self.assertNotIn('secret', str(events))
        self.assertFalse(session.active)

    def test_only_finished_connections_can_be_removed(self):
        session = self.start()
        self.assertFalse(self.manager.remove(session.session_id))
        self.release.set(); session.worker.join(2)
        self.assertTrue(self.manager.remove(session.session_id))
        self.assertFalse(self.manager.sessions)

    def test_invalid_input_does_not_start_session(self):
        for args in (dict(account='', password='x', port=1234),
                     dict(account='user', password='', port=1234),
                     dict(account='user', password='x', port='1234')):
            with self.assertRaises(ValueError):
                self.manager.start(label='fixture', host='fixture.invalid', **args)
        self.assertFalse(self.manager.sessions)
