"""Server-companion identity, buffered S8 attributes and UI label regressions."""
import unittest

from wlre.core.state import State
from wlre.network.wire import ProtocolError
from wlre.services.battle.companions import ambiguous_identity, command, problem


def companion(index, npc_id, base_str=12):
    return {
        'ready': True, 'index': index, 'npc_id': npc_id,
        'str': base_str, 'con': 11, 'int': 8, 'wis': 6, 'agi': 9,
        'skill_slots': [], 'equips': [], 'can_grow': 1,
    }


class CompanionIdentitySafetyTests(unittest.TestCase):
    def setUp(self):
        self.state = State(phase='world_ready')
        self.state.player = {'role_id': 7}

    def test_buffered_s8_before_first_s15_is_applied_to_correct_slot(self):
        self.state.apply({'type': 'attribute_set', 'entity': 'follow:2',
                          'human_kind': 4, 'index': 2,
                          'kind': 28, 'parameter': 0, 'value': 321})
        self.state.apply({'type': 'companion_snapshot',
                          'companions': [companion(2, 101)]})
        self.assertEqual(self.state.knowledge['companions']['2']['stats']['str'], 321)

    def test_reused_slot_does_not_inherit_previous_npc_stats(self):
        self.state.apply({'type': 'companion_snapshot',
                          'companions': [companion(2, 101)]})
        self.state.apply({'type': 'attribute_set', 'entity': 'follow:2',
                          'human_kind': 4, 'index': 2,
                          'kind': 28, 'parameter': 0, 'value': 444})
        self.assertEqual(self.state.knowledge['companions']['2']['stats']['str'], 444)
        self.state.apply({'type': 'companion_snapshot',
                          'companions': [companion(2, 102, base_str=20)]})
        self.assertEqual(self.state.knowledge['companions']['2']['stats']['str'], 20)
        self.assertNotIn('follow:2', self.state.attributes)

    def test_delete_clears_slot_scoped_attribute_cache(self):
        self.state.apply({'type': 'companion_snapshot',
                          'companions': [companion(2, 101)]})
        self.state.apply({'type': 'attribute_set', 'entity': 'follow:2',
                          'human_kind': 4, 'index': 2,
                          'kind': 28, 'parameter': 0, 'value': 444})
        self.state.apply({'type': 'companion_delete',
                          'owner_id': 7, 'index': 2})
        self.assertNotIn('2', self.state.knowledge['companions'])
        self.assertNotIn('follow:2', self.state.attributes)

    def test_duplicate_npc_identity_blocks_ambiguous_companion_commands(self):
        self.state.knowledge.update(companions_ready=True, companions={
            '2': {'ready': True, 'index': 2, 'npc_id': 101,
                  'stats': {'can_grow': 1}},
            '5': {'ready': True, 'index': 5, 'npc_id': 101,
                  'stats': {'can_grow': 1}},
        }, active_npc_id=101)
        state = self.state.snapshot()
        self.assertTrue(ambiguous_identity(state['knowledge'], 101))
        for action in ('deploy', 'rest'):
            with self.subTest(action=action):
                self.assertIn('格位身份', problem(state, 2, 101, action))
                with self.assertRaises(ProtocolError):
                    command(self.state, {'action': action, 'index': 2, 'npc_id': 101})

    def test_unique_npc_identity_keeps_original_deploy_packet(self):
        self.state.knowledge.update(companions_ready=True, companions={
            '2': {'ready': True, 'index': 2, 'npc_id': 101,
                  'stats': {'can_grow': 1}},
        })
        self.assertFalse(ambiguous_identity(self.state.snapshot()['knowledge'], 101))
        p = command(self.state, {'action': 'deploy', 'index': 2, 'npc_id': 101})
        self.assertEqual((p.main, p.sub, p.payload), (19, 1, b'\x65\x00\x00\x00'))


if __name__ == '__main__':
    unittest.main()
