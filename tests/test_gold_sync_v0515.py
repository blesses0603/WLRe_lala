"""Official 1262 S26 Gold synchronization, independent of NPC purchase permissions."""
import unittest
from wlre.core.state import State
from wlre.network.wire import Packet, ProtocolError
from wlre.network.protocol import decode


class GoldSyncTests(unittest.TestCase):
    def test_authoritative_snapshot_then_signed_deltas(self):
        state=State()
        self.assertFalse(state.gold['ready'])
        state.apply(decode(Packet(26,4,(5000).to_bytes(4,'little'))))
        self.assertEqual(state.gold['amount'],5000)
        self.assertTrue(state.gold['reliable'])
        self.assertEqual(state.gold['source'],'S26-4')
        state.apply(decode(Packet(26,2,(750).to_bytes(4,'little')+b'\x00')))
        self.assertEqual(state.gold['amount'],4250)
        state.apply(decode(Packet(26,1,(20).to_bytes(4,'little')+b'\x01')))
        self.assertEqual(state.gold['amount'],4270)
        self.assertEqual(state.gold['revision'],3)

    def test_delta_before_initialization_fails_closed(self):
        state=State()
        state.apply(decode(Packet(26,1,(200).to_bytes(4,'little')+b'\0')))
        self.assertFalse(state.gold['reliable'])
        self.assertIsNone(state.gold['amount'])
        state.apply(decode(Packet(26,4,(100).to_bytes(4,'little'))))
        self.assertEqual(state.gold['amount'],100)
        state.apply(decode(Packet(26,2,(200).to_bytes(4,'little')+b'\0')))
        self.assertFalse(state.gold['reliable'])
        self.assertIsNone(state.gold['amount'])
        state.apply(decode(Packet(26,4,(900).to_bytes(4,'little'))))
        self.assertEqual(state.gold['amount'],900)
        self.assertTrue(state.gold['reliable'])

    def test_overflow_cap_and_role_switch_reset(self):
        state=State()
        state.apply(decode(Packet(26,4,(0xffffffff).to_bytes(4,'little'))))
        state.apply(decode(Packet(26,1,b'\x01\0\0\0\x01')))
        self.assertFalse(state.gold['reliable'])
        state.apply(decode(Packet(26,4,(1000).to_bytes(4,'little'))))
        state.apply(decode(Packet(26,3,b'')))
        self.assertFalse(state.gold['reliable'])
        state.apply({'type':'role_list_available','roles':[]})
        self.assertEqual(state.gold['revision'],0)
        self.assertFalse(state.gold['ready'])

    def test_malformed_lengths_or_flags_raise(self):
        samples=[
            Packet(26,4,b'\x01\x02'),
            Packet(26,4,b'\0'*5),
            Packet(26,1,b'\0'*4),
            Packet(26,2,b'\0'*4+b'\x03'),
            Packet(26,2,b'\0'*6),
        ]
        for packet in samples:
            with self.subTest(packet=packet),self.assertRaises(ProtocolError):
                decode(packet)

    def test_gold_snapshot_not_used_to_authorize_shop_payment(self):
        from wlre.network.commands import dispatch
        from unittest.mock import Mock
        state=State()
        state.apply(decode(Packet(26,4,(50000).to_bytes(4,'little'))))
        logic=Mock()
        logic.world_acknowledged=True
        logic.maintenance.pending=None
        logic.maintenance.uncertain=False
        for action in ('npc_shop_buy','npc_shop_sell'):
            with self.subTest(action=action),self.assertRaises(ProtocolError):
                dispatch(logic,{'type':action,'confirmed':True},state)
