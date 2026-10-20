"""Regression tests for health-25804: battle and maintenance health evidence."""
import tempfile
import unittest

from wlre.core.diagnostics import Diagnostics
from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.service_scheduler import auto_battle_status_event, maintenance_trace_event
from wlre.services.battle.auto_battle import defaults


class Health25804Tests(unittest.TestCase):
    def test_two_battles_with_same_ai_status_are_both_logged(self):
        state = State()
        state.player = {'role_id': 9, 'name': 'private name'}
        state.battle = {'active': True, 'round': 1, 'war_style': 16}
        state.auto_battle = {'enabled': True, 'status': 'submitted',
                             'reason': 'private reason', 'stop_source': 'none'}
        state.battle_count = 1
        with tempfile.TemporaryDirectory() as folder:
            health = Diagnostics(folder)
            self.assertTrue(health.auto_battle_status(auto_battle_status_event(state)))
            self.assertFalse(health.auto_battle_status(auto_battle_status_event(state)))
            state.battle_count = 2
            self.assertTrue(health.auto_battle_status(auto_battle_status_event(state)))
            health.close()
            saved = health.path.read_text(encoding='utf-8')
        self.assertEqual(saved.count('auto_battle state=submitted'), 2)
        self.assertIn('battle_count=1', saved)
        self.assertIn('battle_count=2', saved)
        self.assertNotIn('private', saved)

    def test_manual_and_maintenance_auto_stop_sources(self):
        state = State()
        logic = SessionLogic()
        logic.world_acknowledged = True
        logic.auto_battle.start(state, defaults())
        logic.command({'type': 'stop_auto_battle'}, state)
        self.assertEqual(state.auto_battle['stop_source'], 'manual')
        logic.auto_battle.start(state, defaults())
        self.assertEqual(state.auto_battle['stop_source'], 'none')
        logic.auto_battle.stop(state, 'private item name', source='maintenance_uncertain')
        self.assertEqual(state.auto_battle['stop_source'], 'maintenance_uncertain')
        with tempfile.TemporaryDirectory() as folder:
            health = Diagnostics(folder)
            self.assertTrue(health.auto_battle_status(auto_battle_status_event(state)))
            health.close()
            saved = health.path.read_text(encoding='utf-8')
        self.assertIn('stop_source=maintenance_uncertain', saved)
        self.assertNotIn('private item name', saved)

    def test_maintenance_pending_and_uncertain_are_redacted(self):
        state = State()
        state.battle_count = 3
        logic = SessionLogic()
        logic.maintenance.pending = {'action': 'repair', 'due': 120,
                                     'index': 17, 'item_id': 123456,
                                     'owner': 999}
        pending = maintenance_trace_event(state, logic, 105)
        self.assertEqual((pending['phase'], pending['action'], pending['elapsed_s'],
                          pending['battle_count']),
                         ('pending', 'repair', 5, 3))
        self.assertNotIn('index', pending)
        self.assertNotIn('item_id', pending)
        self.assertNotIn('owner', pending)
        logic.maintenance.uncertain = True
        uncertain = maintenance_trace_event(state, logic, 122)
        self.assertEqual((uncertain['phase'], uncertain['elapsed_s']),
                         ('uncertain', 22))
        with tempfile.TemporaryDirectory() as folder:
            health = Diagnostics(folder)
            self.assertTrue(health.maintenance_trace(pending))
            self.assertTrue(health.maintenance_trace(uncertain))
            self.assertFalse(health.maintenance_trace({
                **pending, 'action': 'token=secret'}))
            self.assertFalse(health.maintenance_trace({
                **pending, 'elapsed_s': True}))
            health.close()
            saved = health.path.read_text(encoding='utf-8')
        self.assertIn('maintenance phase=pending action=repair elapsed_s=5', saved)
        self.assertIn('maintenance phase=uncertain action=repair elapsed_s=22', saved)
        self.assertNotIn('123456', saved)
        self.assertNotIn('secret', saved)

    def test_s51_distinct_malformed_shapes_keep_context_not_bytes(self):
        base = {'type': 'battle_attribute_invalid', 'main': 51, 'sub': 1,
                'payload_bytes': 10, 'trailing_bytes': 3,
                'battle_count': 2, 'battle_war_style': 16, 'battle_active': True}
        with tempfile.TemporaryDirectory() as folder:
            health = Diagnostics(folder)
            self.assertTrue(health.battle_attribute_invalid(base))
            self.assertFalse(health.battle_attribute_invalid(base))
            self.assertTrue(health.battle_attribute_invalid({
                **base, 'payload_bytes': 8, 'trailing_bytes': 1}))
            self.assertFalse(health.battle_attribute_invalid({
                **base, 'battle_war_style': 'private'}))
            health.close()
            saved = health.path.read_text(encoding='utf-8')
        self.assertEqual(saved.count('protocol_warning packet_main=51'), 2)
        self.assertIn('payload_bytes=10 complete_records=1 trailing_bytes=3', saved)
        self.assertIn('battle_count=2 war_style=16 battle_active=1', saved)
        self.assertNotIn('private', saved)


if __name__ == '__main__':
    unittest.main()
