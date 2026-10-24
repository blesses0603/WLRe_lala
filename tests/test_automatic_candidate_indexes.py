"""Independent offline checks for zero-manual-source candidate indexes."""
import hashlib
import json
import struct
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

    def test_textdata_is_independently_classified_with_source_hash(self):
        from wlre.services.expedition.data import parse_text_data
        value = '星之方舟・遠征'
        payload = value.encode('utf-16-le')
        raw = struct.pack('<iIH', 1, 4101, len(payload)) + payload
        self.assertEqual(parse_text_data(raw), {4101: value})
        candidates = _derive_candidate_indexes(
            {'tables/datapackage_data_t.bundle/TextData_C.bytes': raw},
            revision='1275')
        self.assertEqual(set(candidates), {'candidate_indexes/text_data.json'})
        doc = json.loads(candidates['candidate_indexes/text_data.json'])
        self.assertEqual(doc['source'], 'TextData_C')
        self.assertEqual(doc['record_count'], 1)
        self.assertEqual(doc['records']['4101'], value)
        self.assertEqual(doc['source_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertIs(doc['approved'], False)
        self.assertIs(doc['can_send_packets'], False)
        self.assertIs(doc['assets_ready'], False)
        self.assertNotIn('indexes/npc_text_1275.json.gz', candidates)

    def test_invalid_textdata_does_not_create_or_approve_index(self):
        from wlre.services.expedition.data import parse_text_data
        for raw in (
            b'',
            struct.pack('<i', -1),
            struct.pack('<iIH', 1, 7, 3) + b'ABC',
            struct.pack('<iIH', 1, 7, 4) + b'A',
            struct.pack('<iIH', 1, 7, 2) + b'A\x00' + b'X',
        ):
            with self.subTest(length=len(raw)):
                from wlre.network.wire import ProtocolError
                with self.assertRaises(ProtocolError):
                    parse_text_data(raw)
                self.assertEqual(
                    _derive_candidate_indexes(
                        {'tables/datapackage_data_t.bundle/TextData_C.bytes': raw},
                        revision='1275'), {})

    def test_no_future_version_textdata_decode_attempt(self):
        raw = struct.pack('<iIH', 1, 42, 2) + '好'.encode('utf-16-le')
        with patch('wlre.services.expedition.data.parse_text_data') as parser:
            self.assertEqual(
                _derive_candidate_indexes(
                    {'tables/datapackage_data_t.bundle/TextData_C.bytes': raw},
                    revision='1276'), {})
            parser.assert_not_called()

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
