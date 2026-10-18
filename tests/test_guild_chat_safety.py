"""Regression checks for guild chat membership and stuck send state."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.wire import ProtocolError
from wlre.services.social.chat import chat_packet
from wlre.ui.chat_ui import ChatPanel


class GuildChatPacketTests(unittest.TestCase):
    def setUp(self):
        self.state = State(phase='world_ready')
        self.state.player = {'role_id': 12345}
        self.command = {'type': 'chat', 'channel': '組織', 'text': '測試訊息'}

    def test_unjoined_or_unsynced_guild_never_emits_chat_packet(self):
        for guild in ({}, {'ready': False, 'members': {'12345': {}}}):
            with self.subTest(guild=guild):
                self.state.guild = guild
                with self.assertRaisesRegex(ProtocolError, '組織'):
                    chat_packet(self.command, self.state)

    def test_non_member_cannot_send_using_somebody_elses_roster(self):
        self.state.guild = {'ready': True, 'members': {'77777': {}}}
        with self.assertRaisesRegex(ProtocolError, '組織成員'):
            chat_packet(self.command, self.state)

    def test_verified_member_can_send_and_other_channels_unchanged(self):
        self.state.guild = {'ready': True, 'members': {'12345': {'role_id': 12345}}}
        packet = chat_packet(self.command, self.state)
        self.assertEqual((packet.main, packet.sub), (2, 6))
        self.state.guild = {}
        packet = chat_packet({**self.command, 'channel': '區域'}, self.state)
        self.assertEqual((packet.main, packet.sub), (2, 2))

    def test_network_command_rejects_before_chat_cooldown(self):
        logic = SessionLogic()
        logic.world_acknowledged = True
        with self.assertRaisesRegex(ProtocolError, '組織'):
            logic.command(self.command, self.state)
        self.assertIsNone(logic.last_chat_time)


def fake_panel(guild, send_result=True):
    app = SimpleNamespace(
        live_active=True,
        worker=SimpleNamespace(is_alive=lambda: True),
        snapshot={'player': {'role_id': 12345}, 'attributes': {}, 'party': {}, 'guild': guild},
        send=Mock(return_value=send_result),
    )
    panel = SimpleNamespace(
        pending=False,
        pending_timeout=None,
        app=app,
        channel=SimpleNamespace(get=lambda: '組織'),
        target=SimpleNamespace(get=lambda: ''),
        text=SimpleNamespace(get=lambda: '測試訊息'),
        quote=None,
        sent_quote=None,
        send_button=Mock(),
        status=Mock(),
        after=Mock(return_value='job-1'),
        after_cancel=Mock(),
        pending_expired=lambda: None,
    )
    panel.finish_pending = lambda: ChatPanel.finish_pending(panel)
    return panel


class GuildChatPanelTests(unittest.TestCase):
    def test_unjoined_send_stays_enabled_and_never_enqueues(self):
        panel = fake_panel({})
        ChatPanel.send(panel)
        self.assertFalse(panel.pending)
        panel.app.send.assert_not_called()
        panel.send_button.configure.assert_not_called()
        panel.status.set.assert_called_once()
        self.assertIn('組織', panel.status.set.call_args.args[0])

    def test_joined_send_is_enqueued_and_timeout_started(self):
        panel = fake_panel({'ready': True, 'members': {'12345': {}}})
        ChatPanel.send(panel)
        self.assertTrue(panel.pending)
        panel.app.send.assert_called_once()
        panel.after.assert_called_once()
        self.assertEqual(panel.pending_timeout, 'job-1')
        panel.send_button.configure.assert_called_with(state='disabled')

    def test_queue_rejection_unlocks_immediately(self):
        panel = fake_panel({'ready': True, 'members': {'12345': {}}}, send_result=False)
        ChatPanel.send(panel)
        self.assertFalse(panel.pending)
        self.assertIsNone(panel.pending_timeout)
        panel.after.assert_not_called()
        panel.send_button.configure.assert_called_with(state='normal')
        self.assertIn('重新登入', panel.status.set.call_args.args[0])

    def test_expired_send_unlocks_and_does_not_clear_composed_text(self):
        panel = fake_panel({'ready': True, 'members': {'12345': {}}})
        ChatPanel.send(panel)
        ChatPanel.pending_expired(panel)
        self.assertFalse(panel.pending)
        self.assertIsNone(panel.pending_timeout)
        panel.send_button.configure.assert_called_with(state='normal')
        self.assertIn('逾時', panel.status.set.call_args.args[0])

    def test_server_refusal_unlocks_pending(self):
        panel = fake_panel({'ready': True, 'members': {'12345': {}}})
        ChatPanel.send(panel)
        panel.update_names = Mock()
        ChatPanel.handle_event(panel, {'type': 'chat_result', 'result': 2, 'text': '已禁言'}, {})
        self.assertFalse(panel.pending)
        panel.after_cancel.assert_called_once_with('job-1')
        panel.send_button.configure.assert_called_with(state='normal')


if __name__ == '__main__':
    unittest.main()
