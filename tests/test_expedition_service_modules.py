"""Backward-compatible expedition service package split.

Keep original import APIs, singleton functions, cached team selection and
server event/automation behavior; full scenarios remain in test_expedition.py.
"""
import unittest

from wlre.services import expedition as legacy
from wlre.services import expedition_data as legacy_data
from wlre.services import expedition_teams as legacy_teams
from wlre.services.expedition import manager, data, teams
from wlre.core.state import State


class ExpeditionServiceModules(unittest.TestCase):
    def test_old_expedition_imports_keep_same_implementation(self):
        names = (
            'Expedition', 'defaults', 'apply_expedition', 'with_deadline',
            'preferences', 'validate', 'faith_gain', 'recovery_stock',
            'duration', 'condition_ok', 'blocked', 'item_totals',
            'claim_space', 'load_catalog', 'choose_members',
            'condition_met', 'success_details',
        )
        for name in names:
            with self.subTest(name=name):
                self.assertIs(getattr(legacy, name), getattr(manager, name))
        self.assertEqual(legacy.Expedition.__module__,
                         'wlre.services.expedition.manager')

    def test_legacy_module_misc_attributes_remain_accessible(self):
        self.assertIs(legacy.CAT, manager.CAT)
        self.assertIs(legacy.Writer, manager.Writer)
        self.assertIs(legacy.STACKABLE, manager.STACKABLE)

    def test_original_data_and_team_paths_are_compatible(self):
        for name in ('data_root', 'parse_catalog', 'load_catalog',
                     'attach_names', 'parse_npcs'):
            with self.subTest(name=name):
                self.assertIs(getattr(legacy_data, name), getattr(data, name))
        for name in ('condition_met', 'success_details', 'choose_members',
                     '_choose_cached'):
            with self.subTest(name=name):
                self.assertIs(getattr(legacy_teams, name), getattr(teams, name))

    def test_cached_team_search_is_singleton_and_empty_input(self):
        self.assertIs(legacy_teams._choose_cached, teams._choose_cached)
        self.assertEqual(legacy_teams._choose_cached.cache_info(),
                         teams._choose_cached.cache_info())
        self.assertEqual(legacy.choose_members(
            {'faith_cost': 0, 'condition': [0, 0, 0],
             'success_rate': 0, 'recommendations': []}, [], 80), [])

    def test_state_uses_same_expedition_defaults_and_server_applicator(self):
        state = State()
        self.assertEqual(state.expedition, manager.defaults())
        event = {'type': 'expedition_level', 'level': 1}
        state.apply(event)
        self.assertEqual(state.expedition['level'], 1)
        self.assertEqual(state.expedition['revision'], 1)

    def test_catalog_loader_has_same_implementation(self):
        self.assertIs(legacy.load_catalog, legacy_data.load_catalog)
        catalog = data.load_catalog()
        self.assertEqual(len(catalog['tasks']), 260)
        self.assertEqual(len(catalog['levels']), 10)


if __name__ == '__main__':
    unittest.main()


# Historical 1262 fixtures require an explicit test-only baseline.
from unittest.mock import patch as _legacy_baseline_patch
_legacy_baseline_context = None

def setUpModule():
    global _legacy_baseline_context
    _legacy_baseline_context = _legacy_baseline_patch(
        'wlre.services.world.runtime_1275.baseline_revision', return_value='1262')
    _legacy_baseline_context.start()

def tearDownModule():
    _legacy_baseline_context.stop()
