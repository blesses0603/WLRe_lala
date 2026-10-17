import importlib.util
import os
import unittest
from unittest.mock import patch

HAS_KIVY = importlib.util.find_spec('kivy') is not None


@unittest.skipUnless(HAS_KIVY and (os.environ.get('DISPLAY') or os.name == 'nt'),
                     'Requires Kivy and a desktop display')
class AndroidUI(unittest.TestCase):
    def setUp(self):
        from android_app.app import LaLaApp
        from android_app.sessions import Session
        from kivy.clock import Clock
        self.app = LaLaApp(); self.root = self.app.build()
        self.addCleanup(lambda: Clock.unschedule(self.app.drain_events))
        self.session = Session('fixture', 'fixture', 'fixture-user', 'fixture.invalid', 1234)
        self.session.phase = 'role_selection'
        self.session.roles = [dict(index=1, name='測試', level=14, locked=False),
                              dict(index=2, name='鎖定', level=10, locked=True)]
        self.app.manager.sessions['fixture'] = self.session
        self.app.account.text = 'fixture-user'; self.app.password.text = 'fixture-secret'
        with patch.object(self.app.manager, 'start', return_value=self.session):
            self.app.connect_account()
        self.status, self.buttons, _, self.stop, _ = self.app.cards['fixture']

    def roles(self):
        self.app.manager.events.put(('fixture', 'roles', self.session.roles))
        self.app.drain_events()

    def test_chinese_font_is_used_and_has_distinct_glyphs(self):
        from kivy.core.text import Label
        from PIL import ImageFont
        label = Label(text='帳號'); label.resolve_font_name()
        font = ImageFont.truetype(label.options['font_name_r'], 32)
        self.assertNotEqual(bytes(font.getmask('帳')), bytes(font.getmask('號')))

    def test_locked_roles_and_pending_selection_stay_disabled(self):
        self.roles()
        self.assertFalse(self.buttons[1].disabled); self.assertTrue(self.buttons[2].disabled)
        self.app.choose_role('fixture', 1)
        self.assertTrue(all(button.disabled for button in self.buttons.values()))
        self.roles()
        self.assertTrue(all(button.disabled for button in self.buttons.values()))

    def test_finished_preserves_failure_and_allows_removal(self):
        self.session.active = False
        self.app.manager.events.put(('fixture', 'finished', '帳號驗證未通過'))
        self.app.drain_events()
        self.assertIn('帳號驗證未通過', self.status.text)
        self.assertTrue(all(button.disabled for button in self.buttons.values()))
        self.assertEqual(self.stop.text, '移除')
        self.app.remove_card('fixture')
        self.assertFalse(self.app.cards); self.assertFalse(self.app.manager.sessions)

    def test_snapshot_displays_hp_and_zero_sp_without_inventing_position(self):
        self.app.manager.events.put(('fixture', 'snapshot', dict(phase='world_ready', character='測試',
            level=14, hp=20, max_hp=50, sp=0, max_sp=30, scene=60000, position=None)))
        self.app.drain_events()
        self.assertIn('HP 20/50', self.status.text)
        self.assertIn('SP 0/30', self.status.text)
        self.assertIn('位置待同步', self.status.text)

    def test_pause_clears_password_and_prevents_late_role_enable(self):
        self.app.password.text = 'not-persisted'
        self.assertTrue(self.app.on_pause())
        self.assertEqual(self.app.password.text, '')
        self.assertTrue(self.session.stop_event.is_set())
        self.roles()
        self.assertTrue(all(button.disabled for button in self.buttons.values()))

    def test_android_pause_keeps_service_sessions(self):
        self.app.manager.background = True
        self.app.password.text = 'temporary'
        self.assertTrue(self.app.on_pause())
        self.app.on_stop()
        self.assertEqual(self.app.password.text, '')
        self.assertFalse(self.session.stop_event.is_set())

    def test_switch_and_delete_saved_account_preserves_other_account(self):
        records = [dict(server=self.app.server.text, account=name, password=name + '-secret')
                   for name in ('A', 'B')]
        class Vault:
            def save(self, value): self.records = value
        self.app.vault = Vault()
        self.app.saved_accounts = records
        self.app.saved.values = self.app.saved_names()
        self.app.saved.text = self.app.saved_names()[0]
        self.assertEqual(self.app.account.text, 'A')
        self.app.delete_saved()
        self.assertEqual([r['account'] for r in self.app.vault.records], ['B'])
        self.assertEqual(self.app.password.text, '')
        self.assertFalse(self.session.stop_event.is_set())

    def test_android_startup_error_keeps_ui_and_hides_exception_details(self):
        from types import SimpleNamespace
        import android_app.app as module
        def fail(_name): raise RuntimeError('fixture-secret must not appear')
        with patch.object(module, 'platform', 'android'), patch.dict('sys.modules', {'jnius': SimpleNamespace(autoclass=fail)}):
            self.app.initialize_android()
            self.assertIn('A01', self.app.message.text)
            self.assertNotIn('fixture-secret', self.app.message.text)
            with patch.object(self.app.manager, 'start') as start:
                self.app.connect_account()
                start.assert_not_called()
        self.assertIsNotNone(self.app.root if self.app.root else self.root)

    def test_monitor_failure_does_not_exit_render_loop(self):
        from types import SimpleNamespace
        import queue
        self.app.manager = SimpleNamespace(background=True, sessions={'fixture': self.session},
            available=True, metrics={'active': 1}, events=queue.Queue())
        with patch.object(self.app, 'render_metrics', side_effect=RuntimeError('private detail')):
            self.assertTrue(self.app.drain_events())
        self.assertIn('A06', self.app.resources.text)
        self.assertNotIn('private detail', self.app.resources.text)

    def test_automation_controls_follow_core_and_do_not_optimistically_enable(self):
        from android_app.automation_ui import refresh, toggle
        card = self.app.cards['fixture'][4]
        refresh(self.app, 'fixture')
        self.assertTrue(card.automation_buttons['battle'].disabled)
        self.session.phase = 'world_ready'
        refresh(self.app, 'fixture')
        self.assertFalse(card.automation_buttons['battle'].disabled)
        toggle(self.app, 'fixture', 'battle')
        self.assertEqual(card.automation_buttons['battle'].text, '處理中')
        self.assertFalse(self.session.automation.get('battle', {}).get('enabled', False))
        self.session.automation_pending.clear()
        self.session.automation = {'battle': {'enabled': True, 'status': 'armed'}}
        refresh(self.app, 'fixture')
        self.assertEqual(card.automation_buttons['battle'].text, '停止戰鬥')
        self.assertIn('AI待命', card.automation_status.text)
        self.session.active = False
        refresh(self.app, 'fixture')
        self.assertTrue(card.automation_buttons['battle'].disabled)

    def test_ai_dialog_saves_validated_preferences(self):
        from android_app.automation_ui import edit_settings
        from kivy.uix.spinner import Spinner
        from kivy.uix.button import Button
        captured = []
        with patch('android_app.automation_ui.Popup.open', lambda popup: captured.append(popup)):
            edit_settings(self.app, 'fixture')
        popup = captured[0]
        widgets = list(popup.content.walk())
        selectors = [w for w in widgets if isinstance(w, Spinner)]
        self.assertEqual(len(selectors), 2)
        for selector in selectors: selector.text = '自動選擇已知技能'
        save = next(w for w in widgets if isinstance(w, Button) and w.text == '保存')
        save.dispatch('on_release')
        for profile in self.session.ai_settings['profiles'].values():
            self.assertEqual(profile['orderAction'][0]['id'], -1)
