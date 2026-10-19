import copy
import struct
import unittest
from unittest.mock import patch

from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.expedition import Expedition, duration, validate, choose_members
from wlre.services.expedition_data import parse_catalog, attach_names
from wlre.paths import RESOURCE_ROOT
from wlre.services.items.combat_resources import available
import json


def role(index=1, faith=90, status=0):
    return {'index': index, 'npc_id': 100 + index, 'state': status, 'faith': faith,
            'stats': {'level': 30, 'degree': 0, 'str': 10, 'con': 10, 'int': 10, 'wis': 10, 'agi': 10, 'potential': 0}}


def catalog():
    return {'levels': {'1': {'teams': 2, 'difficulty': 3, 'reduction': 0}}, 'tasks': {
        '1': {'id': 1, 'area': 1, 'minutes': 300, 'faith_cost': 20, 'difficulty': 1, 'condition': [0, 0, 0]},
        '2': {'id': 2, 'area': 2, 'minutes': 360, 'faith_cost': 20, 'difficulty': 1, 'condition': [1, 1, 0]}}}


class ExpeditionFixture:
    def setUp(self):
        self.state = State(phase='world_ready')
        self.state.expedition.update(ready=True, outpost_ready=True, level=1,
            roles={'1': role()}, quests={'1': 1, '2': 2}, teams={
                '1': {'index': 1, 'quest': 0, 'members': [0]*4},
                '2': {'index': 2, 'quest': 0, 'members': [0]*4}})
        self.service = Expedition(catalog())
        self.settings = {'min_hours': 5, 'faith_min': 80, 'item_id': 34014, 'min_success': 0}

    def event(self, event):
        self.state.apply(event)
        self.service.observe(event, self.state)


