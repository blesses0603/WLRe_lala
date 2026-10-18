import queue
import unittest
from wlre.core.maintenance import PeriodicCleanup
from wlre.core.state import State
from wlre.ui.event_queue import DisplayQueue


class PeriodicCleanupTests(unittest.TestCase):
    def test_two_hour_deadline_repeats_without_catchup_burst(self):
        now = [0.0]; timer = PeriodicCleanup(lambda: now[0])
        now[0] = 7199; self.assertFalse(timer.due())
        now[0] = 7200; self.assertTrue(timer.due()); self.assertFalse(timer.due())
        now[0] = 14400; self.assertTrue(timer.due())
        now[0] = 50000; self.assertTrue(timer.due()); self.assertFalse(timer.due())

    def test_cleanup_preserves_messages_controls_latest_state_and_fresh_updates(self):
        now = [0.0]; display = DisplayQueue(clock=lambda: now[0])
        display.put(('event', {'type': 'walk', 'role_id': 2}))
        keep = [('event', {'type': 'chat', 'text': 'hello'}),
                ('event', {'type': 'team_invitation'}), ('error', 'error'),
                ('state', {'player': 1}), ('health', {'status': 'receiving'}),
                ('event', {'type': 'connection_closed'}), ('finished', None)]
        for item in keep: display.put(item)
        now[0] = 7199; self.assertIsNone(display.cleanup())
        fresh = ('event', {'type': 'walk', 'role_id': 3})
        display.put(fresh)
        now[0] = 7200; self.assertEqual(display.cleanup(), 1)
        result = []
        while not display.empty(): result.append(display.get_nowait())
        for item in keep + [fresh]: self.assertIn(item, result)
        self.assertEqual(len(result), len(keep) + 1)
        with self.assertRaises(queue.Empty): display.get_nowait()
        now[0] = 14400; self.assertEqual(display.cleanup(), 0)

    def test_history_cleanup_preserves_authoritative_location_and_own_cache(self):
        state = State(); state.player = {'role_id': 1}
        state.remember_position(1, 10, 20); state.remember_position(2, 30, 40)
        location = state.location; inventory = state.inventory
        self.assertEqual(state.clear_position_history(), 1)
        self.assertEqual(state.positions, {'1': [10, 20]})
        self.assertIs(state.location, location); self.assertIs(state.inventory, inventory)
        self.assertEqual(state.clear_position_history(), 0)
        state.remember_position(2, 50, 60)
        self.assertEqual(state.positions['2'], [50, 60])
