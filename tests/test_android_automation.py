"""Exercise real Android adapters with isolated fake connections and storage."""
import unittest
import tempfile
from pathlib import Path
from tests import test_android_sessions as fixtures
from android_app.sessions import SessionManager
from android_app.runtime import Runtime
from wlre.services.battle.auto_battle import defaults
from wlre.core.state import State


class AndroidAutomation(unittest.TestCase):
    setUp = fixtures.AndroidSessions.setUp
    start = fixtures.AndroidSessions.start
    runner = fixtures.AndroidSessions.runner
    cleanup = fixtures.AndroidSessions.cleanup
    drain = fixtures.AndroidSessions.drain

    def test_commands_require_world_and_wait_for_core_acknowledgement(self):
        session = self.start()
        sid = session.session_id
        self.assertFalse(self.manager.automation_command(sid, 'battle', True))
        state = State().snapshot(); state['phase'] = 'world_ready'
        self.calls[0][1]['on_state'](state)
        self.assertTrue(self.manager.automation_command(sid, 'battle', True))
        self.assertFalse(self.manager.automation_command(sid, 'battle', True))
        command = session.commands.get_nowait()
        self.assertEqual(command['type'], 'start_auto_battle')
        self.assertEqual(command['settings'], defaults())
        self.assertFalse(session.automation['battle']['enabled'])
        self.calls[0][0]({'type': 'auto_battle_status', 'enabled': True, 'status': 'armed'})
        self.assertTrue(session.automation['battle']['enabled'])
        self.assertTrue(self.manager.automation_command(sid, 'battle', False))
        self.assertEqual(session.commands.get_nowait()['type'], 'stop_auto_battle')
        self.manager.stop(sid)
        self.assertFalse(self.manager.automation_command(sid, 'roaming', True))

    def test_roaming_rejection_and_independent_account_commands(self):
        first = self.start(); self.ready.clear(); second = self.start('other')
        first.phase = second.phase = 'world_ready'
        runtime = Runtime(self.manager)
        self.assertTrue(runtime.dispatch(dict(op='automation', id=first.session_id, feature='roaming', enabled=True)))
        self.assertTrue(second.commands.empty())
        self.assertEqual(first.commands.get_nowait(), {'type': 'start_roaming'})
        self.calls[0][0]({'type': 'command_rejected', 'command_type': 'start_roaming', 'error': 'secret'})
        self.assertFalse(first.automation_pending)
        self.assertNotIn('secret', str(self.drain()))
        self.assertTrue(self.manager.automation_command(first.session_id, 'roaming', True))

    def test_settings_restore_per_account_and_server_and_survive_service_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            self.manager.settings_base = Path(directory)
            session = self.start()
            settings = defaults(); settings['bPlayerDieCloseAI'] = True
            self.assertTrue(self.manager.save_ai_settings(session.session_id, settings))
            settings['bPlayerDieCloseAI'] = False
            self.assertTrue(session.ai_settings['bPlayerDieCloseAI'])
            self.release.set(); session.worker.join(2)
            self.manager = SessionManager(settings_base=directory)
            restored = self.start()
            self.assertTrue(restored.ai_settings['bPlayerDieCloseAI'])
            other = self.start('different-user')
            self.assertFalse(other.ai_settings['bPlayerDieCloseAI'])
            files = list(Path(directory).rglob('*.json'))
            self.assertEqual(len(files), 1)
            self.assertNotIn('fixture-user', files[0].read_text())
            self.assertNotIn('fixture-secret', files[0].read_text())
            projected = Runtime(self.manager).dispatch({'op': 'poll'})
            self.assertTrue(projected['sessions'][0]['ai_settings']['bPlayerDieCloseAI'])
