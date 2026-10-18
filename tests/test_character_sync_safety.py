"""Character preview and authoritative allocation safety regressions."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from wlre.network.wire import ProtocolError
from wlre.services.battle.attribute_points import (
    KEYS, baseline, allocation, begin, apply_event, expire, defaults,
    preview_block_reason,
)
from wlre.ui.attribute_points_ui import AttributePointWindow


def snapshot(role_id=100):
    return {
        'phase': 'world_ready',
        'player': {'role_id': role_id, 'name': '角色甲'},
        'knowledge': {'player': {'ready': True, 'stats': {
            'str': 20, 'con': 30, 'int': 40, 'wis': 50,
            'agi': 60, 'attribute_potential': 15}}},
        'attribute_allocation': defaults(),
        'battle': {'active': False},
        'event_flow': {'blocked': False},
        'auto_battle': {'enabled': False},
        'roaming': {'enabled': False},
    }


class AttributeUiGuardTests(unittest.TestCase):
    def test_world_and_automation_guard(self):
        base = snapshot()
        self.assertEqual(preview_block_reason(base), '')
        cases = (
            ({'phase': 'authenticated'}, '登入'),
            ({'knowledge': {'player': {'ready': False}}}, '同步'),
            ({'battle': {'active': True}}, '戰鬥'),
            ({'event_flow': {'blocked': True}}, '事件'),
            ({'auto_battle': {'enabled': True}}, '停止'),
            ({'roaming': {'enabled': True}}, '停止'),
            ({'attribute_allocation': {**defaults(), 'pending': True}}, '尚未確認'),
            ({'attribute_allocation': {**defaults(), 'uncertain': True}}, '重新登入'),
        )
        for delta, expected in cases:
            with self.subTest(delta=delta):
                state = {**base, **delta}
                self.assertIn(expected, preview_block_reason(state))
        self.assertIn('連線', preview_block_reason(base, live=False))

    def test_switching_equal_stat_characters_drops_staged_spend(self):
        old = snapshot(role_id=100)
        new = snapshot(role_id=200)
        window = AttributePointWindow.__new__(AttributePointWindow)
        window.app = SimpleNamespace(snapshot=new, live_active=True)
        window._role_id = 100
        window.base = baseline(old['knowledge']['player']['stats'])
        window.add = {**{k: 0 for k in KEYS}, 'str': 3}
        window.queued = True
        window.role = Mock()
        window.note = Mock()
        window.show_values = Mock()
        window.render(new)
        self.assertEqual(window._role_id, 200)
        self.assertEqual(sum(window.add.values()), 0)
        self.assertFalse(window.queued)
        window.show_values.assert_called_once()

    def test_same_role_refresh_preserves_unsent_preview(self):
        state = snapshot()
        window = AttributePointWindow.__new__(AttributePointWindow)
        window.app = SimpleNamespace(snapshot=state, live_active=True)
        window._role_id = 100
        window.base = baseline(state['knowledge']['player']['stats'])
        window.add = {**{k: 0 for k in KEYS}, 'wis': 2}
        window.queued = False
        window.role = Mock()
        window.note = Mock()
        window.show_values = Mock()
        window.render(state)
        self.assertEqual(window.add['wis'], 2)

    def test_partial_stats_and_ack_order_cannot_duplicate_spending(self):
        state = SimpleNamespace(
            attribute_allocation=defaults(),
            knowledge={'player': {'stats': snapshot()['knowledge']['player']['stats'].copy()}},
        )
        start = baseline(state.knowledge['player']['stats'])
        _packet, expected = allocation(start, {'str': 2, 'wis': 1}, start)
        begin(state, expected, now=1)
        state.knowledge['player']['stats'].update(str=expected['str'])
        apply_event(state, {'type': 'attribute_set'})
        self.assertTrue(state.attribute_allocation['pending'])
        apply_event(state, {'type': 'attribute_allocation_success'})
        self.assertTrue(state.attribute_allocation['pending'])
        state.knowledge['player']['stats'].update(wis=expected['wis'])
        apply_event(state, {'type': 'attribute_set'})
        self.assertTrue(state.attribute_allocation['pending'])
        state.knowledge['player']['stats']['attribute_potential'] = expected['attribute_potential']
        apply_event(state, {'type': 'attribute_set'})
        self.assertFalse(state.attribute_allocation['pending'])

    def test_uncertain_timeout_remains_locked_after_late_ack(self):
        state = SimpleNamespace(attribute_allocation=defaults(),
                                knowledge={'player': {'stats': {}}})
        begin(state, {'str': 22}, now=1)
        self.assertTrue(expire(state, now=20))
        apply_event(state, {'type': 'attribute_allocation_success'})
        self.assertTrue(state.attribute_allocation['uncertain'])
        with self.assertRaises(ProtocolError):
            begin(state, {'str': 22}, now=21)


if __name__ == '__main__':
    unittest.main()
