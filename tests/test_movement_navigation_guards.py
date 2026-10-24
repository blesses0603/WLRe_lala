"""Exercise path interruption without sockets or a verified live mesh."""
import unittest
from wlre.core.state import State
from wlre.services.world.movement import Movement


class Converter:
    def route(self, repository, scene, start, goal, **kwargs):
        return {'points': [[0, 0, 0], [10000, 0, 0]]}

    def to_packet(self, scene, x, z):
        return x / 10, z / 10


class MovementGuards(unittest.TestCase):
    def moving(self):
        state = State()
        state.player = {'role_id': 1, 'scene': 12170, 'x': 0, 'y': 0}
        state.confirm_location(12170, 0, 0, 'S3-1')
        state.navigation['scene'] = 12170
        service = Movement(Converter(), object())
        service.start(state, 1000, 0, 0)
        return state, service

    def test_state_changes_stop_before_the_next_packet(self):
        changes = [
            lambda s: s.player.update(scene=12171),
            lambda s: s.player.update(role_id=2),
            lambda s: s.battle.update(active=True),
            lambda s: s.event_flow.update(blocked=True),
            lambda s: s.navigation.update(stale=True),
            lambda s: s.navigation.update(revision=1),
            lambda s: s.activities.update(crafting=True),
            lambda s: s.party['teams'].update({'2': {'leader_id': 2, 'members': [2, 1]}}),
        ]
        for change in changes:
            with self.subTest(change=change):
                state, service = self.moving()
                change(state)
                self.assertEqual(service.tick(state, .2), [])
                self.assertFalse(service.active)
                self.assertEqual(state.local_movement['status'], 'stopped')

    def test_server_correction_stops_old_route(self):
        state, service = self.moving()
        service.observe({'type': 'position_snapshot', 'role_id': 1}, state)
        self.assertEqual(service.tick(state, .2), [])
        self.assertEqual(state.local_movement['status'], 'stopped')

    def test_relevant_obstacle_event_stops_route_without_claiming_rebuild(self):
        state, service = self.moving()
        event = {'type': 'navigation_geometry_change', 'reason': 'test_obstacle',
                 'geometry_scope': 'world', 'affects_geometry': True, 'details_parsed': True}
        state.apply(event)
        service.observe(event, state)
        self.assertTrue(state.navigation['stale'])
        self.assertFalse(state.navigation['runtime_geometry_verified'])
        self.assertFalse(service.active)
        self.assertEqual(service.tick(state, .2), [])

    def test_authoritative_fix_is_required_to_match_the_goal(self):
        state, service = self.moving()
        state.apply({'type': 'walk', 'role_id': 1, 'x': 1000, 'y': 0})
        self.assertEqual(state.movement_check['status'], 'waiting')
        state.apply({'type': 'position_snapshot', 'role_id': 1, 'scene': 12170,
                     'x': 500, 'y': 0, 'source': 'S7-1'})
        self.assertEqual(state.movement_check['status'], 'different_position')
        state.apply({'type': 'position_snapshot', 'role_id': 1, 'scene': 12170,
                     'x': 1000, 'y': 0, 'source': 'S7-1'})
        self.assertEqual(state.movement_check['status'], 'matched')

    def test_local_completion_does_not_confirm_server_arrival(self):
        state, service = self.moving()
        for tick in range(1, 16):
            service.tick(state, tick * .2)
        self.assertFalse(service.active)
        self.assertEqual(state.local_movement['status'], 'finished')
        self.assertEqual(state.movement_check['status'], 'waiting')
        self.assertIsNone(state.movement_check['confirmation'])

    def test_blocked_loop_does_not_catch_up_with_a_packet_burst(self):
        state, service = self.moving()
        self.assertEqual(len(service.tick(state, 60)), 1)
        self.assertAlmostEqual(state.local_movement['x'], 70)
        self.assertEqual(service.tick(state, 60), [])
