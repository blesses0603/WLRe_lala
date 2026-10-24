"""Independent offline checks for zero-manual-source candidate indexes."""
import hashlib
import json
import unittest
from unittest.mock import patch

from wlre.services.world.resource_rebuilder import _derive_candidate_indexes


def fixtures(*names):
    return {
        'tables/datapackage_data_a.bundle/' + name + '.bytes':
        ('official fixture ' + name).encode('ascii')
        for name in names
    }


class AutomaticCandidateIndexTests(unittest.TestCase):
    def test_all_four_module_sources_are_grouped_when_downloaded(self):
        data = fixtures('SmithData_C', 'AdventureData_C',
                        'AdventureLvData_C', 'TextData_C',
                        'NpcData_C', 'NpcCareerData_C')
        quest = {
            'tasks': {'1': {'id': 1, 'name_id': 7, 'area_name': 8}},
            'levels': {'1': {'teams': 1}}
        }
        with patch('wlre.services.world.preview_1275.parse_smith_1275',
                   return_value={1234: {'item_id': 1234, 'materials': []}}), \
             patch('wlre.services.expedition.data.parse_catalog',
                   return_value=quest), \
             patch('wlre.services.expedition.data.attach_names',
                   side_effect=lambda q, text: {
                       **q, 'tasks': {'1': {**q['tasks']['1'],
                                          'name': '官方遠征名稱'}}}), \
             patch('wlre.services.expedition.data.parse_npcs',
                   return_value={'7': {'element': 3, 'kind': 1}}):
            candidates = _derive_candidate_indexes(data, revision='1275')
        self.assertEqual(set(candidates), {
            'candidate_indexes/smith_recipes.json',
            'candidate_indexes/expedition_quests.json',
            'candidate_indexes/expedition_npcs.json'})
        for body in candidates.values():
            doc = json.loads(body)
            self.assertEqual(doc['schema_version'], 1)
            self.assertEqual(doc['revision'], 1275)
            self.assertIs(doc['approved'], False)
            self.assertIs(doc['assets_ready'], False)
            self.assertIs(doc['can_send_packets'], False)
            for name, sha in doc['sources'].items():
                self.assertEqual(sha, hashlib.sha256(
                    data['tables/datapackage_data_a.bundle/'
                         + name + '.bytes']).hexdigest())
        quests = json.loads(
            candidates['candidate_indexes/expedition_quests.json'])
        self.assertEqual(quests['records']['tasks']['1']['name'],
                         '官方遠征名稱')
        self.assertIn('TextData_C', quests['sources'])

    def test_no_candidate_for_unknown_future_schema_even_if_name_matches(self):
        data = fixtures('AdventureData_C', 'AdventureLvData_C', 'SmithData_C')
        with patch('wlre.services.expedition.data.parse_catalog') as parser:
            self.assertEqual(
                _derive_candidate_indexes(data, revision='1276'), {})
            parser.assert_not_called()
        self.assertEqual(_derive_candidate_indexes(data, revision='1262'), {})

    def test_missing_text_generates_numeric_only_not_invented_names(self):
        data = fixtures('AdventureData_C', 'AdventureLvData_C')
        with patch('wlre.services.expedition.data.parse_catalog',
                   return_value={'tasks': {'1': {'name_id': 10}},
                                 'levels': {'1': {'teams': 1}}}):
            candidates = _derive_candidate_indexes(data, revision='1275')
        self.assertEqual(set(candidates),
                         {'candidate_indexes/expedition_quests.json'})
        doc = json.loads(next(iter(candidates.values())))
        self.assertNotIn('TextData_C', doc['sources'])
        self.assertNotIn('name', doc['records']['tasks']['1'])

    def test_one_corrupt_table_does_not_block_other_decoders(self):
        data = fixtures('SmithData_C', 'AdventureData_C',
                        'AdventureLvData_C')
        with patch('wlre.services.world.preview_1275.parse_smith_1275',
                   side_effect=ValueError('bad Smith schema')), \
             patch('wlre.services.expedition.data.parse_catalog',
                   return_value={'tasks': {}, 'levels': {}}):
            candidates = _derive_candidate_indexes(data, revision='1275')
        self.assertIn('candidate_indexes/expedition_quests.json',
                      candidates)
        self.assertNotIn('candidate_indexes/smith_recipes.json',
                         candidates)


if __name__ == '__main__':
    unittest.main()
