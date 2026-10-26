"""P1b / P1a: automation intent may coexist with instance manual actions."""
import unittest

from wlre.core.state import State
from wlre.network.wire import ProtocolError
from wlre.services.instance_activity import instance_background_blockers
from wlre.services.instance_creation import create
from wlre.services.instance_room_flow import _activity_guard
from wlre.ui.instance_ui import creation_block_reasons


def ready_state():
    state = State(phase='world_ready', initial_data_complete=True)
    state.player = {'role_id': 678, 'scene': 20000}
    return state


class AutomationInstanceLockTests(unittest.TestCase):
    def test_enabled_flags_not_real_conflicts(self):
        for name, key in (
            ('roaming', 'enabled'), ('alchemy', 'enabled'),
            ('expedition', 'enabled'), ('crafting', 'auto_continue'),
        ):
            with self.subTest(name=name):
                state = ready_state()
                state.__dict__[name][key] = True
                self.assertEqual(instance_background_blockers(state), ())
                self.assertEqual(instance_background_blockers(state.snapshot()), ())
                self.assertNotIn('自動', '、'.join(creation_block_reasons(
                    state.snapshot(), 'main', True)))
                _activity_guard(state, joining=False)
                packets = create(state, {'mode': 'main', 'public': True,
                                         'map_id': 30012})
                self.assertEqual(len(packets), 1)
                self.assertIsNotNone(state.instances['main']['create_pending'])

    def test_still_blocks_real_pending_and_uncertain(self):
        for name, key in (('maintenance', 'pending'),
                          ('maintenance', 'uncertain'),
                          ('expedition', 'pending'), ('expedition', 'uncertain'),
                          ('alchemy', 'pending'), ('alchemy', 'uncertain'),
                          ('crafting', 'pending'), ('crafting', 'uncertain')):
            with self.subTest(name=name, key=key):
                state = ready_state()
                state.__dict__[name][key] = (
                    {'started': 1} if key == 'pending' else True)
                self.assertTrue(instance_background_blockers(state))
                reasons = creation_block_reasons(state.snapshot(), 'coop', True)
                self.assertTrue(any('等待回覆' in x or '結果不明' in x
                                    for x in reasons))
                with self.assertRaises(ProtocolError):
                    _activity_guard(state, joining=False)
                with self.assertRaises(ProtocolError):
                    create(state, {'mode': 'coop', 'public': True,
                                   'dungeon_id': 21, 'player_count': 2,
                                   'confirm_cost': True})

    def test_active_battle_and_event_still_block_manual_rooms(self):
        for field in ('battle', 'event_flow'):
            state = ready_state()
            if field == 'battle':
                state.battle['active'] = True
            else:
                state.event_flow['blocked'] = True
            with self.assertRaises(ProtocolError):
                _activity_guard(state, joining=False)
            with self.assertRaises(ProtocolError):
                create(state, {'mode': 'main', 'public': True, 'map_id': 30012})


if __name__ == '__main__':
    unittest.main()
