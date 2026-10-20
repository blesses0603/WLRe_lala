"""S51-1 malformed record containment and privacy-safe diagnostics (protocol 1262)."""
import tempfile
import unittest
from unittest.mock import Mock, patch

from wlre.core.diagnostics import Diagnostics
from wlre.core.state import State
from wlre.network.client import run_client
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError, encode


def record(col, row, kind, value):
    return bytes((col, row, kind)) + value.to_bytes(4, 'little')


class S51ProtocolTests(unittest.TestCase):
    def test_complete_records_are_still_applied(self):
        payload = record(1, 0, 25, 73) + record(1, 0, 26, 19)
        event = decode(Packet(51, 1, payload))
        self.assertEqual(event['type'], 'battle_attribute_set')
        self.assertEqual(event['values'], [
            {'col': 1, 'row': 0, 'kind': 25, 'value': 73},
            {'col': 1, 'row': 0, 'kind': 26, 'value': 19},
        ])
        state = State()
        state.battle_units['1:0'] = {'col': 1, 'row': 0, 'hp': 100, 'sp': 40}
        state.apply(event)
        self.assertEqual((state.battle_units['1:0']['hp'],
                          state.battle_units['1:0']['sp']), (73, 19))

    def test_empty_packet_is_valid_noop_in_official_loop(self):
        event = decode(Packet(51, 1))
        self.assertEqual(event['type'], 'battle_attribute_set')
        self.assertEqual(event['values'], [])

    def test_partial_record_is_ignored_atomically_without_payload_leak(self):
        full = record(1, 0, 25, 1)
        for length in (1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 15, 20):
            with self.subTest(length=length):
                payload = (full * 3)[:length]
                event = decode(Packet(51, 1, payload))
                self.assertEqual(event['type'], 'battle_attribute_invalid')
                self.assertEqual(event['payload_bytes'], length)
                self.assertEqual(event['trailing_bytes'], length % 7)
                self.assertEqual(event['complete_records'], length // 7)
                self.assertNotIn('values', event)
                self.assertNotIn('payload', event)
                state = State()
                state.battle_units['1:0'] = {'col': 1, 'row': 0, 'hp': 100}
                state.apply(event)
                self.assertEqual(state.battle_units['1:0']['hp'], 100)

    def test_other_protocols_remain_strict(self):
        with self.assertRaises(ProtocolError):
            decode(Packet(52, 1, b'\x01'))


class S51DiagnosticsTests(unittest.TestCase):
    def test_diagnostics_are_numeric_rate_limited_and_redacted(self):
        event = decode(Packet(51, 1, record(1, 0, 25, 1) + b'X'))
        with tempfile.TemporaryDirectory() as folder:
            diagnostics = Diagnostics(folder)
            self.assertTrue(diagnostics.battle_attribute_invalid(event))
            self.assertFalse(diagnostics.battle_attribute_invalid(event))
            self.assertEqual(diagnostics.battle_invalid_count, 2)
            # Invalid or caller-controlled attributes must never reach logging.
            self.assertFalse(diagnostics.battle_attribute_invalid({
                **event, 'payload_bytes': 'password=secret', 'trailing_bytes': 1}))
            self.assertFalse(diagnostics.battle_attribute_invalid({
                **event, 'main': True, 'payload_bytes': 8}))
            self.assertFalse(diagnostics.battle_attribute_invalid({
                **event, 'trailing_bytes': 6}))
            diagnostics.close()
            text = diagnostics.path.read_text(encoding='utf-8')
        self.assertEqual(text.count('protocol_warning packet_main=51 packet_sub=1'), 1)
        self.assertIn('payload_bytes=8 complete_records=1 trailing_bytes=1 count=1', text)
        self.assertNotIn('password', text)
        self.assertNotIn('secret', text)

    def test_session_keeps_processing_after_invalid_s51(self):
        malformed = Packet(51, 1, record(1, 0, 25, 999) + b'\xff')
        healthy = Packet(51, 1, record(1, 0, 25, 73))
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.recv.side_effect = [encode(malformed, 0) + encode(healthy, 0), b'']
        events = []
        with patch('wlre.network.client.socket.create_connection', return_value=connection):
            state = run_client('fixture.invalid', 1, {'rx_xor': 0, 'tx_xor': 0},
                               events.append, duration=None)
        types = [event.get('type') for event in events]
        self.assertIn('battle_attribute_invalid', types)
        self.assertIn('battle_attribute_set', types)
        self.assertEqual(types.index('battle_attribute_set'),
                         types.index('battle_attribute_invalid') + 1)
        self.assertEqual(state.packet_count, 2)
        closed = next(event for event in events
                      if event.get('type') == 'connection_health'
                      and event.get('status') == 'closed')
        self.assertEqual(closed['reason'], 'server_closed')
        self.assertNotIn('error_type', closed)
        self.assertNotIn('payload', repr(events))


if __name__ == '__main__':
    unittest.main()
