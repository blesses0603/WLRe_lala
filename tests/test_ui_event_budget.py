import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from wlre.ui.gui import App
from wlre.ui.chat_ui import ChatPanel


class EventBudget(unittest.TestCase):
    def test_poll_yields_and_preserves_remaining_events_in_order(self):
        events=queue.Queue()
        for text in ('one','two','three'):events.put(('message',text))
        app=SimpleNamespace(events=events,write=Mock(),status=Mock(),root=Mock(),poll=Mock())
        with patch('wlre.ui.gui.time.perf_counter',side_effect=[0,0.001,0.009]):App.poll(app)
        app.write.assert_called_once_with('one')
        self.assertEqual(events.qsize(),2)
        app.root.after.assert_called_with(10,app.poll)
        with patch('wlre.ui.gui.time.perf_counter',return_value=1):App.poll(app)
        self.assertEqual([call.args[0] for call in app.write.call_args_list],['one','two','three'])
        self.assertTrue(events.empty())
        app.root.after.assert_called_with(50,app.poll)

    def test_unrelated_packets_do_not_scan_chat_names(self):
        panel=SimpleNamespace(update_names=Mock())
        for kind in ('unimplemented','position_snapshot','battle_start','roaming_status'):
            ChatPanel.handle_event(panel,{'type':kind},{})
        ChatPanel.handle_event(panel,{'type':'command_rejected','command_type':'craft'},{})
        panel.update_names.assert_not_called()

    def test_chat_event_still_updates_names_and_status(self):
        panel=SimpleNamespace(update_names=Mock(),status=Mock())
        event={'type':'chat_notice','text':'fixture'};state={'player':{'role_id':1}}
        ChatPanel.handle_event(panel,event,state)
        panel.update_names.assert_called_once_with(state,event)
        panel.status.set.assert_called_once_with('fixture')
