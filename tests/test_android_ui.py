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