class ExpeditionAutomation(ExpeditionFixture, unittest.TestCase):
    def test_time_threshold_after_reduction_and_no_early_local_dispatch(self):
        self.service.start(self.state, self.settings)
        packet, = self.service.tick(self.state, 10)
        self.assertEqual((packet.main, packet.sub, packet.payload), (31, 15, b'\x02\x00\x65\x00' + b'\x00'*7))
        self.assertEqual(self.state.expedition['teams']['1']['quest'], 0)
        self.event({'type': 'expedition_team', 'team': {'index': 1, 'quest': 2, 'members': [101, 0, 0, 0], 'minutes': 360}})
        self.assertIsNone(self.service.pending)
        self.assertEqual(self.service.tick(self.state, self.service.next_check + 1), [])
        self.assertIn('閒置', self.state.expedition['status'])
        q = catalog()['tasks']['2']
        self.assertEqual(duration(q, {'reduction': 200}), 17280)
        self.assertEqual(validate({'min_hours': 6.5})['min_hours'], 6.5)

    def test_exact_five_hours_and_shortened_quests_are_not_dispatched(self):
        for minutes, reduction in ((300, 0), (360, 200)):
            with self.subTest(minutes=minutes, reduction=reduction):
                self.service.catalog['tasks']['2']['minutes'] = minutes
                self.service.catalog['levels']['1']['reduction'] = reduction
                self.service.start(self.state, self.settings)
                self.assertEqual(self.service.tick(self.state, 10), [])

    def test_faith_restoration_waits_for_both_consumption_and_faith(self):
        self.state.expedition['roles']['1']['faith'] = 70
        self.state.inventory.update(ready=True, reliable=True, items={'3': {'item_id': 34014, 'count': 5, 'serial': 123}})
        self.service.start(self.state, self.settings)
        packet, = self.service.tick(self.state, 10)
        expected = Writer().u8(1).u8(1).u8(1).u16(3).u16(34014).u16(2).build()
        self.assertEqual((packet.main, packet.sub, packet.payload), (31, 27, expected))
        self.assertEqual(available(self.state.inventory, 3), 0)
        self.assertEqual(self.state.expedition['roles']['1']['faith'], 70)
        self.event({'type': 'outpost_faith', 'index': 1, 'faith': 80, 'show': 0})
        self.assertIsNotNone(self.service.pending)
        self.assertEqual(self.service.tick(self.state, 11), [])
        self.event({'type': 'bag_delete', 'index': 3, 'count': 2})
        self.assertIsNone(self.service.pending)
        self.assertEqual(available(self.state.inventory, 3), 3)
        packet, = self.service.tick(self.state, self.service.next_check + 1)
        self.assertEqual((packet.main, packet.sub), (31, 15))

    def test_timeout_never_retries_and_stop_does_not_drop_pending(self):
        self.service.start(self.state, self.settings)
        self.service.tick(self.state, 10)
        self.service.stop(self.state)
        self.assertIsNotNone(self.service.pending)
        self.assertEqual(self.service.tick(self.state, 31), [])
        self.assertTrue(self.state.expedition['uncertain'])
        with self.assertRaises(ProtocolError): self.service.start(self.state, self.settings)
        self.assertEqual(self.service.tick(self.state, 100), [])

    def test_insufficient_or_locked_items_stop_without_consumption(self):
        self.state.expedition['roles']['1']['faith'] = 70
        self.state.inventory.update(ready=True, reliable=True, items={'3': {'item_id': 34014, 'count': 1}})
        before = copy.deepcopy(self.state.inventory)
        self.service.start(self.state, self.settings)
        self.assertEqual(self.service.tick(self.state, 10), [])
        self.assertFalse(self.state.expedition['enabled'])
        self.assertEqual(before, self.state.inventory)

    def test_idle_members_and_supported_conditions_only(self):
        self.state.expedition['roles'].update({'2': role(2, 100, 1), '3': role(3, 99)})
        self.service.start(self.state, self.settings)
        self.service.tick(self.state, 10)
        self.assertTrue(set(self.service.pending['members']) <= {101, 103})
        self.assertNotIn(102, self.service.pending['members'])
        self.assertEqual(choose_members({'condition': [2, 1, 1], 'faith_cost': 20}, [role()], 80), [])

    def test_session_rejects_conflicting_actions_and_missing_catalog(self):
        logic = SessionLogic(); logic.world_acknowledged = True
        logic.expedition = Expedition(catalog())
        logic.command({'type': 'start_expedition', 'settings': self.settings}, self.state)
        with self.assertRaises(ProtocolError): logic.command({'type': 'start_alchemy'}, self.state)
        with self.assertRaises(ProtocolError): Expedition({'tasks': {}, 'levels': {}}).start(self.state, self.settings)
        self.state.expedition['enabled'] = False
        self.state.battle['active'] = True
        with self.assertRaises(ProtocolError): self.service.start(self.state, self.settings)

    def test_ai_roaming_and_expedition_can_start_in_either_order(self):
        from unittest.mock import Mock
        for expedition_first in (True, False):
            with self.subTest(expedition_first=expedition_first):
                state = copy.deepcopy(self.state)
                state.player = {'role_id': 1, 'scene': 60000}
                state.location.update(confirmed={'scene': 60000, 'x': 500, 'y': 500, 'packet_number': 1}, confirmed_is_current=True)
                logic = SessionLogic(); logic.world_acknowledged = True
                logic.expedition = Expedition(catalog())
                logic.roaming.converter = Mock()
                if expedition_first: logic.command({'type': 'start_expedition', 'settings': self.settings}, state)
                logic.command({'type': 'start_auto_battle'}, state)
                logic.command({'type': 'start_roaming'}, state)
                if not expedition_first: logic.command({'type': 'start_expedition', 'settings': self.settings}, state)
                packet, = logic.expedition.tick(state, 10)
                self.assertEqual((packet.main, packet.sub), (31, 15))
                self.assertTrue(state.auto_battle['enabled'])
                self.assertTrue(state.roaming['enabled'])
                self.assertTrue(state.expedition['enabled'])
                logic.command({'type': 'start_auto_battle'}, state)  # pending expedition does not block AI

    def test_actual_battle_still_waits_then_resumes(self):
        self.state.auto_battle['enabled'] = True
        self.state.roaming['enabled'] = True
        self.service.start(self.state, self.settings)
        self.state.battle['active'] = True
        self.assertEqual(self.service.tick(self.state, 10), [])
        self.assertTrue(self.state.expedition['enabled'])
        self.state.battle['active'] = False
        packet, = self.service.tick(self.state, 13)
        self.assertEqual((packet.main, packet.sub), (31, 15))

    def test_automatic_backpack_selection_can_mix_item_types(self):
        self.state.expedition['roles']['1']['faith'] = 70
        self.state.inventory.update(ready=True, reliable=True, items={
            '3': {'item_id': 34014, 'count': 1}, '4': {'item_id': 34068, 'count': 1}})
        self.service.start(self.state, {**self.settings, 'item_id': 0})
        packet, = self.service.tick(self.state, 10)
        self.assertEqual(self.service.pending['target'], 78)
        self.assertEqual(available(self.state.inventory, 4), 0)
        self.assertEqual(available(self.state.inventory, 3), 1)
        self.event({'type': 'bag_delete', 'index': 4, 'count': 1})
        self.event({'type': 'outpost_faith', 'index': 1, 'faith': 78, 'show': 0})
        packet, = self.service.tick(self.state, self.service.next_check + 1)
        self.assertEqual(packet.payload[5:7], Writer().u16(34014).build())
        self.assertEqual(self.service.pending['target'], 80)

    def test_automatic_selection_does_not_use_locked_stock(self):
        self.state.expedition['roles']['1']['faith'] = 70
        self.state.inventory.update(ready=True, reliable=True, items={'3': {'item_id': 34014, 'count': 10, 'locked': True}})
        self.service.start(self.state, {**self.settings, 'item_id': 0})
        self.assertEqual(self.service.tick(self.state, 10), [])
        self.assertFalse(self.state.expedition['enabled'])

    def test_online_sync_requests_time_once_without_starting_automation(self):
        logic = SessionLogic()
        event = {'type': 'expedition_level', 'level': 1, 'exp': 0}
        self.assertEqual(logic.receive(event, self.state), [])
        logic.world_acknowledged = True
        packet, = logic.receive(event, self.state)
        self.assertEqual((packet.main, packet.sub, packet.payload), (31, 28, b''))
        self.assertEqual(logic.receive(event, self.state), [])
        self.assertFalse(self.state.expedition['enabled'])


