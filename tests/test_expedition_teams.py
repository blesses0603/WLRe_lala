import copy
import itertools
import json
import random
import unittest

from wlre.paths import RESOURCE_ROOT
from wlre.services.expedition import Expedition, validate
from wlre.services.expedition_teams import choose_members, success_details, condition_met
from test_expedition import ExpeditionFixture, role, catalog


def quest():
    return {'id': 1, 'faith_cost': 2, 'condition': [0, 0, 0], 'success_rate': 500,
            'recommendations': [{'condition': [10, 100, 0], 'bonus': 250},
                                {'condition': [11, 100, 0], 'bonus': 250}]}


class TeamSuccess(unittest.TestCase):
    def test_complementary_team_beats_greedy_top_four_and_uses_fewer_members(self):
        roles = [role(i) for i in range(1, 6)]
        for r in roles:
            r['stats'].update(wis=100 if r['index'] < 5 else 0, agi=100 if r['index'] == 5 else 0)
        team = choose_members(quest(), roles, 80)
        self.assertEqual([r['index'] for r in team], [1, 5])
        self.assertEqual(success_details(quest(), team)['percent'], 100)

    def test_condition_bonus_is_all_or_nothing_and_caps_at_one_hundred(self):
        r = role(); r['stats'].update(wis=99, agi=100)
        self.assertEqual(success_details(quest(), [r])['percent'], 75)
        q = quest(); q['success_rate'] = 900
        self.assertEqual(success_details(q, [r])['percent'], 100)

    def test_all_metadata_conditions_and_original_career_id(self):
        a, b = role(1), role(2)
        npcs = {'101': {'element': 2, 'kind': 0, 'original': 99}, '102': {'element': 3, 'kind': 1, 'original': 102}}
        for condition in ([2, 2, 1], [3, 1, 0], [4, 99, 0], [13, 1, 0], [14, 1, 0]):
            self.assertTrue(condition_met(condition, [a, b], npcs), condition)
        self.assertFalse(condition_met([3, 2, 0], [a, b], npcs))
        self.assertIsNone(condition_met([13, 1, 0], [a]))
        q = quest(); q['recommendations'] = [{'condition': [13, 1, 0], 'bonus': 250}]
        self.assertEqual(success_details(q, [a])['percent'], 50)
        self.assertFalse(success_details(q, [a])['complete'])

    def test_success_has_priority_over_avoiding_faith_items(self):
        weak, strong = role(1, 100), role(2, 70)
        weak['stats'].update(wis=0, agi=0)
        strong['stats'].update(wis=100, agi=100)
        team = choose_members(quest(), [weak, strong], 80)
        self.assertEqual([r['index'] for r in team], [2])

    def test_exact_search_matches_independent_brute_force(self):
        rng = random.Random(1262)
        for _ in range(30):
            roles = [role(i, rng.choice([70, 85, 100])) for i in range(1, 9)]
            for r in roles: r['stats'].update(wis=rng.randrange(80), agi=rng.randrange(80))
            q = quest(); q['condition'] = [1, rng.randint(1, 4), 0]
            expected = None
            for size in range(1, 5):
                if size < q['condition'][1]: continue
                for team in itertools.combinations(roles, size):
                    points = min(1000, 500 + 250 * (sum(r['stats']['wis'] for r in team) >= 100)
                                 + 250 * (sum(r['stats']['agi'] for r in team) >= 100))
                    deficit = sum(max(0, 80-r['faith']) for r in team)
                    cost = sum(r['stats']['level'] + sum(r['stats'][k] for k in ('str','con','int','wis','agi','potential')) for r in team)
                    key = (points, -deficit, -cost, -size, tuple(-r['index'] for r in team))
                    if expected is None or key > expected: expected = key
            team = choose_members(q, roles, 80)
            self.assertEqual(tuple(r['index'] for r in team), tuple(-i for i in expected[-1]))

    def test_official_recommendations_and_npc_metadata_are_bundled(self):
        c = json.loads((RESOURCE_ROOT / 'expedition_catalog.json').read_text())
        self.assertEqual(len(c['npcs']), 7543)
        self.assertTrue(all(len(q['recommendations']) == 4 for q in c['tasks'].values()))
        q = next(q for q in c['tasks'].values() if q['name'] == '入侵威脅 II')
        r = role(); r['stats'].update(wis=100, agi=100)
        self.assertEqual(success_details(q, [r], c['npcs'])['percent'], 100)


class MinimumSuccess(ExpeditionFixture, unittest.TestCase):
    def test_default_and_invalid_minimum(self):
        self.assertEqual(validate({})['min_success'], 75)
        self.assertEqual(validate({})['min_hours'], 0)
        for value in (-1, 101, float('nan'), True):
            with self.assertRaises(ValueError): validate({'min_success': value})

    def test_threshold_is_enforced_at_exact_boundary(self):
        for points, expected in ((749, False), (750, True), (751, True)):
            with self.subTest(points=points):
                state = copy.deepcopy(self.state)
                data = catalog(); data['tasks']['2']['success_rate'] = points
                service = Expedition(data)
                service.start(state, {**self.settings, 'min_success': 75})
                self.assertEqual(bool(service.tick(state, 10)), expected)

    def test_higher_success_task_wins_even_when_shorter(self):
        data = catalog(); data['tasks']['1']['success_rate'] = 900; data['tasks']['2']['success_rate'] = 800
        service = Expedition(data); service.start(self.state, {**self.settings, 'min_hours': 0, 'min_success': 75})
        service.tick(self.state, 10)
        self.assertEqual(service.pending['quest'], 1)
