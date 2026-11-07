"""Offline projection/packet guard parity for observed Ark fight rewards."""
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from wlre.core.state import State
from wlre.network.wire import Packet, ProtocolError
from wlre.services import daily_assistant as assistant, star_ark as ark


class AssistantGuardSafetyTests(unittest.TestCase):
    def setUp(self):
        self.token = (True, 'a' * 64)
        self.catalog = {'fights': {1: {'agent': 0, 'awards': [
            {'kind': 10, 'id': 40001, 'value': 1}]}}}
        self.runtime = SimpleNamespace(ark_catalog=self.catalog,
                                       catalog_identity=SimpleNamespace(key=self.token[1]))
        for name, value in [('current_runtime', self.runtime),
                            ('current_catalog_token', self.token)]:
            mock = patch('wlre.services.world.dynamic_bundle_runtime.' + name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.state = State(phase='world_ready', initial_data_complete=True)
        self.state.player['role_id'] = 1
        self.state.auto_battle['enabled'] = True
        self.event = dict(index=1, id=1, kind=1, main=False, planet=1)
        self.state.star_ark.update(ready=True, role=1, catalog_token=self.token,
                                  planet=1, events_ready=True, events={1: self.event})
        self.state.daily_tasks.update(ready=True, groups_ready=True, catalog_ready=True,
                                     catalog_token=self.token, rows=[dict(
                                         cycle=1, index=1, condition_kind=9,
                                         condition_params=[1], progress=0, goal=1)])
        self.state.inventory.update(ready=True, reliable=True, revision=1, capacity=1,
                                    items={1: {'item_id': 40002, 'count': 1}})

    def row(self):
        return assistant.view(self.state.snapshot())['rows'][0]

    def assert_blocked(self, reason):
        before = self.state.snapshot()
        row = self.row()
        self.assertEqual(row['classification'], 'blocked')
        self.assertIn(reason, row['reason'])
        with self.assertRaisesRegex(ProtocolError, reason):
            ark.begin(self.state, 'fight', True, self.event, now=1)
        self.assertEqual(self.state.snapshot(), before)

    def test_full_bag_blocks_projection_and_begin(self):
        self.assert_blocked('背包剩餘 0 格')

    def test_unknown_awards_and_agent_capacity_fail_closed(self):
        for field, value, reason in [
            ('awards', [{'kind': 99, 'id': 1, 'value': 1}], '未支援種類'),
            ('awards', [], '沒有可驗證的獎勵'),
            ('agent', 1, '情報員容量'),
        ]:
            with self.subTest(reason=reason):
                original = deepcopy(self.catalog['fights'][1])
                self.catalog['fights'][1][field] = value
                self.assert_blocked(reason)
                self.catalog['fights'][1] = original

    def test_missing_catalog_or_stale_identity_fail_closed(self):
        self.state.inventory['items'] = {}
        for catalog, token, identity in [
            (None, self.token, self.runtime.catalog_identity),
            (self.catalog, (True, 'b' * 64), self.runtime.catalog_identity),
            (self.catalog, self.token, None),
        ]:
            with self.subTest(token=token, identity=identity):
                self.runtime.ark_catalog = catalog
                self.runtime.catalog_identity = identity
                with patch('wlre.services.world.dynamic_bundle_runtime.current_catalog_token',
                           return_value=token):
                    self.assertEqual(self.row()['classification'], 'blocked')
                    with self.assertRaises(ProtocolError):
                        ark.begin(self.state, 'fight', True, self.event, now=1)

    def test_daily_identity_must_match_current_ark_identity(self):
        self.state.inventory['items'] = {}
        self.state.daily_tasks['catalog_token'] = (True, 'b' * 64)
        self.assertEqual(self.row()['classification'], 'blocked')

    def test_malformed_snapshot_tokens_fail_closed(self):
        self.state.inventory['items'] = {}
        for token in [None, 'a' * 64, (1, self.token[1]), (True, None),
                      (True,), (True, self.token[1], 'extra')]:
            with self.subTest(token=token):
                self.state.star_ark['catalog_token'] = token
                self.state.daily_tasks['catalog_token'] = token
                self.assertEqual(self.row()['classification'], 'blocked')

    def test_missing_or_unreliable_inventory_evidence_fails_closed(self):
        self.state.inventory['items'] = {}
        for field, value, reason in [('ready', False, '背包完整快照'),
                                     ('reliable', False, '一致性驗證'),
                                     ('capacity', None, '容量或格位')]:
            with self.subTest(field=field):
                original = self.state.inventory[field]
                self.state.inventory[field] = value
                self.assert_blocked(reason)
                self.state.inventory[field] = original

    def test_missing_fight_definition_fails_closed(self):
        self.catalog['fights'] = {}
        self.assert_blocked('沒有同版戰鬥事件資料')

    def test_eligible_fight_preserves_exact_packet_guard(self):
        self.state.inventory['items'] = {}
        self.assertEqual(self.row()['classification'], 'automatic')
        self.assertEqual(ark.begin(self.state, 'fight', True, self.event, now=1),
                         [Packet(191, 4, b'\x01\x01\x00')])

    def test_eligible_alternative_event_is_not_hidden(self):
        self.state.star_ark['events'][2] = dict(index=2, id=2, kind=1, main=False, planet=1)
        self.catalog['fights'][2] = {'agent': 0, 'awards': [{'kind': 6, 'id': 8, 'value': 1}]}
        self.assertEqual(self.row()['classification'], 'automatic')
        self.state.star_ark['events'][2]['kind'] = 3
        self.assertEqual(self.row()['classification'], 'automatic')

    def test_projection_is_read_only_without_packets_or_scheduler(self):
        before = self.state.snapshot()
        catalog_before = deepcopy(self.catalog)
        with patch.object(ark, 'begin', side_effect=AssertionError('must not execute')), \
                patch.object(ark, 'tick', side_effect=AssertionError('must not schedule')), \
                patch.object(ark, 'Packet', side_effect=AssertionError('must not build packets')):
            for _ in range(2):
                result = assistant.view(before)
                self.assertEqual(result['rows'][0]['classification'], 'blocked')
        self.assertEqual(before, self.state.snapshot())
        self.assertEqual(catalog_before, self.catalog)

    def test_json_snapshot_matches_native_guard(self):
        for items, classification in [({}, 'automatic'),
                                      ({1: {'item_id': 40002, 'count': 1}}, 'blocked')]:
            self.state.inventory['items'] = items
            snapshot = json.loads(json.dumps(self.state.snapshot()))
            self.assertEqual(assistant.view(snapshot)['rows'][0]['classification'], classification)
        self.state.inventory['items'] = {}
        self.state.star_ark['attempted'] = [ark._event_key(self.state.star_ark, self.event, self.token)]
        snapshot = json.loads(json.dumps(self.state.snapshot()))
        self.assertIn('已要求執行', assistant.view(snapshot)['rows'][0]['reason'])


if __name__ == '__main__':
    unittest.main()