class ExpeditionWire(unittest.TestCase):
    def test_bundled_official_catalog_uses_minutes_and_level_reduction(self):
        value = json.loads((RESOURCE_ROOT / 'expedition_catalog.json').read_text(encoding='utf8'))
        self.assertEqual(len(value['tasks']), 260)
        self.assertEqual(len(value['levels']), 10)
        self.assertEqual(value['tasks']['1']['name'], '遺跡探索 I')
        self.assertTrue(all(q.get('name') for q in value['tasks'].values()))
        self.assertEqual(duration(value['tasks']['1'], value['levels']['1']), 30 * 60)
        longest = max(value['tasks'].values(), key=lambda q: q['minutes'])
        self.assertEqual(longest['minutes'], 720)
        self.assertEqual(duration(longest, value['levels']['10']), 612 * 60)
        # Native code rounds minutes, then formats hours/minutes, not seconds.
        self.assertEqual(duration({'minutes': 31}, {'reduction': 150}), 26 * 60)

    def test_outpost_faith_and_strict_lengths(self):
        w = Writer().u8(1).u8(1).u8(4).u16(101).u8(0)
        for _ in range(5): w.u16(10)
        w.u8(30).raw(b'\0'*5).u8(75).u32(0).u8(0).u16(0).u8(0).u8(0).u16(0)
        s = State(); s.apply(decode(Packet(31, 6, w.build())))
        self.assertEqual(s.expedition['roles']['4']['faith'], 75)
        s.apply(decode(Packet(31, 27, b'\x04\x55\x00')))
        self.assertEqual(s.expedition['roles']['4']['faith'], 85)
        with self.assertRaises(ProtocolError): decode(Packet(31, 27, b'\x04'))

    def test_fixed_snapshot_keeps_all_empty_team_slots(self):
        payload = b'\0'* (10 * 21 + 100 + 125 + 15) + b'\x01' + b'\0'* (4 + 27)
        event = decode(Packet(31, 13, payload))
        s = State(); s.apply(event)
        self.assertEqual(len(s.expedition['teams']), 10)
        self.assertEqual(s.expedition['teams']['1']['index'], 1)
        self.assertTrue(s.expedition['ready'])

    def test_official_binary_catalog_layout(self):
        w = Writer().u32(1).u16(2).u8(1).u32(100).u8(1).u32(101).u32(102).u16(360).u8(20).u16(500)
        w.u16(1).u16(1).u16(0).raw(b'\0'*(32 + 4 + 27 + 2 + 9 + 4))
        lv = Writer().u32(1).u8(1).u32(0).u32(0).u8(2).u8(3).u16(200).u8(0).u8(0).build()
        value = parse_catalog(w.build(), lv)
        self.assertEqual(value['tasks']['2']['minutes'], 360)
        self.assertEqual(value['levels']['1']['reduction'], 200)
        with self.assertRaises(ProtocolError): parse_catalog(w.build()[:-1], lv)
        with self.assertRaises(ProtocolError): parse_catalog(w.build(), lv + b'\0')

    def test_text_table_uses_official_text_id_and_rejects_incomplete_data(self):
        original = {'tasks': {'1': {'name_id': 141001, 'area_name': 140001}}}
        text = '測試中文任務'.encode('utf-16-le')
        raw = Writer().u32(1).u32(141001).u16(len(text)).raw(text).build()
        translated = attach_names(original, raw)
        self.assertEqual(translated['tasks']['1']['name'], '測試中文任務')
        self.assertNotIn('name', original['tasks']['1'])
        with self.assertRaises(ProtocolError): attach_names(original, raw[:-1])
        with self.assertRaises(ProtocolError): attach_names({'tasks': {'2': {'name_id': 141002, 'area_name': 140001}}}, raw)


