"""State event routing regression: ordering, payload semantics and thread ownership."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import unittest
from unittest.mock import patch

import wlre.core.state as state_module
from wlre.core.state import State
from wlre.core.state_events import (
    WORLD_KINDS, BATTLE_KINDS, SESSION_KINDS, dispatch_local,
)


class StateEventRoutingTests(unittest.TestCase):
    def test_each_local_event_domain_is_disjoint(self):
        self.assertFalse(WORLD_KINDS & BATTLE_KINDS)
        self.assertFalse(WORLD_KINDS & SESSION_KINDS)
        self.assertFalse(BATTLE_KINDS & SESSION_KINDS)
        self.assertIn('event_rejected', SESSION_KINDS)
        self.assertTrue({'gold_snapshot','gold_delta','gold_limit'} <= SESSION_KINDS)
        # Three official S26 gold event variants extend the previous 26 cases.
        self.assertEqual(len(WORLD_KINDS | BATTLE_KINDS | SESSION_KINDS), 29)

    def test_service_update_order_and_single_router_call(self):
        state = State()
        calls = []
        names = (
            'apply_recovery', 'apply_guild', 'apply_activity',
            'apply_crafting', 'apply_storage', 'apply_live',
            'apply_points_event', 'apply_party', 'apply_expedition',
        )
        with ExitStack() as stack:
            for name in names:
                stack.enter_context(patch.object(
                    state_module, name,
                    side_effect=lambda _s, _e, name=name: calls.append(name)))
            stack.enter_context(patch.object(
                state_module, 'dispatch_local',
                side_effect=lambda _s, _e, **kw: calls.append('dispatch_local')))
            stack.enter_context(patch.object(
                state_module, 'observe_efficiency',
                side_effect=lambda _s, _e: calls.append('observe_efficiency')))
            state.apply({'type': 'unknown_fixture'})
        self.assertEqual(calls, [*names, 'dispatch_local', 'observe_efficiency'])
        self.assertEqual(state.packet_count, 1)

    def test_world_position_follows_server_ack_not_requested_target(self):
        state = State()
        state.apply({'type': 'world_player',
                     'player': {'role_id': 17, 'scene': 101, 'x': 8, 'y': 9}})
        self.assertEqual(state.phase, 'world_received')
        self.assertEqual(state.location['confirmed']['x'], 8)
        state.apply({'type': 'movement_request', 'x': 14, 'y': 15})
        self.assertFalse(state.location['confirmed_is_current'])
        self.assertEqual(state.location['requested_destination']['x'], 14)
        state.apply({'type': 'walk', 'role_id': 17, 'x': 14, 'y': 15})
        self.assertEqual(state.player['x'], 8)  # A walk command is not a position confirmation.
        self.assertEqual(state.movement_check['status'], 'waiting')
        state.apply({'type': 'position_snapshot', 'role_id': 17, 'scene': 101,
                     'x': 14, 'y': 15, 'source': 'S3'})
        self.assertEqual(state.player['x'], 14)
        self.assertEqual(state.movement_check['status'], 'matched')
        self.assertTrue(state.location['confirmed_is_current'])
        self.assertEqual(state.positions['17'], [14, 15])
        self.assertEqual(state.navigation['revision'], 2)

    def test_session_readiness_and_raw_attribute_replacements(self):
        state = State()
        state.apply({'type': 'login_result', 'result': 0})
        self.assertEqual(state.phase, 'authenticated')
        state.apply({'type': 'role_list_available', 'roles': [{'index': 2}]})
        self.assertEqual(state.phase, 'role_selection')
        state.apply({'type': 'initial_data_complete'})
        self.assertTrue(state.initial_data_complete)
        state.apply({'type': 'event_active', 'sub': 1})
        self.assertTrue(state.event_flow['blocked'])
        state.apply({'type': 'event_end'})
        self.assertFalse(state.event_flow['blocked'])
        state.apply({'type': 'attribute_set', 'entity': 'self',
                     'kind': 27, 'parameter': 0, 'value': 123})
        state.apply({'type': 'attribute_set', 'entity': 'self',
                     'kind': 27, 'parameter': 0, 'value': 89})
        self.assertEqual(state.attributes['self']['27:0'], 89)
        state.apply({'type': 'unimplemented'})
        self.assertEqual(state.unimplemented_count, 1)

    def test_battle_round_and_server_unit_updates(self):
        state = State()
        state.apply({'type': 'battle_start', 'stage': 12, 'fight_number': 3,
                     'units': [{'col': 1, 'row': 0, 'pid': 17, 'hp': 90, 'sp': 20}]})
        self.assertEqual(state.battle_count, 1)
        self.assertTrue(state.battle['active'])
        state.apply({'type': 'battle_attribute_set',
                     'values': [{'col': 1, 'row': 0, 'kind': 25, 'value': 73}]})
        self.assertEqual(state.battle_units['1:0']['hp'], 73)
        state.apply({'type': 'round_start', 'round': 2})
        state.apply({'type': 'battle_command_sent', 'col': 1, 'row': 0})
        state.apply({'type': 'attack_result',
                     'actions': [{'col': 1, 'row': 0, 'damage': 9999}]})
        self.assertEqual(state.battle['actions'], 1)
        self.assertEqual(state.battle['commands']['1:0']['status'], 'resolved')
        self.assertEqual(state.battle_units['1:0']['hp'], 73)  # Never subtract speculative damage.
        state.apply({'type': 'winner', 'side': 1})
        self.assertFalse(state.battle['active'])
        self.assertEqual(state.battle['winner_side'], 1)

    def test_world_geometry_predicate_only_marks_relevant_scene(self):
        state = State()
        state.apply({'type': 'world_player',
                     'player': {'role_id': 1, 'scene': 100, 'x': 1, 'y': 1}})
        event = {'type': 'navigation_geometry_change', 'reason': 'dynamic object'}
        with patch.object(state_module, 'affects_navigation', return_value=False) as allowed:
            state.apply(event)
            allowed.assert_called_once_with(event, 100)
        self.assertFalse(state.navigation['stale'])
        with patch.object(state_module, 'affects_navigation', return_value=True):
            state.apply(event)
        self.assertTrue(state.navigation['stale'])
        self.assertEqual(state.navigation['reasons'], ['dynamic object'])

    def test_detached_snapshot_and_scope_authority_remain_enforced(self):
        state = State()
        state.apply({'type': 'world_player',
                     'player': {'role_id': 1, 'scene': 99, 'x': 3, 'y': 4}})
        copy = state.snapshot()
        copy['player']['x'] = 999
        self.assertEqual(state.player['x'], 3)
        with state.editing('expedition'):
            with self.assertRaises(RuntimeError):
                state.player['x'] = 99
        with ThreadPoolExecutor(max_workers=1) as workers:
            for fn in (state.snapshot, lambda: state.apply({'type': 'unimplemented'})):
                with self.subTest(fn=fn), self.assertRaises(RuntimeError):
                    workers.submit(fn).result(timeout=5)
        self.assertEqual(state.unimplemented_count, 0)

    def test_unrecognized_event_still_runs_service_observers(self):
        state = State()
        before = state.packet_count
        dispatch_local(state, {'type': 'new_future_server_event'},
                       affects_navigation=lambda *_: False)
        self.assertEqual(state.packet_count, before)  # Router never owns counters.
        state.apply({'type': 'new_future_server_event'})
        self.assertEqual(state.packet_count, before + 1)


if __name__ == '__main__':
    unittest.main()
