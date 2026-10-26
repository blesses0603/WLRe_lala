"""P4 second batch: preserve App event-session API and Tk-only lifecycle."""
import queue
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock

from wlre.ui.gui import App
from wlre.ui.session_event_coordinator import SessionEventCoordinator


class SessionEventCoordinatorTests(unittest.TestCase):
    def test_app_keeps_original_poll_once_contract(self):
        self.assertIs(App._poll_once, SessionEventCoordinator._poll_once)
        self.assertTrue(callable(App.poll))

    def test_session_finished_restores_login_without_reconnecting(self):
        events = queue.Queue()
        events.put(('session_finished', None))
        app = SimpleNamespace(
            events=events, live_active=True, hide_all_features=Mock(),
            password=Mock(), update_role_choices=Mock(),
            show_login=Mock(), _set_login_gate_button=Mock(),
            start_version_check=Mock(), send=Mock(), status=Mock())
        App._poll_once(app)
        self.assertFalse(app.live_active)
        app.hide_all_features.assert_called_once_with()
        app.password.set.assert_called_once_with('')
        self.assertEqual(app.update_role_choices.call_count, 2)
        app.update_role_choices.assert_called_with([])
        app.show_login.assert_called_once_with()
        app._set_login_gate_button.assert_called_once_with()
        app.start_version_check.assert_called_once_with()
        app.send.assert_not_called()

    def test_last_state_passed_to_render_without_writing_game_state(self):
        events = queue.Queue()
        events.put(('state', {'phase': 'connected', 'value': 1}))
        events.put(('state', {'phase': 'authenticated', 'value': 2}))
        app = SimpleNamespace(events=events, render=Mock(),
                              live_active=False, status=Mock())
        App._poll_once(app)
        app.render.assert_called_once_with(
            {'phase': 'authenticated', 'value': 2})

    def test_event_order_and_chat_context_from_same_queue(self):
        events = queue.Queue()
        snapshot = {'player': {'scene': 10000}}
        update = {'player': {'scene': 11016}}
        message = {'type': 'chat_notice', 'text': 'hello'}
        events.put(('state', update))
        events.put(('event', message))
        app = SimpleNamespace(
            events=events, snapshot=snapshot, chat_panel=Mock(),
            attribute_window=None, crafting_panel=Mock(),
            expedition_panel=Mock(), write=Mock(), status=Mock(),
            render=Mock(), live_active=False)
        App._poll_once(app)
        app.chat_panel.handle_event.assert_called_once_with(message, update)
        app.render.assert_called_once_with(update)
        self.assertEqual(app.snapshot, snapshot)

    def test_late_health_telemetry_never_becomes_game_state(self):
        events = queue.Queue()
        health = {'status': 'connected', 'age': 1}
        events.put(('health', health))
        app = SimpleNamespace(events=events, connection_monitor=Mock(),
                              snapshot={'player': {'scene': 10000}},
                              status=Mock(), render=Mock())
        App._poll_once(app)
        app.connection_monitor.update.assert_called_once_with(health)
        app.render.assert_not_called()
        self.assertEqual(app.snapshot['player']['scene'], 10000)


if __name__ == '__main__':
    unittest.main()
