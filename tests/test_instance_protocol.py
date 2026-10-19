"""1262 instance binary layouts and wire-sync safety regression."""
import unittest

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.instances import list_request, member_request
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.instance_catalog import (
    catalog, parse_cooperative_events, parse_dungeons, parse_stages,
)


def main_room(room_id=210):
    name = '房主'.encode('utf-16le')
    guild = '團'.encode('utf-16le')
    return (Writer().u8(1).u16(room_id).u8(len(name)).raw(name)
            .u8(3).u8(len(guild)).raw(guild).u8(1).u16(55).build())


def coop_room(room_id=99):
    return Writer().u16(1).u8(1).u8(2).u8(7).u16(room_id).u8(4).u8(2).u32(345).build()


class InstanceWire(unittest.TestCase):
    def test_main_rooms_and_authoritative_lifecycle(self):
        state = State()
        event = decode(Packet(85, 1, main_room()))
        self.assertEqual(event['rooms'][0]['manager'], '房主')
        state.apply(event)
        self.assertEqual(state.instances['main']['rooms'][0]['sn'], 55)
        state.apply(decode(Packet(85, 5, Writer().u8(1).u8(1).u16(210).u8(2).u32(345).build())))
        self.assertEqual(state.instances['main']['room']['room_id'], 210)
        state.apply(decode(Packet(85, 4, Writer().u16(210).u8(2).u32(345).u32(456).build())))
        self.assertEqual(len(state.instances['main']['members']), 2)
        state.apply(decode(Packet(85, 7, Writer().u8(3).u32(789).u16(210).build())))
        self.assertEqual(len(state.instances['main']['members']), 3)
        state.apply(decode(Packet(85, 9, Writer().u8(1).u32(12).build())))
        self.assertEqual(state.instances['main']['remaining_minutes'], 12)
        state.apply(decode(Packet(85, 15)))
        self.assertTrue(state.instances['main']['completed'])
        state.apply(decode(Packet(85, 5, b'\x02')))
        self.assertIsNone(state.instances['main']['room'])
        self.assertEqual(state.instances['main']['members'], [])

    def test_main_result_does_not_optimistically_create_room(self):
        state = State()
        state.apply(decode(Packet(85, 2, b'\x00')))
        self.assertIsNone(state.instances['main']['room'])
        self.assertIn('等待房間同步', state.instances['main']['status'])
        state.apply(decode(Packet(85, 3, b'\x08')))
        self.assertIn('8', state.instances['main']['status'])

    def test_coop_rooms_members_reward_and_leaving(self):
        state = State()
        state.apply(decode(Packet(186, 17, coop_room())))
        self.assertEqual(state.instances['coop']['rooms'][0]['host_id'], 345)
        room = Writer().u8(0).u8(1).u16(99).u8(0).u8(2).u8(7).u8(2)
        for role_id in (345, 456):
            room.u32(role_id).u8(1).u32(100).u32(100).u32(30).u32(50)
        state.apply(decode(Packet(186, 3, room.build())))
        self.assertEqual(len(state.instances['coop']['members']), 2)
        state.apply(decode(Packet(186, 11, b'\x03\x01\x01\x02\x07')))
        self.assertEqual(state.instances['coop']['reward']['reward_mark'], 2)
        state.apply(decode(Packet(186, 15, b'\x02')))
        self.assertEqual(state.instances['coop']['fight_count'], 2)
        state.apply(decode(Packet(186, 13)))
        self.assertIsNone(state.instances['coop']['room'])
        self.assertEqual(state.instances['coop']['members'], [])

    def test_list_queries_validated_and_mutations_not_exposed(self):
        self.assertEqual((list_request('main').main, list_request('main').sub), (85, 1))
        self.assertEqual((list_request('coop').main, list_request('coop').sub), (186, 17))
        self.assertEqual(member_request('coop', 99).payload, b'\x63\x00')
        with self.assertRaises(ProtocolError): list_request('unknown')
        with self.assertRaises(ProtocolError): member_request('main', 0)
        state = State(phase='world_ready')
        state.player = {'role_id': 1}
        logic = SessionLogic()
        logic.world_acknowledged = True
        self.assertEqual(logic.command({'type': 'instance_refresh', 'mode': 'main'}, state), [Packet(85, 1)])
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_create', 'mode': 'main'}, state)
        state.battle['active'] = True
        with self.assertRaises(ProtocolError):
            logic.command({'type': 'instance_refresh', 'mode': 'coop'}, state)

    def test_malformed_and_unsupported_packets_are_not_silently_accepted(self):
        for packet in (Packet(85, 1, b'\x01\x00'), Packet(186, 17, b'\x01'),
                       Packet(85, 2, b'\x00\x02'), Packet(186, 3, b'\x01')):
            with self.subTest(packet=packet), self.assertRaises(ProtocolError):
                decode(packet)
        self.assertEqual(decode(Packet(186, 14, b'x'))['type'], 'unimplemented')
        self.assertEqual(decode(Packet(85, 21, b'\x03x'))['type'], 'unimplemented')

    def test_instance_state_isolation(self):
        a, b = State(), State()
        a.apply(decode(Packet(85, 1, main_room())))
        self.assertFalse(b.instances['main']['ready'])
        snapshot = a.snapshot()
        snapshot['instances']['main']['rooms'].clear()
        self.assertEqual(len(a.instances['main']['rooms']), 1)