class ExpeditionClaiming(ExpeditionFixture, unittest.TestCase):
    # Use the same state fixture without rerunning the base test methods.
    def setUp(self):
        super().setUp()
        self.award = {'kind': 10, 'id': 34014, 'value': 2}
        self.service.catalog['tasks']['2'].update(rewards=[self.award],
            special_reward={'kind': 0, 'id': 0, 'value': 0})
        self.state.inventory.update(ready=True, reliable=True, capacity=5, items={})
        self.state.expedition['roles']['1']['state'] = 1
        self.state.expedition['teams']['1'].update(quest=2, members=[101, 0, 0, 0], due=9)

    def test_claim_when_all_members_busy_waits_for_result_and_bag_before_redeploy(self):
        self.service.start(self.state, self.settings)
        packet, = self.service.tick(self.state, 10)
        self.assertEqual((packet.main, packet.sub, packet.payload), (31, 16, b'\x01'))
        self.assertEqual(self.state.expedition['teams']['1']['quest'], 2)
        self.event({'type': 'expedition_result', 'index': 2, 'result': 1, 'rewards': []})
        self.assertIsNotNone(self.service.pending)  # another team cannot confirm this claim
        self.event({'type': 'expedition_result', 'index': 1, 'result': 1, 'rewards': [self.award]})
        self.assertEqual(self.service.tick(self.state, 11), [])
        self.assertIsNotNone(self.service.pending)
        self.event({'type': 'bag_add', 'item': {'index': 3, 'item_id': 34014, 'count': 2}})
        self.assertIsNone(self.service.pending)
        self.assertEqual(self.state.expedition['claimed'], 1)
        self.event({'type': 'outpost_status', 'index': 1, 'state': 0})
        packet, = self.service.tick(self.state, self.service.next_check + 1)
        self.assertEqual((packet.main, packet.sub), (31, 15))

    def test_bag_can_arrive_before_result(self):
        self.service.start(self.state, self.settings)
        self.service.tick(self.state, 10)
        self.event({'type': 'bag_add', 'item': {'index': 3, 'item_id': 34014, 'count': 2}})
        self.assertIsNotNone(self.service.pending)
        self.event({'type': 'expedition_result', 'index': 1, 'result': 1, 'rewards': [self.award]})
        self.assertIsNone(self.service.pending)

    def test_currency_only_result_needs_no_item_event(self):
        self.service.start(self.state, self.settings)
        self.service.tick(self.state, 10)
        self.event({'type': 'expedition_result', 'index': 1, 'result': 0,
                    'rewards': [{'kind': 6, 'id': 1, 'value': 10}]})
        self.assertIsNone(self.service.pending)
        self.assertEqual(self.state.expedition['claimed'], 1)

    def test_success_minimum_does_not_block_claiming_completed_tasks(self):
        self.service.start(self.state, {**self.settings, 'min_success': 100})
        packet, = self.service.tick(self.state, 10)
        self.assertEqual((packet.main, packet.sub), (31, 16))

    def test_no_early_claim_and_option_can_be_disabled(self):
        self.service.start(self.state, self.settings)
        self.assertEqual(self.service.tick(self.state, 9), [])
        self.service.stop(self.state)
        self.service.start(self.state, {**self.settings, 'auto_claim': False})
        self.assertEqual(self.service.tick(self.state, 10), [])
        self.assertIsNone(self.service.pending)

    def test_unknown_or_full_bag_pauses_without_sending(self):
        self.service.start(self.state, self.settings)
        self.state.inventory['reliable'] = False
        self.assertEqual(self.service.tick(self.state, 10), [])
        self.state.inventory.update(reliable=True, capacity=1, items={'1': {'item_id': 34014, 'count': 1}})
        self.assertEqual(self.service.tick(self.state, 13), [])
        self.assertIn('空間', self.state.expedition['status'])
        self.state.inventory['items'] = {}
        packet, = self.service.tick(self.state, 16)
        self.assertEqual((packet.main, packet.sub), (31, 16))

    def test_claim_timeout_never_retries(self):
        self.service.start(self.state, self.settings)
        self.service.tick(self.state, 10)
        self.assertEqual(self.service.tick(self.state, 31), [])
        self.assertTrue(self.state.expedition['uncertain'])
        self.assertFalse(self.state.expedition['enabled'])
        self.assertEqual(self.service.tick(self.state, 100), [])

    def test_quest_refresh_after_auto_claim_consumes_official_show_flag(self):
        # Official 1262 ExpeditionMgr.RevExpeditionQuestUpdate reads 50
        # (index:u8, quest:u16) pairs AND one ReadBoolean() show flag.
        self.service.start(self.state, self.settings)
        sent, = self.service.tick(self.state, 10)
        self.assertEqual((sent.main, sent.sub, sent.payload), (31, 16, bytes((1,))))
        claim = Writer().u8(1).u8(1).u16(0).u16(0).u8(10).u32(34014).u32(2)
        self.event(decode(Packet(31, 16, claim.build())))
        self.assertIsNotNone(self.service.pending)

        entries = b''.join(Writer().u8(i).u16(i if i <= 2 else 0).build()
                           for i in range(1, 51))
        for flag in (0, 1):
            update = decode(Packet(31, 19, entries + bytes([flag])))
            self.assertEqual(update['show'], bool(flag))
            self.assertEqual(update['quests']['1'], 1)
            self.assertEqual(update['quests']['50'], 0)
            self.event(update)
            self.assertIsNotNone(self.service.pending)
        self.event({'type': 'bag_add', 'item': {'index': 3, 'item_id': 34014, 'count': 2}})
        self.assertEqual(self.state.expedition['claimed'], 1)
        self.assertIsNone(self.service.pending)
        for malformed in (entries, entries + bytes((1,0))):
            with self.assertRaises(ProtocolError):
                decode(Packet(31, 19, malformed))

    def test_quest_refresh_packet_after_claim_does_not_cause_client_error(self):
        from unittest.mock import Mock
        from wlre.network.client import run_client
        from wlre.network.wire import encode
        result = Writer().u8(1).u8(1).u16(0).u16(0).u8(10).u32(34014).u32(2).build()
        entries = b''.join(Writer().u8(i).u16(i if i <= 2 else 0).build()
                           for i in range(1, 51)) + bytes((1,))
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.recv.side_effect = [
            encode(Packet(31, 16, result), 0),
            encode(Packet(31, 19, entries), 0),
            b'',
        ]
        events = []
        with patch('wlre.network.client.socket.create_connection', return_value=connection):
            state = run_client('fixture.invalid', 1, {'rx_xor': 0, 'tx_xor': 0},
                               events.append, duration=None)
        self.assertEqual(state.phase, 'disconnected')
        self.assertIn('expedition_quests', [e.get('type') for e in events])
        self.assertEqual([e.get('reason') for e in events if e.get('type') == 'connection_closed'],
                         ['server_closed'])
        self.assertFalse(any(e.get('reason') == 'client_error' for e in events))

    def test_reward_wire_is_structured_and_catalog_has_capacity_metadata(self):
        w = Writer().u8(1).u8(1).u16(0).u16(0).u8(10).u32(34014).u32(2)
        self.assertEqual(decode(Packet(31, 16, w.build()))['rewards'], [self.award])
        from wlre.services.expedition import claim_space
        official = json.loads((RESOURCE_ROOT / 'expedition_catalog.json').read_text(encoding='utf8'))
        self.assertTrue(all(claim_space(q) is not None for q in official['tasks'].values()))
