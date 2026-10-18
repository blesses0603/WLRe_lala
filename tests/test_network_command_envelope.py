"""Validated command ingress and exact outbound packet observation tests."""
import queue
import unittest
from unittest.mock import Mock, patch

from wlre.core.state import State
from wlre.network.client import SessionLogic, _send_command_packet, run_client
from wlre.network.command_envelope import validate_command, rejected_command_type
from wlre.network.outbound_observations import observed_outbound
from wlre.network.wire import FrameDecoder, Packet, ProtocolError, encode


class CommandEnvelopeTests(unittest.TestCase):
    def test_bad_command_envelopes_cannot_reach_service_dispatch(self):
        logic=SessionLogic()
        state=State(phase='world_ready')
        for invalid in (None, 7, "allocate_points", [], {}, {'type': None},
                        {'type': 42}, {'type': 'x'*65}):
            with self.subTest(invalid=invalid):
                with patch('wlre.network.client.dispatch') as dispatch:
                    with self.assertRaises(ProtocolError):
                        logic.command(invalid,state)
                    dispatch.assert_not_called()
        with patch('wlre.network.client.dispatch',return_value=[]) as dispatch:
            self.assertEqual(logic.command({'type':'stop_roaming'},state),[])
            dispatch.assert_called_once()

    def test_rejections_never_echo_arbitrary_command_content(self):
        self.assertEqual(rejected_command_type(None),'invalid')
        self.assertEqual(rejected_command_type({'type':'secret:login=password'}),'invalid')
        self.assertEqual(rejected_command_type({'type':'start_auto_battle'}),'start_auto_battle')
        self.assertEqual(validate_command({'type':'allocate_points'}),'allocate_points')

    def test_run_loop_rejects_non_dict_command_without_disconnect(self):
        invalid_commands=queue.Queue()
        invalid_commands.put('private-command-payload')
        invalid_commands.put({'type':False})
        connection=Mock()
        connection.recv.return_value=b''
        context=Mock()
        context.__enter__=Mock(return_value=connection)
        context.__exit__=Mock(return_value=False)
        emitted=[]
        with patch('wlre.network.client.socket.create_connection',return_value=context):
            result=run_client('localhost',16988,{'rx_xor':0,'tx_xor':0},emitted.append,
                              commands=invalid_commands)
        errors=[e for e in emitted if e['type']=='command_rejected']
        self.assertEqual(len(errors),2)
        self.assertTrue(all(e['command_type']=='invalid' for e in errors))
        self.assertNotIn('private-command-payload',str(errors))
        self.assertEqual(result.phase,'disconnected')


class OutboundPacketObservationsTests(unittest.TestCase):
    def test_known_sent_packet_observations_preserve_wire_values(self):
        cases=(
            (Packet(50,1,b'\x01\x02\x03\x04\x34\x12'),
             {'type':'battle_command_sent','col':1,'row':2,
              'target_col':3,'target_row':4,'skill_id':0x1234}),
            (Packet(50,2,b'\x01\x02\x03\x04\x34\x12\x00\x00\x07'),
             {'type':'battle_command_sent','col':1,'row':2,
              'target_col':3,'target_row':4,'skill_id':10024,
              'item_id':0x1234,'bag_index':7}),
            (Packet(23,15,b'\x07\x34\x12\x00\x00\x00\x00\x03'),
             {'type':'field_item_sent','bag_index':7,'item_id':0x1234,'npc_index':3}),
            (Packet(23,147,b'\x03\x00\x02\x22\x11'),
             {'type':'field_storage_sent','resource':'hp','npc_index':2,'amount':0x1122}),
            (Packet(6,1,b'\x22\x11\x44\x33'),
             {'type':'movement_request','main':6,'sub':1,'x':0x1122,'y':0x3344}),
        )
        for packet,expected in cases:
            with self.subTest(packet=(packet.main,packet.sub)):
                self.assertEqual(observed_outbound(packet),expected)
        self.assertIsNone(observed_outbound(Packet(31,28)))

    def test_truncated_outbound_effects_are_rejected_before_send(self):
        for packet in (Packet(50,1,b'\x01\x02'),
                       Packet(50,2,b'\x01'*8),
                       Packet(23,15,b'\x01'*7),
                       Packet(23,147,b'\x03'*4),
                       Packet(6,1,b'\x01')):
            with self.subTest(packet=(packet.main,packet.sub)):
                connection=Mock();emit=Mock();state=Mock()
                with self.assertRaises(ProtocolError):
                    _send_command_packet(connection,packet,0,state,emit,None)
                connection.sendall.assert_not_called()
                state.apply.assert_not_called()

    def test_sent_observation_happens_after_successful_send(self):
        packet=Packet(50,1,b'\x01\x02\x03\x04\x34\x12')
        history=[]
        connection=Mock()
        connection.sendall.side_effect=lambda *_:history.append('socket')
        state=Mock()
        state.apply.side_effect=lambda *_:history.append('apply')
        emitted=[]
        _send_command_packet(connection,packet,0,state,emitted.append,None)
        self.assertEqual(history,['socket','apply'])
        self.assertEqual([e['type'] for e in emitted],['sent','battle_command_sent'])
        self.assertEqual(connection.sendall.call_args.args[0],encode(packet,0))
        connection.sendall.side_effect=OSError('wire disconnected')
        state.apply.reset_mock()
        with self.assertRaises(OSError):
            _send_command_packet(connection,packet,0,state,emitted.append,None)
        state.apply.assert_not_called()

    def test_frame_codec_still_handles_fragmented_and_coalesced_packets(self):
        expected=[Packet(63,5),Packet(8,4),Packet(20,8,b'\x01')]
        raw=b''.join(encode(p,0xad) for p in expected)
        parser=FrameDecoder(0xad)
        seen=[]
        for chunk in (raw[:1],raw[1:3],raw[3:8],raw[8:14],raw[14:]):
            seen.extend(parser.feed(chunk))
        parser.finish()
        self.assertEqual(seen,expected)
        with self.assertRaises(ProtocolError):
            FrameDecoder(0).feed(b'\x00\x00\x02\x00\x01\x02')


if __name__ == '__main__':
    unittest.main()