class InstanceCatalog(unittest.TestCase):
    def _fixtures(self):
        dungeon = (Writer().u32(1).u16(5).u8(1).u8(2).u16(1234)
                   .u32(5678).u8(1).u8(0).u8(1).u16(20).u16(30)
                   .u16(500).u8(2))
        for _ in range(16):
            dungeon.u8(10).u32(123).u32(2)
        dungeon.raw(b'\x01\x00\x00\x80')
        cooperate = (Writer().u32(1).u8(7).u32(900).u16(10).u16(20)
                     .u8(3).u16(1).u16(2).u16(3))
        for npc in (10, 11, 12, 13):
            cooperate.u16(npc)
        cooperate.u8(10).u32(777).u32(2)
        stage = (Writer().u32(1).u16(1234).raw(b'\x00'*2).u32(99)
                 .raw(b'\x00'*4).raw(b'\x00'*3).u16(0).u32(0)
                 .u8(4).u8(0).u8(2).u8(10).u8(0)
                 .u16(0).u16(20).u16(60).raw(b'\x00'*20)
                 .raw(b'\x00'*4).raw(b'\x00'*3).raw(b'\x00'*4)
                 .raw(b'\x00'*8).raw(b'\x00'*5))
        return dungeon.build(), cooperate.build(), stage.build()

    def test_official_fixed_layout_and_missing_localization(self):
        dungeon, coop, stage = self._fixtures()
        rows = parse_dungeons(dungeon)
        self.assertEqual(len(rows[0]['awards']), 16)
        self.assertEqual(rows[0]['double_award_slots'], [1])
        self.assertEqual(rows[0]['special_award_slots'], [16])
        self.assertEqual(parse_cooperative_events(coop)[0]['follower_ids'], [10, 11, 12, 13])
        self.assertEqual(parse_stages(stage)[1234]['min_level'], 20)
        info = catalog(dungeon, coop, stage)
        self.assertIsNone(info['records'][0]['name'])
        self.assertEqual(catalog(dungeon, coop, stage, {99: '測試副本'})['records'][0]['name'], '測試副本')

    def test_truncated_or_extra_binary_tables_rejected(self):
        d, c, s = self._fixtures()
        for parser, raw in ((parse_dungeons, d), (parse_cooperative_events, c), (parse_stages, s)):
            with self.subTest(parser=parser.__name__):
                with self.assertRaises(ProtocolError): parser(raw[:-1])
                with self.assertRaises(ProtocolError): parser(raw+b'\x00')
                with self.assertRaises(ProtocolError): parser(b'\xff\xff\xff\xff')
