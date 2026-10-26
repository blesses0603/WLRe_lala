"""Official 1262 dungeon/co-op safety and multi-round regression tests."""
import unittest

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet, Writer, ProtocolError
from wlre.services.instance_combat import consume_coop_fight, own_victory
from wlre.ui.instance_ui import instance_details


def ustr(value):
    raw = value.encode('utf-16le')
    return Writer().u8(len(raw)).raw(raw)


def coop_members(room_id, ids=(678, 555)):
    w = Writer().u8(0).u8(1).u16(room_id).u8(0).u8(2).u8(0).u8(len(ids))
    for pid in ids:
        w.u32(pid).u8(1).u32(100).u32(100).u32(30).u32(30)
    return Packet(186, 3, w.build())


class OfficialInstanceObjectives(unittest.TestCase):
    def test_s85_10_kills_boss_and_per_player_scores(self):
        state = State()
        state.player = {'role_id': 678}
        for packet in (
            Packet(85, 10, Writer().u8(3).u8(2).u8(5).u16(333).build()),
            Packet(85, 10, Writer().u8(1).u8(2).u8(3).build() + ustr('角色').build()),
            Packet(85, 10, Writer().u8(4).u16(900).build()),
            Packet(85, 10, Writer().u8(2).u8(1).build() + ustr('角色').build()),
            Packet(85, 10, Writer().u8(5).u8(2).u32(678).u32(555).build()),
            Packet(85, 10, Writer().u8(6).u8(1).u32(678).build()),
        ):
            state.apply(decode(packet))
        data = state.instances['main']
        self.assertEqual(data['objectives']['targets'][2]['kills'], 3)
        self.assertEqual(data['objectives']['targets'][2]['required'], 5)
        self.assertTrue(data['objectives']['boss']['defeated'])
        self.assertEqual(data['objectives']['scores']['678'], {'normal': 1, 'boss': 1})
        self.assertIn('3/5', instance_details(data, False, 678))
        self.assertIn('Boss NPC900：已擊敗', instance_details(data, False, 678))
        self.assertFalse(data['completed'])
        state.apply(decode(Packet(85, 5, Writer().u8(1).u8(1).u16(333).u8(2).u32(678).build())))
        self.assertEqual(data['objectives']['targets'], {})
        self.assertFalse(data['completed'])

    def test_s85_10_strict_bounds(self):
        for payload in (
            b'\x03\x02\x05\x01', b'\x01\x02\x05\x01',
            b'\x04\x01', b'\x05\x11', b'\x06\x01\x00',
            Writer().u8(3).u8(2).u8(5).u16(333).u8(0).build(),
        ):
            with self.subTest(payload=payload), self.assertRaises(ProtocolError):
                decode(Packet(85, 10, payload))

    def test_new_dungeon_objectives_and_real_completion_records(self):
        state = State()
        state.player = {'role_id': 678}
        state.apply(decode(Packet(85, 21, Writer().u8(0).u8(1).u8(1).u16(999)
                                  .u32(678).u8(0).u32(20).build())))
        self.assertEqual(state.instances['main']['room']['scene'], 999)
        state.apply(decode(Packet(85, 21, Writer().u8(3).u8(1).u16(150)
                                  .u8(3).u8(1).build())))
        state.apply(decode(Packet(85, 21, Writer().u8(4).u8(1).u8(2).build()
                                  + ustr('角色').build())))
        self.assertEqual(state.instances['main']['objectives']['targets'][1]['kills'], 2)
        self.assertIn('2/3', instance_details(state.instances['main'], False, 678))
        records = (Writer().u8(100).u8(2).u32(678).u8(5).u8(6)
                   .u32(555).u8(7).u8(8).build())
        state.apply(decode(Packet(85, 21, records)))
        self.assertEqual(len(state.instances['main']['objectives']['records']), 2)
        self.assertTrue(state.instances['main']['completed'])
        self.assertEqual(state.instances['main']['completion_source'], 'S85-21-100')
        with self.assertRaises(ProtocolError):
            decode(Packet(85, 21, b'\x64\x02' + b'\0' * 6))
        with self.assertRaises(ProtocolError):
            decode(Packet(85, 21, records + b'\0'))


class CooperativeMatchAndRounds(unittest.TestCase):
    def test_npc_and_player_rosters_are_validated(self):
        npc = (Writer().u8(17).u8(1).u32(900).u8(5).u8(1)
               .u8(0).u8(2).u32(0).u32(0).build() + ustr('對手').build())
        event = decode(Packet(186, 2, npc))
        self.assertEqual(event['roster_role_ids'], [900])
        player = (Writer().u8(18).u8(2).u32(1).u32(2)
                  .u32(3).u32(4).build())
        self.assertEqual(decode(Packet(186, 2, player))['roster_role_ids'],
                         [1, 2, 3, 4])
        for raw in (npc[:-1], npc + b'\0', player[:-1], player + b'\0',
                    b'\x11\x00', b'\x12\x09'):
            with self.subTest(raw=raw), self.assertRaises(ProtocolError):
                decode(Packet(186, 2, raw))

    def test_side_and_count_decrement_exactly_once(self):
        state = State()
        state.player = {'role_id': 678}
        state.battle_count = 1
        state.instances['coop']['fight_count'] = 3
        state.battle = {'active': False, 'winner_side': 1}
        state.battle_units['4:1'] = {'col': 4, 'row': 1, 'pid': 678}
        self.assertTrue(own_victory(state))
        self.assertEqual(consume_coop_fight(state), 5.0)
        self.assertEqual(state.instances['coop']['fight_count'], 2)
        self.assertIsNone(consume_coop_fight(state))
        self.assertEqual(state.instances['coop']['fight_count'], 2)
        state.battle_count = 2
        state.battle['winner_side'] = 2
        self.assertFalse(own_victory(state))
        self.assertEqual(consume_coop_fight(state), 2.5)
        self.assertEqual(state.instances['coop']['fight_count'], 1)
        state.battle_count = 3
        state.battle['winner_side'] = 1
        self.assertEqual(consume_coop_fight(state), 2.5)
        self.assertEqual(state.instances['coop']['fight_count'], 0)

    def test_ambiguous_side_cannot_trigger_5sec_win_wait(self):
        state = State()
        state.player = {'role_id': 678}
        state.battle_count = 1
        state.battle = {'winner_side': 1}
        state.instances['coop']['fight_count'] = 2
        self.assertIsNone(own_victory(state))
        self.assertEqual(consume_coop_fight(state), 2.5)
        self.assertEqual(state.instances['coop']['fight_count'], 1)

    def test_coop_new_room_clears_old_run_but_not_opt_in(self):
        state = State()
        coop = state.instances['coop']
        state.apply(decode(coop_members(77)))
        state.apply(decode(Packet(186, 11, b'\x03\x03\x01\x01\x07')))
        self.assertTrue(coop['completed'])
        coop['auto_claim_enabled'] = True
        state.apply(decode(Packet(186, 15, b'\x03')))
        state.apply(decode(coop_members(78)))
        self.assertFalse(coop['completed'])
        self.assertIsNone(coop['reward'])
        self.assertIsNone(coop['fight_count'])
        self.assertTrue(coop['auto_claim_enabled'])
        self.assertEqual(coop['received_awards'], [])


if __name__ == '__main__':
    unittest.main()
