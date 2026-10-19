"""Room packet builders are Lua-verified but have no direct network dispatch."""
import unittest

from wlre.network.instance_actions import (
    create_main_room, create_coop_room, join_main_room,
    join_coop_room, leave_room,
)
from wlre.network.wire import Packet, ProtocolError, Writer


class DungeonRoomActionBytes(unittest.TestCase):
    def test_normal_public_and_private_create(self):
        self.assertEqual(
            create_main_room(30012, public=True),
            Packet(85, 3, Writer().u16(30012).u8(1).u16(0).u8(0).build()))
        self.assertEqual(
            create_main_room(30012, public=False, password=1234),
            Packet(85, 3, Writer().u16(30012).u8(0).u16(1234).build()))
        with self.assertRaises(ProtocolError):
            create_main_room(30040, public=True)  # unsupported new-dungeon mode
        with self.assertRaises(ProtocolError):
            create_main_room(30012, public=False, password=0)

    def test_coop_create_uses_correct_kind_and_map_npc_index(self):
        self.assertEqual(
            create_coop_room(27, 3, public=True),
            Packet(186, 1, Writer().u8(3).u8(2).u8(1)
                   .u8(1).u32(0).u8(0).build()))
        self.assertEqual(
            create_coop_room(28, 4, public=False, password=123456),
            Packet(186, 1, Writer().u8(4).u8(2).u8(2)
                   .u8(0).u32(123456).u8(0).build()))
        self.assertEqual(
            create_coop_room(21, 2, public=True),
            Packet(186, 1, Writer().u8(2).u8(1).u8(0)
                   .u8(1).u32(0).u8(0).build()))
        with self.assertRaises(ProtocolError):
            create_coop_room(27, 5, public=True)
        with self.assertRaises(ProtocolError):
            create_coop_room(99, 3, public=True)

    def test_join_leave_and_server_room_sn(self):
        self.assertEqual(
            join_main_room(1000, 55, public=True),
            Packet(85, 5, Writer().u16(1000).u16(55).build()))
        self.assertEqual(
            join_main_room(1000, 55, public=False, password=123),
            Packet(85, 5, Writer().u16(1000).u16(55).u16(123).build()))
        self.assertEqual(
            join_coop_room(8, public=False, password=100000),
            Packet(186, 4, Writer().u16(8).u32(100000).build()))
        self.assertEqual(leave_room('main'), Packet(85, 6))
        self.assertEqual(leave_room('coop'), Packet(186, 5))
        with self.assertRaises(ProtocolError):
            leave_room('unknown')
        with self.assertRaises(ProtocolError):
            join_main_room(1000, 65536, public=True)
        with self.assertRaises(ProtocolError):
            join_coop_room(8, public=False, password=-1)

    def test_builder_does_not_change_network_commands(self):
        # Integration remains deliberately opt-in until server ACK validation.
        from wlre.core.state import State
        from wlre.network.client import SessionLogic
        s = State(phase='world_ready')
        s.player = {'role_id': 1}
        logic = SessionLogic()
        logic.world_acknowledged = True
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_create', 'mode': 'main',
                           'map_id': 30012, 'public': True}, s)
        self.assertIsNone(s.instances['main']['room'])
